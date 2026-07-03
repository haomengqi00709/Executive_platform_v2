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

_RECEIPT_EXTS  = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".tiff",
                  ".csv", ".xlsx", ".xls"}
_RECEIPT_MIMES = {"image/jpeg", "image/jpg", "image/png", "image/gif",
                  "image/webp", "application/pdf", "image/tiff",
                  "text/csv", "application/csv",
                  "application/vnd.ms-excel",
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
_TABULAR_EXTS  = {".csv", ".xlsx", ".xls"}


def _classify_tabular_purpose(ai, file_bytes: bytes, ext: str) -> str:
    """Show AI the header + first 3 data rows of a tabular file, ask what it's for.

    Returns one of:
      'contact_list'  — names/emails/companies, suitable for outreach
      'other'         — unknown / not yet supported

    Future doc-types can be added here without changing the upstream router.
    """
    import csv as _csv, io as _io
    sample_rows: list = []
    try:
        if ext == ".csv":
            text = file_bytes.decode("utf-8-sig", errors="replace")
            reader = _csv.reader(_io.StringIO(text))
            for i, row in enumerate(reader):
                if i >= 4:
                    break
                sample_rows.append(row)
        else:
            import openpyxl, tempfile, os
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(file_bytes)
                tmp = f.name
            wb = openpyxl.load_workbook(tmp, data_only=True)
            ws = wb.active
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 4:
                    break
                sample_rows.append([str(c) if c is not None else "" for c in row])
            try:
                os.unlink(tmp)
            except Exception:
                pass
    except Exception as e:
        print(f"[TabularClassify] Parse failed: {e}")
        return "other"

    if not sample_rows:
        return "other"

    preview = "\n".join("\t".join(r) for r in sample_rows[:4])
    prompt = f"""Look at this table sample (header + up to 3 data rows). What is this file for?

Sample:
{preview}

Return JSON with one field:
"purpose": one of:
  - "contact_list"  — a list of people with names/emails/companies (suitable for outreach)
  - "other"         — anything else (financial report, project tracker, inventory, etc.)

Respond with valid JSON only."""

    try:
        raw = ai.extract_json(prompt)
        import json as _j, re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            return _j.loads(m.group()).get("purpose", "other")
    except Exception as e:
        print(f"[TabularClassify] AI failed: {e}")
    return "other"


def _mime_for_ext(ext: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif",  ".webp": "image/webp",  ".pdf": "application/pdf",
        ".tiff": "image/tiff",
        ".csv":  "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls":  "application/vnd.ms-excel",
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


def _store_incoming_file(owner_graph, filename, file_bytes, mime, doc_type="file", summary="") -> dict | None:
    """Upload an incoming Teams file to OneDrive (receipts → Receipts/, everything else → Inbox/) so the
    conversational agent can act on it later ('forward this to X'). Returns a file-handle dict."""
    folder = "Receipts" if doc_type == "receipt" else "Inbox"
    onedrive_path = f"CEO Platform/{folder}/{filename}"
    if owner_graph:
        try:
            owner_graph.upload_to_onedrive(onedrive_path, file_bytes, mime or "application/octet-stream")
        except Exception as e:
            print(f"[TeamsFile] OneDrive upload failed: {e}")
    return {"filename": filename, "mime": mime, "doc_type": doc_type,
            "summary": summary, "onedrive_path": onedrive_path}


def _expense_summary(item: dict) -> str:
    dt = item.get("document_type")
    if dt == "invoice":
        return (f"invoice from {item.get('vendor','?')} for {item.get('amount','?')} "
                f"{item.get('currency','')} due {item.get('due_date') or '?'}")
    if dt == "contract":
        return f"contract with {item.get('counterparty','?')} — {item.get('subject','')}"
    return f"receipt from {item.get('vendor','?')} for {item.get('amount','?')} {item.get('currency','')}"


def _expense_capture_reply(item: dict) -> str:
    dt = item.get("document_type")
    if dt == "invoice":
        return (f"🧾 Invoice saved — {item.get('vendor','?')} | {item.get('amount','?')} "
                f"{item.get('currency','CAD')} | due {item.get('due_date') or '?'}. It's in your dashboard under Invoices.")
    if dt == "contract":
        return (f"📄 Contract saved — {item.get('counterparty','?')} · {item.get('subject','')}. "
                f"It's in your dashboard under Contracts.")
    return (f"✅ Receipt captured — {item.get('vendor','?')} | {item.get('amount','?')} "
            f"{item.get('currency','CAD')} [{item.get('category','Other')}]. Added to your expense report.")


def _handle_teams_receipt(msg: dict, chat_id: str, graph, ai,
                           owner_graph=None, data_dir=None, settings=None, bot_state=None) -> tuple:
    """
    Route a Teams attachment to the right pipeline.
    AI classifies the document — receipt/invoice/contract → expenses store (all three persist now);
    business_card → CRM ingest + auto-draft outreach. The file is also stored to OneDrive and a handle
    is put on bot_state["pending_file"] so the agent can act on it ("forward this to X").
    Returns (reply_str | None, pending_expense | None).
    """
    # Check for attachment bytes first — no heavy imports until we know there's a receipt
    img_bytes, mime, filename = _extract_receipt_bytes(msg, chat_id, graph, owner_graph)
    if not img_bytes:
        return None, None

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

    # ── Early branch: CSV / XLSX → AI classifies purpose, then route ──
    ext = Path(filename).suffix.lower()
    if ext in _TABULAR_EXTS:
        seen.add(dedup_key)
        _save_seen(seen, seen_file)
        purpose = _classify_tabular_purpose(ai, img_bytes, ext)
        print(f"[ExpenseAgent] Tabular file purpose: {purpose}")
        if purpose == "contact_list":
            from src.modules.outreach import _extract_from_csv, _extract_from_xlsx
            raw_contacts = _extract_from_csv(img_bytes) if ext == ".csv" else _extract_from_xlsx(img_bytes)
            # Reuse business_card path below by faking the result shape
            result = {"document_type": "business_card", "contacts": raw_contacts}
            doc_type = "business_card"
            _skip_vision = True
        else:
            return (f"I received a {ext.lstrip('.').upper()} file but it doesn't look like a contact list. "
                    f"Currently I can only process contact lists from CSV/Excel files. "
                    f"Other file types (financial reports, project trackers, etc.) aren't supported yet."), None
    else:
        _skip_vision = False

    # Skip receipt-hash dedup for tabular files (CSV/XLSX) — receipt hashing is image-only
    hashes = _load_hashes(hashes_file) if not _skip_vision else {}
    h      = _compute_hash(img_bytes) if not _skip_vision else ""
    if not _skip_vision and h in hashes:
        seen.add(dedup_key)
        _save_seen(seen, seen_file)
        meta  = hashes[h]
        _today = datetime.now().strftime("%Y-%m-%d")
        if isinstance(meta, dict):
            item = {
                "document_type": "receipt",
                "vendor":        meta.get("vendor", ""),
                "counterparty":  "",
                "date":          meta.get("date", ""),
                "due_date":      None,
                "amount":        meta.get("amount", 0),
                "currency":      meta.get("currency", "CAD"),
                "gst_hst":       "", "net_amount": "",
                "category":      meta.get("category", "Other"),
                "subject":       "", "confidence": "",
                "attachment":    meta.get("filename", filename),
                "email_subject": "[Teams Chat]", "from": "teams",
                "msg_id":        msg_id, "att_id": "",
                "processed_at":  _today, "source_type": "teams", "sha256": h,
            }
            pending = {"item": item, "hash": h,
                       "hashes_file": str(hashes_file) if hashes_file else None, "is_hash_dup": True}
            reply = (
                f"⚠️ This receipt was already captured on {meta.get('processed_date', '?')}.\n\n"
                f"Vendor: {meta.get('vendor', '?')}\n"
                f"Amount: {meta.get('amount', '?')} {meta.get('currency', '')}\n"
                f"Date: {meta.get('date', '?')}\n\n"
                f"Reply YES to add as a new expense entry anyway, or NO to discard."
            )
            return reply, pending
        return "This receipt has already been captured (exact duplicate). No action taken.", None

    if not _skip_vision:
        print(f"[ExpenseAgent] Processing Teams attachment: {filename}")
        result = _extract_from_attachment(img_bytes, mime, filename, ai)

        seen.add(dedup_key)
        _save_seen(seen, seen_file)

        if not result:
            return ("I received your attachment but couldn't analyze it. "
                    "If this is a receipt or contact card, please resend a clearer image."), None

        doc_type = result.get("document_type", "")

    # ── Business card / contact list → CRM ingest + auto-draft ────────
    if doc_type == "business_card":
        from src.modules.crm import add_contacts_bulk
        from src.modules.outreach import _generate_draft
        from src.modules.profile import load_profile_context, get_user_signature, append_signature_to_body

        raw_contacts = result.get("contacts") or []
        skipped_no_email = sum(1 for c in raw_contacts if not (c.get("email") or "").strip())
        valid_contacts = [c for c in raw_contacts if (c.get("email") or "").strip()]

        if not valid_contacts:
            return ("I detected a business card / contact list, but no email addresses were visible. "
                    "Please resend a clearer image, or include an email in your message."), None

        bulk_result = add_contacts_bulk(data_dir, valid_contacts, source="teams_card")

        # Auto-draft outreach for newly added contacts (skip already-existing ones)
        _settings = settings or {}
        display_name     = _settings.get("display_name", "the executive")
        business_context = load_profile_context(data_dir) if data_dir else ""
        writing_style    = _settings.get("writing_style_note", "")
        user_signature   = get_user_signature(_settings)
        # Use any text the user sent alongside the photo as context
        body_text = _strip_html(msg.get("body", {}).get("content", "")).strip()
        context_note = body_text or "Following up from our recent meeting"

        draft_links = {}
        if owner_graph:
            for c in valid_contacts:
                email = c["email"].strip().lower()
                if bulk_result["by_email"].get(email) != "added":
                    continue  # already in CRM, don't re-draft
                draft = _generate_draft(ai, c, context_note,
                                        display_name, business_context, writing_style)
                if not draft:
                    continue
                final_body = append_signature_to_body(draft["body"], user_signature)
                try:
                    gr = owner_graph.create_draft(subject=draft["subject"], body=final_body, to=email)
                    web_link = gr.get("webLink", "")
                    draft_links[email] = web_link
                    # Persist link on the contact
                    try:
                        from src.modules.crm import update_contact
                        if web_link:
                            update_contact(data_dir, email, "draft_link", web_link)
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[ContactIngest] Draft create failed for {email}: {e}")

        # Append newly added contacts to the OneDrive master Excel
        # (read-only mirror of CRM — user can open in Excel app or share).
        if bulk_result.get("added") and owner_graph:
            try:
                from src.modules.contacts_excel import append_contacts as _excel_append
                from src.modules.crm import load_crm
                crm = load_crm(data_dir).get("contacts", {})
                # Pull the enriched CRM records (with added_at, draft_link, source, tags)
                # for the contacts we just added in this batch
                added_emails = {
                    e for e, status in bulk_result["by_email"].items()
                    if status == "added"
                }
                rows = [crm[e] for e in added_emails if e in crm]
                xr = _excel_append(owner_graph, rows)
                if xr.get("error"):
                    print(f"[ContactIngest] OneDrive excel append failed: {xr['error']}")
                else:
                    print(f"[ContactIngest] Appended {xr['appended']} rows to OneDrive contacts_master.xlsx")
            except Exception as e:
                print(f"[ContactIngest] OneDrive excel append error: {e}")

        # Build reply
        lines = [f"🆕 Captured {bulk_result['added']} new contact{'s' if bulk_result['added'] != 1 else ''}:"]
        for c in valid_contacts:
            email = c["email"].strip().lower()
            if bulk_result["by_email"].get(email) != "added":
                continue
            name = c.get("name") or email
            company = c.get("company", "")
            role = c.get("role", "")
            details = " · ".join(filter(None, [role, company]))
            lines.append(f"• {name}" + (f" — {details}" if details else "") + f" ({email})")
        if bulk_result["updated"]:
            lines.append(f"\n({bulk_result['updated']} already in CRM — merged tags/notes, no new draft)")
        if skipped_no_email:
            lines.append(f"({skipped_no_email} card{'s' if skipped_no_email != 1 else ''} skipped — no email visible)")
        if draft_links:
            lines.append(f"\n📬 {len(draft_links)} draft{'s' if len(draft_links) != 1 else ''} saved to Outlook.")
        if bulk_result["added"]:
            lines.append(f"📊 Updated OneDrive › Conferences › contacts_master.xlsx")
            lines.append("Send 'tag as X' to group these contacts.")

        return "\n".join(lines), None

    # ── receipt / invoice / contract → expenses store (ALL THREE persist now) ──
    if doc_type not in ("receipt", "invoice", "contract"):
        # A file we can't file as an expense or a card — still keep it so the agent can act on it.
        if bot_state is not None:
            bot_state["pending_file"] = _store_incoming_file(owner_graph, filename, img_bytes, mime, "file", "")
        return ("I saved that file. Tell me what you'd like me to do with it — forward it to someone, "
                "or file it as a receipt / invoice / contract."), None

    today  = datetime.now().strftime("%Y-%m-%d")
    amount = result.get("amount") or 0
    gst    = result.get("gst_hst") or 0
    net    = result.get("net_amount") or (round(amount - gst, 2) if gst else "")
    item = {
        "document_type": doc_type,
        "vendor":        result.get("vendor", ""),
        "counterparty":  result.get("counterparty", ""),
        "date":          result.get("date", today),
        "due_date":      result.get("due_date"),
        "amount":        amount,
        "currency":      result.get("currency", "CAD"),
        "gst_hst":       gst or "",
        "net_amount":    net,
        "category":      result.get("category", "Other"),
        "subject":       result.get("subject", ""),
        "confidence":    result.get("confidence", ""),
        "attachment":    filename,
        "email_subject": "[Teams Chat]",
        "from":          "teams",
        "msg_id":        msg_id,
        "att_id":        "",
        "processed_at":  today,
        "source_type":   "teams",
        "sha256":        h,
    }

    # Receipt duplicate-by-fields confirm (reads the synced xlsx projection).
    if doc_type == "receipt":
        existing = _find_field_match(master_file, result.get("vendor", ""), amount, result.get("date", ""))
        if existing:
            pending = {"item": item, "hash": h,
                       "hashes_file": str(hashes_file) if hashes_file else None, "is_hash_dup": False}
            reply = (
                f"⚠️ Possible duplicate receipt detected!\n\n"
                f"New:   {result.get('vendor','?')} | {amount} {result.get('currency','CAD')} | {result.get('date','?')}\n"
                f"Existing: {existing.get('Vendor','?')} | {existing.get('Amount','?')} "
                f"{existing.get('Currency','CAD')} | {existing.get('Date','?')}\n\n"
                f"Reply YES to record as a new expense, or NO to discard."
            )
            return reply, pending

    # Store the file to OneDrive + persist the expense (receipt/invoice/contract all go to the store).
    file_info = _store_incoming_file(owner_graph, filename, img_bytes, mime, doc_type, _expense_summary(item))
    item["onedrive_path"] = (file_info or {}).get("onedrive_path")
    if data_dir:
        from src.modules import expenses_store
        expenses_store.upsert_expense(data_dir, item)
    if h and hashes_file is not None:
        hashes[h] = {"filename": filename, "vendor": item["vendor"], "amount": amount,
                     "currency": item["currency"], "date": item["date"],
                     "category": item["category"], "processed_date": today}
        _save_hashes(hashes, hashes_file)
    if bot_state is not None and file_info:
        bot_state["pending_file"] = file_info

    return _expense_capture_reply(item), None


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
        print(f"[TeamsBot] Fast-forward → last_seen_ts={bot_state.get('last_seen_ts')!r}")
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

    # Log ONLY when there's something to act on. The old per-poll prints (Fetched N /
    # per-msg dump / "0 new msgs") fired every 10s per bot and were ~94% of all prod log
    # volume — that's what burned Railway's retention down to ~6 days and buried every
    # cost signal. Silence on empty polls; one line when a real message arrives.
    if not new_msgs:
        return bot_state
    print(f"[TeamsBot] {len(new_msgs)} new msg(s) to handle")

    owner_uid       = bot_state.get("owner_uid") or ""
    wiki_dir        = Path(owner_wiki_dir)    if owner_wiki_dir    else None
    data_dir        = Path(owner_data_dir)    if owner_data_dir    else None
    settings        = owner_settings or {}
    user_model_path = (data_dir / "user_model.json") if data_dir else None

    for msg in new_msgs:
        last_seen_ts = msg["createdDateTime"]

        # ── Stage 1: deterministic auto-capture (receipt/invoice/contract → store, card → CRM).
        # Also stores any incoming file to OneDrive + puts a handle on bot_state["pending_file"] so
        # the agent (stage 3) can act on it ("forward this to X"). Runs cheaply, no agent needed.
        capture_reply, pending_expense = _handle_teams_receipt(
            msg, chat_id, graph, ai, owner_graph, owner_data_dir, settings=settings, bot_state=bot_state
        )
        if pending_expense:
            bot_state["pending_expense"] = pending_expense
        if capture_reply is not None:
            graph.send_chat_message(chat_id, capture_reply)

        text = _strip_html(msg.get("body", {}).get("content", "")).strip()

        # ── Stage 2: a bare capture with no request text is done — skip the agent (cheap + automatic).
        if not text:
            continue

        # ── Stage 3: the user asked something — run the agent WITH the file in context (pending_file),
        # so requests like "forward this to Bob" work while the auto-capture above still happened.
        sender = msg.get("from", {}).get("user", {}).get("displayName", "Colleague")
        print(f"[TeamsBot] {sender}: {text[:80]}")

        try:
            reply_text, bot_state = _bot.reply(
                bot_state, text, graph, owner_graph,
                settings, wiki_dir, data_dir,
                user_model_path=user_model_path,
            )
            if "<a href=" in reply_text:
                graph.send_html_message(chat_id, reply_text)
            else:
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
