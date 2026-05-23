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
from src.modules.profile import load_profile_context


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
        for row in reader:
            normalized = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
            email = (normalized.get("email") or normalized.get("e-mail")
                     or normalized.get("email address") or "")
            if not email or "@" not in email:
                continue
            contacts.append({
                "name":    normalized.get("name") or f"{normalized.get('first name','')} {normalized.get('last name','')}".strip(),
                "email":   email,
                "company": normalized.get("company") or normalized.get("organization") or normalized.get("org") or "",
                "role":    normalized.get("role") or normalized.get("title") or normalized.get("job title") or "",
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
        for r in rows[1:]:
            row = dict(zip(headers, [str(v or "").strip() for v in r]))
            email = (row.get("email") or row.get("e-mail") or row.get("email address") or "")
            if not email or "@" not in email:
                continue
            contacts.append({
                "name":    row.get("name") or f"{row.get('first name','')} {row.get('last name','')}".strip(),
                "email":   email,
                "company": row.get("company") or row.get("organization") or "",
                "role":    row.get("role") or row.get("title") or "",
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
                    writing_style: str, signoff: str) -> dict | None:
    """Generate subject + body for one contact. Returns None on failure."""
    bc_block = f"Business context:\n{business_context.strip()}\n\n" if business_context.strip() else ""
    style_block = f"Writing style to match:\n{writing_style.strip()}\n\n" if writing_style.strip() else ""
    ctx_block = f"How the user knows this contact:\n{context_note.strip()}\n\n" if context_note.strip() else ""
    signoff_block = f"\nClose with this sign-off:\n{signoff}\n" if signoff.strip() else ""

    prompt = f"""You are drafting a personal outreach email on behalf of {display_name}.

{bc_block}{style_block}{ctx_block}Contact info:
  Name: {contact.get('name', '')}
  Email: {contact.get('email', '')}
  Company: {contact.get('company', '')}
  Role: {contact.get('role', '')}

Write a brief, warm outreach email (3-5 short sentences). Reference the meeting context naturally if provided.
Mention something specific about their company or role to show this is personalized, not a mass email.
{signoff_block}
Return JSON only: {{"subject": "...", "body": "..."}}"""

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
        context_note: str = "", folder: str = "", progress=None) -> dict:
    """
    Scan OneDrive folder, extract contacts, generate Outlook drafts.

    folder: OneDrive path relative to drive root (e.g. "Conferences/TechConf").
            If empty, uses settings["outreach_folder"].
    context_note: brief context to inject into each draft.
    """
    def log(msg: str):
        print(f"[Outreach] {msg}")
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    folder = (folder or settings.get("outreach_folder", "")).strip().strip("/")
    if not folder:
        return {
            "status": "not_run",
            "error": "No folder specified — set outreach_folder in settings or pass folder argument.",
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

    display_name     = settings.get("display_name", "the executive")
    business_context = load_profile_context(data_dir) if data_dir else ""
    writing_style    = settings.get("writing_style_note", "")
    signoff          = settings.get("outreach_default_signoff", "")

    drafts_created = []
    contacts_skipped = []
    files_processed = []
    errors = []

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
                display_name, business_context, writing_style, signoff,
            )
            if not draft:
                contacts_skipped.append({"reason": "draft_gen_failed", "file": name, "contact": contact})
                continue

            try:
                result = graph.create_draft(
                    subject=draft["subject"],
                    body=draft["body"],
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
