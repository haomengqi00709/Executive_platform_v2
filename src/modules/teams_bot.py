"""
Teams Chat Bot — polling loop and receipt detection.

All conversation logic lives in src/bot/.
This module is responsible for:
  1. Polling the Teams 1:1 chat for new messages
  2. Detecting receipt attachments and routing them to the expense agent
  3. Calling bot_app.invoke() for each new text message
  4. Persisting activation state (last_seen_ts, timing gates) back to teams_bot.json

State that was previously in teams_bot.json (pending_draft, pending_expense,
pending_meeting_drafts, chat_history, etc.) now lives exclusively in the
LangGraph SqliteSaver at .data/{user_id}/bot.sqlite.
"""

import re
from pathlib import Path


# ── Receipt extraction (unchanged from original) ──────────────────────────

_RECEIPT_EXTS  = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".tiff"}
_RECEIPT_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/gif",
                  "image/webp", "application/pdf", "image/tiff"}


def _mime_for_ext(ext: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif",  ".webp": "image/webp",  ".pdf": "application/pdf",
        ".tiff": "image/tiff",
    }.get(ext, "application/octet-stream")


def _extract_receipt_bytes(msg: dict, chat_id: str, graph, owner_graph=None) -> tuple:
    """
    Try to extract image/document bytes from a Teams message.
    Returns (bytes, mime, filename) or (None, '', '').
    """
    import requests as _req

    msg_id = msg.get("id", "")
    print(f"[ExpenseAgent] Checking message {msg_id} — attachments: {msg.get('attachments', [])}")

    for att in msg.get("attachments", []):
        name   = att.get("name") or ""
        ext    = Path(name).suffix.lower()
        ctype  = (att.get("contentType") or "").lower()
        att_id = att.get("id", "")

        print(f"[ExpenseAgent] Attachment: name={name!r} type={ctype!r} id={att_id!r}")

        if ext not in _RECEIPT_EXTS and ctype not in _RECEIPT_MIMES:
            continue

        content_url = att.get("contentUrl") or ""
        if content_url:
            import re as _re
            from urllib.parse import unquote as _unquote
            sp_match = _re.match(
                r'https://[^/]+-my\.sharepoint\.com/personal/[^/]+/(.+)',
                content_url
            )
            if sp_match and owner_graph:
                import base64 as _b64
                from urllib.parse import quote as _quote

                drive_path = _unquote(sp_match.group(1))

                try:
                    b64      = _b64.urlsafe_b64encode(content_url.encode()).rstrip(b"=").decode()
                    share_id = f"u!{b64}"
                    meta     = owner_graph.get(f"/shares/{share_id}/driveItem")
                    dl_url   = meta.get("@microsoft.graph.downloadUrl")
                    if dl_url:
                        r = _req.get(dl_url, allow_redirects=True, timeout=30)
                        r.raise_for_status()
                        return r.content, _mime_for_ext(ext), name
                    item_id = meta.get("id")
                    if item_id:
                        return owner_graph.download(f"/me/drive/items/{item_id}/content"), _mime_for_ext(ext), name
                except Exception as e:
                    print(f"[ExpenseAgent] Shares API failed: {e}")

                encoded_path = _quote(drive_path, safe="/")
                try:
                    return owner_graph.download(f"/me/drive/root:/{encoded_path}:/content"), _mime_for_ext(ext), name
                except Exception as e:
                    print(f"[ExpenseAgent] OneDrive path failed: {e}")

                try:
                    fname  = Path(drive_path).name
                    search = owner_graph.get(f"/me/drive/root/search(q='{fname}')")
                    for item in (search.get("value") or []):
                        if (item.get("name") or "").lower() == fname.lower():
                            return owner_graph.download(f"/me/drive/items/{item['id']}/content"), _mime_for_ext(ext), name
                except Exception as e:
                    print(f"[ExpenseAgent] OneDrive search failed: {e}")
            else:
                for dl_graph in ([owner_graph, graph] if owner_graph else [graph]):
                    if dl_graph is None:
                        continue
                    try:
                        r = _req.get(content_url, headers=dl_graph.headers, timeout=30, allow_redirects=True)
                        r.raise_for_status()
                        return r.content, _mime_for_ext(ext), name
                    except Exception as e:
                        print(f"[ExpenseAgent] contentUrl failed: {e}")

        if att_id and chat_id and msg_id:
            try:
                img_bytes = graph.download(
                    f"/me/chats/{chat_id}/messages/{msg_id}/hostedContents/{att_id}/$value"
                )
                mime = ctype if ctype in _RECEIPT_MIMES else _mime_for_ext(ext)
                return img_bytes, mime, name or f"receipt_{att_id}.jpg"
            except Exception as e:
                print(f"[ExpenseAgent] hostedContent failed: {e}")

    # Inline images pasted into chat
    body_html = msg.get("body", {}).get("content", "")
    for hc_id in re.findall(r"hostedContents/([^/$'\"]+)/\$value", body_html):
        try:
            img_bytes = graph.download(
                f"/me/chats/{chat_id}/messages/{msg_id}/hostedContents/{hc_id}/$value"
            )
            return img_bytes, "image/jpeg", f"inline_{hc_id}.jpg"
        except Exception as e:
            print(f"[ExpenseAgent] inline hostedContent failed: {e}")

    return None, "", ""


def _handle_teams_receipt(msg: dict, chat_id: str, graph, ai,
                           owner_graph=None, data_dir=None) -> tuple:
    """
    Route a Teams message to the Expense Agent.
    Returns (reply_str | None, pending_expense | None).
    pending_expense is non-None only when a field-duplicate is detected.
    """
    import openpyxl
    from datetime import datetime
    from src.modules.m05_expense import (
        _extract_from_attachment, _append_row, _init_workbook,
        _load_seen, _save_seen, _load_hashes, _save_hashes, _compute_hash,
        _find_field_match, MASTER_FILE, EXPENSES_DIR,
    )

    if data_dir:
        expenses_dir = Path(data_dir) / "expenses"
        master_file  = expenses_dir / "expenses_master.xlsx"
        seen_file    = expenses_dir / "_seen.json"
        hashes_file  = expenses_dir / "_receipt_hashes.json"
    else:
        expenses_dir = EXPENSES_DIR
        master_file  = MASTER_FILE
        seen_file    = None
        hashes_file  = None

    msg_id    = msg.get("id", "")
    dedup_key = f"teams_chat::{msg_id}"
    seen      = _load_seen(seen_file)
    if dedup_key in seen:
        return None, None

    img_bytes, mime, filename = _extract_receipt_bytes(msg, chat_id, graph, owner_graph)
    if not img_bytes:
        return None, None

    hashes = _load_hashes(hashes_file)
    h      = _compute_hash(img_bytes)
    if h in hashes:
        seen.add(dedup_key)
        _save_seen(seen, seen_file)
        return "This receipt has already been captured (exact duplicate).", None

    print(f"[ExpenseAgent] Processing Teams receipt: {filename}")
    result = _extract_from_attachment(img_bytes, mime, filename, ai)

    if owner_graph:
        try:
            owner_graph.upload_to_onedrive(f"CEO Platform/Receipts/{filename}", img_bytes, mime)
        except Exception as e:
            print(f"[ExpenseAgent] OneDrive upload failed: {e}")

    seen.add(dedup_key)
    _save_seen(seen, seen_file)

    if not result or not result.get("is_receipt"):
        return ("I received your attachment but it doesn't look like a receipt or invoice. "
                "If this is an expense document, please send the actual receipt image."), None

    today      = datetime.now().strftime("%Y-%m-%d")
    amount     = result.get("amount") or 0
    gst_hst    = result.get("gst_hst") or 0
    net_amount = result.get("net_amount") or (round(amount - gst_hst, 2) if gst_hst else "")

    new_row = {
        "Date":           result.get("date", today),
        "Vendor":         result.get("vendor", ""),
        "Amount":         amount,
        "Currency":       result.get("currency", "CAD"),
        "GST_HST":        gst_hst or "",
        "Net_Amount":     net_amount,
        "Category":       result.get("category", "Other"),
        "Attachment":     filename,
        "Email_Subject":  "[Teams Chat]",
        "From":           "teams",
        "Msg_ID":         msg_id,
        "Att_ID":         "",
        "Processed_Date": today,
    }

    existing = _find_field_match(master_file, result.get("vendor",""), amount, result.get("date",""))
    if existing:
        pending = {
            "new_row":       new_row,
            "existing_row":  existing,
            "new_file":      f"CEO Platform/Receipts/{filename}",
            "existing_file": f"CEO Platform/Receipts/{existing.get('Attachment','')}",
            "hash":          h,
            "hashes_file":   str(hashes_file) if hashes_file else None,
            "master_file":   str(master_file),
            "expenses_dir":  str(expenses_dir),
        }
        reply = (
            f"⚠️ Possible duplicate receipt detected!\n\n"
            f"New:   {result.get('vendor','?')} | {amount} {result.get('currency','CAD')} | {result.get('date','?')}\n"
            f"       📎 {filename} → OneDrive: CEO Platform/Receipts/{filename}\n\n"
            f"Existing: {existing.get('Vendor','?')} | {existing.get('Amount','?')} "
            f"{existing.get('Currency','CAD')} | {existing.get('Date','?')}\n\n"
            f"Reply YES to record as a new expense, or NO to discard."
        )
        return reply, pending

    expenses_dir.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(master_file) if master_file.exists() else _init_workbook()
    _append_row(wb.active, new_row)
    wb.save(master_file)
    hashes[h] = filename
    _save_hashes(hashes, hashes_file)

    conf = {"high": "✅ High", "medium": "⚠️ Medium", "low": "⚠️ Low"}.get(
        result.get("confidence", ""), "?"
    )
    return (
        f"✅ Receipt captured!\n\n"
        f"Vendor: {result.get('vendor','Unknown')}\n"
        f"Date: {result.get('date','?')}\n"
        f"Amount: {amount} {result.get('currency','CAD')}\n"
        f"GST/HST: {gst_hst or 'N/A'}\n"
        f"Category: {result.get('category','Other')}\n"
        f"Confidence: {conf}\n\n"
        f"Saved to expense report."
    ), None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


# ── Public API ────────────────────────────────────────────────────────────

def poll_and_reply(bot_state: dict, graph, ai, owner_graph=None,
                   owner_wiki_dir=None, owner_settings=None,
                   owner_settings_path=None, owner_context_path=None,
                   owner_data_dir=None, bot_state_path=None) -> dict:
    """
    Poll Teams chat for new messages and reply using Gemini function calling bot.
    Conversation state (pending_draft, pending_expense, etc.) lives in bot_state.json.
    """
    from src import bot as _bot

    peer_email = bot_state.get("peer_email", "")
    if not peer_email:
        return bot_state

    chat_id      = bot_state.get("chat_id")
    last_seen_ts = bot_state.get("last_seen_ts") or ""

    if not chat_id:
        chat_id = graph.find_chat_with_user(peer_email)
        if not chat_id:
            print(f"[TeamsBot] No 1:1 chat with {peer_email} yet — waiting")
            return bot_state
        bot_state["chat_id"] = chat_id
        print(f"[TeamsBot] Chat found with {peer_email}")

    me    = graph.get_me()
    my_id = me.get("id", "")

    messages = graph.get_chat_messages(chat_id, top=25)

    # First activation: fast-forward past existing messages
    if not last_seen_ts:
        timestamps = [m.get("createdDateTime", "") for m in messages if m.get("createdDateTime")]
        if timestamps:
            bot_state["last_seen_ts"] = max(timestamps)
        return bot_state

    new_msgs = sorted(
        [
            m for m in messages
            if m.get("messageType") == "message"
            and m.get("from", {}).get("user", {}).get("id", "") != my_id
            and m.get("createdDateTime", "") > last_seen_ts
        ],
        key=lambda m: m.get("createdDateTime", ""),
    )

    if not new_msgs:
        return bot_state

    owner_uid    = bot_state.get("owner_uid") or ""
    wiki_dir     = Path(owner_wiki_dir)    if owner_wiki_dir    else None
    data_dir     = Path(owner_data_dir)    if owner_data_dir    else None
    settings     = owner_settings or {}

    for msg in new_msgs:
        last_seen_ts = msg["createdDateTime"]

        # Receipt attachment handling
        expense_reply, pending_expense = _handle_teams_receipt(
            msg, chat_id, graph, ai, owner_graph, owner_data_dir
        )
        if pending_expense:
            bot_state["pending_expense"] = pending_expense
        if expense_reply is not None:
            graph.send_chat_message(chat_id, expense_reply)
            continue

        text = _strip_html(msg.get("body", {}).get("content", "")).strip()
        if not text:
            continue

        sender = msg.get("from", {}).get("user", {}).get("displayName", "Colleague")
        print(f"[TeamsBot] {sender}: {text[:80]}")

        try:
            reply_text, bot_state = _bot.reply(
                bot_state, text, graph, owner_graph,
                settings, wiki_dir, data_dir,
            )
            graph.send_chat_message(chat_id, reply_text)
        except Exception as e:
            import traceback
            print(f"[TeamsBot] Bot error: {e}")
            traceback.print_exc()
            try:
                graph.send_chat_message(chat_id, f"Sorry, I hit an error: {e}")
            except Exception:
                pass

    bot_state["last_seen_ts"] = last_seen_ts
    return bot_state
