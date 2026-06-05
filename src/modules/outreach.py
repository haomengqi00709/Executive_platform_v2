"""
Outreach Tool — batch-generate personalized email drafts from a OneDrive folder.

Scenario: user attends a conference, collects contacts (business cards, attendee lists,
CSV exports). They drop the files into a OneDrive folder. This tool reads each file,
extracts contact info, and creates a personalized Outlook Draft for every contact.

NOT a section — it's an on-demand personalized tool. Output goes to data_dir/outreach/
(not data_dir/results/, which is sections-only).

Entry point: run(graph, ai, data_dir, settings, context_note, folder)
"""
import csv
import io
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
except ImportError:
    openpyxl = None

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.profile import load_profile_context, get_user_signature, append_signature_to_body


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_PDF_EXTS   = {".pdf"}
_CSV_EXTS   = {".csv"}
_XLSX_EXTS  = {".xlsx", ".xls"}


def _load_state(data_dir: Path) -> dict:
    f = Path(data_dir) / "outreach.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    return {"processed_files": {}, "history": []}


def _save_state(data_dir: Path, state: dict) -> None:
    f = Path(data_dir) / "outreach.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(f)


def _save_result(data_dir: Path, result: dict) -> None:
    out_dir = Path(data_dir) / "outreach"
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / "results.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    tmp.replace(f)


# ── Contact extraction by file type ─────────────────────────────────────────

def _extract_from_image(ai: AIClient, file_bytes: bytes, ext: str) -> list[dict]:
    """Gemini Vision: extract single contact from a business card photo."""
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".webp": "image/webp"}
    mime = mime_map.get(ext, "image/jpeg")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name

    try:
        from google.genai import types as genai_types
        uploaded = ai.client.files.upload(file=tmp_path)
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = ai.client.files.get(name=uploaded.name)

        prompt = """This is a business card photo. Extract the contact info.
Return JSON: {"name": "...", "email": "...", "company": "...", "role": "..."}
If a field is missing, use empty string. If this is NOT a business card, return {"name": ""}."""

        response = ai.client.models.generate_content(
            model=ai.model,
            contents=[
                genai_types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime),
                prompt,
            ],
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return [data] if data.get("email") else []
    except Exception as e:
        print(f"[Outreach] Image extract failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return []


def _extract_from_pdf(ai: AIClient, file_bytes: bytes) -> list[dict]:
    """Gemini multimodal: extract list of contacts from a PDF (attendee list, roster, etc.)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name

    try:
        from google.genai import types as genai_types
        uploaded = ai.client.files.upload(file=tmp_path)
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = ai.client.files.get(name=uploaded.name)

        prompt = """This PDF likely contains a list of contacts (conference attendees, roster, exported list).
Extract every contact you can find.
Return JSON: {"contacts": [{"name": "...", "email": "...", "company": "...", "role": "..."}, ...]}
Skip rows without an email. If no contacts found, return {"contacts": []}."""

        response = ai.client.models.generate_content(
            model=ai.model,
            contents=[
                genai_types.Part.from_uri(file_uri=uploaded.uri, mime_type="application/pdf"),
                prompt,
            ],
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return [c for c in data.get("contacts", []) if c.get("email")]
    except Exception as e:
        print(f"[Outreach] PDF extract failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    return []


def _extract_from_csv(file_bytes: bytes) -> list[dict]:
    """Parse CSV. Try to map columns to name/email/company/role by header name."""
    contacts = []
    try:
        text = file_bytes.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        _known_keys = {"email", "e-mail", "email address", "name", "first name", "last name",
                       "company", "organization", "org", "role", "title", "job title"}
        for row in reader:
            normalized = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
            email = (normalized.get("email") or normalized.get("e-mail")
                     or normalized.get("email address") or "")
            if not email or "@" not in email:
                continue
            # Any column NOT in known_keys becomes free-form context (notes, comments, etc.)
            extras = [f"{k}: {v}" for k, v in normalized.items() if k not in _known_keys and v]
            contacts.append({
                "name":    normalized.get("name") or f"{normalized.get('first name','')} {normalized.get('last name','')}".strip(),
                "email":   email,
                "company": normalized.get("company") or normalized.get("organization") or normalized.get("org") or "",
                "role":    normalized.get("role") or normalized.get("title") or normalized.get("job title") or "",
                "notes":   " | ".join(extras),
            })
    except Exception as e:
        print(f"[Outreach] CSV parse failed: {e}")
    return contacts


def _extract_from_xlsx(file_bytes: bytes) -> list[dict]:
    """Parse Excel via openpyxl."""
    if openpyxl is None:
        return []
    contacts = []
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            f.write(file_bytes)
            tmp_path = f.name
        wb = openpyxl.load_workbook(tmp_path, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h or "").lower().strip() for h in rows[0]]
        _known_keys = {"email", "e-mail", "email address", "name", "first name", "last name",
                       "company", "organization", "org", "role", "title", "job title"}
        for r in rows[1:]:
            row = dict(zip(headers, [str(v or "").strip() for v in r]))
            email = (row.get("email") or row.get("e-mail") or row.get("email address") or "")
            if not email or "@" not in email:
                continue
            extras = [f"{k}: {v}" for k, v in row.items() if k not in _known_keys and v]
            contacts.append({
                "name":    row.get("name") or f"{row.get('first name','')} {row.get('last name','')}".strip(),
                "email":   email,
                "company": row.get("company") or row.get("organization") or "",
                "role":    row.get("role") or row.get("title") or "",
                "notes":   " | ".join(extras),
            })
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    except Exception as e:
        print(f"[Outreach] XLSX parse failed: {e}")
    return contacts


# ── Draft generation ────────────────────────────────────────────────────────

def _generate_draft(ai: AIClient, contact: dict, context_note: str,
                    display_name: str, business_context: str,
                    writing_style: str) -> dict | None:
    """Generate subject + body for one contact. Returns None on failure.

    business_context already includes the user's Personal Profile, Business Profile,
    and Market Segments (merged by load_profile_context).

    Body comes back WITHOUT a signature — caller appends via
    profile.append_signature_to_body(body, get_user_signature(settings)).
    Centralising the append means every draft (this outreach worker, the
    bot's create_reply_draft, the dashboard's draft_generate) gets the
    same signature treatment without each path duplicating logic.
    """
    bc_block = f"User profile (personal + business + market):\n{business_context.strip()}\n\n" if business_context.strip() else ""
    style_block = f"Writing style to match:\n{writing_style.strip()}\n\n" if writing_style.strip() else ""
    ctx_block = f"How the user knows this contact:\n{context_note.strip()}\n\n" if context_note.strip() else ""
    notes_block = f"Specific notes from past interaction with this contact:\n{contact.get('notes', '')}\n\n" if (contact.get('notes') or '').strip() else ""

    prompt = f"""You are drafting a personal outreach email on behalf of {display_name}.

{bc_block}{style_block}{ctx_block}Contact info:
  Name: {contact.get('name', '')}
  Email: {contact.get('email', '')}
  Company: {contact.get('company', '')}
  Role: {contact.get('role', '')}

{notes_block}Write a personalized outreach email with these requirements:

1. STRUCTURE — 2-3 short paragraphs:
   • Opening: greeting on its own line, then 1-2 sentences referencing the meeting context (or how you know them).
   • Middle: 1-2 sentences connecting their company/role/notes to what the user offers. If "notes from past interaction" exist, weave them in specifically — that's the most personal hook.
   • Closing: 1 sentence with a clear next step (a call, a quick chat, a question).

2. FORMAT — return the body as HTML. Each paragraph wrapped in <p>...</p>. Do NOT use <div>, headers, lists, or styles.

3. TONE — warm but specific. Avoid generic phrases like "great to connect" without a follow-up specific. No marketing jargon.

4. LENGTH — keep total body 60-100 words.

5. DO NOT write a sign-off or signature — the user's real signature (extracted from their actual sent emails) is appended automatically. Anything you write at the end will look like a duplicate.

Return JSON only: {{"subject": "...", "body": "<p>...</p><p>...</p><p>...</p>"}}"""

    try:
        raw = ai.generate(prompt).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("subject") and data.get("body"):
                return {"subject": data["subject"], "body": data["body"]}
    except Exception as e:
        print(f"[Outreach] Draft gen failed for {contact.get('email')}: {e}")
    return None


# ── Main entry ─────────────────────────────────────────────────────────────

def run(graph: GraphClient, ai: AIClient, data_dir: Path, settings: dict,
        context_note: str = "", folder: str = "",
        tag: str = "", recent_hours: int = 0, progress=None) -> dict:
    """
    Generate Outlook drafts for a batch of contacts. Three modes:

      folder       — scan OneDrive folder for files (cards/csv/xlsx/pdf), extract contacts, draft.
      tag          — pull contacts from CRM that have this tag, draft.
      recent_hours — pull contacts from CRM added in the last N hours, draft.

    Defaults to folder mode if none specified. context_note is injected into each draft prompt.
    """
    def log(msg: str):
        print(f"[Outreach] {msg}")
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    display_name     = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir) if data_dir else ""
    writing_style    = settings.get("writing_style_note", "")
    # Resolved once for the whole run — same signature appended to every
    # generated draft. Empty string for users who haven't completed
    # signature extraction yet; append helper passes the body through
    # unchanged in that case.
    user_signature   = get_user_signature(settings)

    drafts_created = []
    contacts_skipped = []
    files_processed = []
    errors = []

    # ── Mode 1: CRM by tag or recency ─────────────────────────────────
    if tag or recent_hours:
        from src.modules.crm import find_contacts_by_tag, find_contacts_added_since
        crm_contacts = (find_contacts_by_tag(data_dir, tag) if tag
                        else find_contacts_added_since(data_dir, recent_hours))
        log(f"CRM lookup ({'tag='+tag if tag else 'recent_hours='+str(recent_hours)}) → {len(crm_contacts)} contacts")

        for contact in crm_contacts:
            email = (contact.get("email") or "").strip()
            if not email or "@" not in email:
                contacts_skipped.append({"reason": "no_email", "contact": contact})
                continue
            draft = _generate_draft(ai, contact, context_note,
                                    display_name, business_context, writing_style)
            if not draft:
                contacts_skipped.append({"reason": "draft_gen_failed", "contact": contact})
                continue
            final_body = append_signature_to_body(draft["body"], user_signature)
            try:
                gr = graph.create_draft(subject=draft["subject"], body=final_body, to=email)
                drafts_created.append({
                    "to": email, "name": contact.get("name", ""),
                    "company": contact.get("company", ""),
                    "subject": draft["subject"],
                    "web_link": gr.get("webLink", ""),
                    "source_file": f"CRM:{tag or 'recent'}",
                })
                log(f"  ✅ Draft created: {email}")
            except Exception as e:
                errors.append({"contact": email, "error": str(e)})

        result = {
            "status": "fresh",
            "last_run": datetime.now(timezone.utc).isoformat(),
            "mode": "crm",
            "source": tag or f"recent_{recent_hours}h",
            "context_note": context_note,
            "drafts_created": drafts_created,
            "files_processed": [],
            "contacts_skipped": contacts_skipped,
            "errors": errors,
            "summary": {
                "drafts": len(drafts_created),
                "files": 0,
                "skipped": len(contacts_skipped),
                "errors": len(errors),
            },
        }
        _save_result(data_dir, result)
        log(f"Done — {len(drafts_created)} drafts, {len(contacts_skipped)} skipped")
        return result

    # ── Mode 2: OneDrive folder (original) ─────────────────────────────
    folder = (folder or settings.get("outreach_folder", "")).strip().strip("/")
    if not folder:
        return {
            "status": "not_run",
            "error": "No folder/tag/recent_hours specified.",
            "drafts_created": 0,
            "files_processed": 0,
            "contacts_skipped": 0,
        }

    log(f"Scanning OneDrive folder: {folder}")
    try:
        items = graph.list_drive_folder(folder)
    except Exception as e:
        return {
            "status": "not_run",
            "error": f"Folder not found or inaccessible: {e}",
            "drafts_created": 0,
            "files_processed": 0,
            "contacts_skipped": 0,
        }

    state = _load_state(data_dir)
    processed = state.get("processed_files", {})

    for item in items:
        if item.get("folder"):
            continue  # skip subfolders
        name = item.get("name", "")
        item_id = item.get("id", "")
        ext = Path(name).suffix.lower()

        if item_id in processed:
            continue  # already handled

        log(f"  Processing: {name}")

        try:
            file_bytes = graph.download_drive_item(item_id)
        except Exception as e:
            errors.append({"file": name, "error": f"download failed: {e}"})
            continue

        # Extract contacts based on file type
        if ext in _IMAGE_EXTS:
            contacts = _extract_from_image(ai, file_bytes, ext)
        elif ext in _PDF_EXTS:
            contacts = _extract_from_pdf(ai, file_bytes)
        elif ext in _CSV_EXTS:
            contacts = _extract_from_csv(file_bytes)
        elif ext in _XLSX_EXTS:
            contacts = _extract_from_xlsx(file_bytes)
        else:
            continue  # unknown type, skip silently

        files_processed.append({"file": name, "type": ext, "contacts_found": len(contacts)})

        for contact in contacts:
            email = (contact.get("email") or "").strip()
            if not email or "@" not in email:
                contacts_skipped.append({"reason": "no_email", "file": name, "contact": contact})
                continue

            draft = _generate_draft(
                ai, contact, context_note,
                display_name, business_context, writing_style,
            )
            if not draft:
                contacts_skipped.append({"reason": "draft_gen_failed", "file": name, "contact": contact})
                continue

            final_body = append_signature_to_body(draft["body"], user_signature)
            try:
                result = graph.create_draft(
                    subject=draft["subject"],
                    body=final_body,
                    to=email,
                )
                drafts_created.append({
                    "to": email,
                    "name": contact.get("name", ""),
                    "company": contact.get("company", ""),
                    "subject": draft["subject"],
                    "web_link": result.get("webLink", ""),
                    "source_file": name,
                })
                log(f"    ✅ Draft created: {email}")
            except Exception as e:
                errors.append({"contact": email, "error": f"create_draft failed: {e}"})

        processed[item_id] = {
            "filename": name,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    state["processed_files"] = processed
    state.setdefault("history", []).append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "folder": folder,
        "context_note": context_note,
        "drafts_created": len(drafts_created),
        "files_processed": len(files_processed),
    })
    state["history"] = state["history"][-50:]  # keep last 50 runs
    _save_state(data_dir, state)

    result = {
        "status": "fresh",
        "last_run": datetime.now(timezone.utc).isoformat(),
        "folder": folder,
        "context_note": context_note,
        "drafts_created": drafts_created,
        "files_processed": files_processed,
        "contacts_skipped": contacts_skipped,
        "errors": errors,
        "summary": {
            "drafts": len(drafts_created),
            "files": len(files_processed),
            "skipped": len(contacts_skipped),
            "errors": len(errors),
        },
    }
    _save_result(data_dir, result)
    log(f"Done — {len(drafts_created)} drafts, {len(files_processed)} files, {len(contacts_skipped)} skipped")
    return result
