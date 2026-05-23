"""
M03 — Meeting Intelligence

Two input modes (controlled by use_mock flag):
  Production : OneDrive .mp4 files → transcription fallback chain → analysis
  Mock       : data_dir/wiki/transcripts/mock/*.txt → analysis (skips transcription)

Transcription fallback chain (OneDrive):
  1. Teams .vtt file (same folder as MP4) — speaker-labelled, free, fastest
  2. ffmpeg audio extraction (mp3) → Gemini transcribe_audio
  3. Full MP4 → Gemini transcribe_video (last resort)

Project detection:
  Match attendee emails against projects.json participants field.
  No match → project_id: null (no auto-registration).

Post-processing per meeting:
  - CRM alignment: update last_contact for known attendees
  - Projects alignment: update last_activity for matched project
  - Follow-up draft saved to Outlook Drafts
  - Action items pushed to MS To-Do
  - Transcript + analysis backed up to OneDrive
"""
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.graph import GraphClient
from src.ai import AIClient
from src.modules.wiki import (
    add_meeting,
    is_processed,
    save_transcript,
    save_unprocessed,
)
from src.modules.crm import load_crm, save_crm
from src.modules.projects import load_projects, save_projects
from src.modules.wiki import get_recent_meetings


# ── Skill loading ─────────────────────────────────────────

_SKILL_FILE = Path(__file__).parent.parent / "skills" / "m03_meeting" / "skill.md"


def _load_skill(data_dir: Path) -> tuple[str, str]:
    """Return (skill_text, user_instruction)."""
    skill_text = _SKILL_FILE.read_text() if _SKILL_FILE.exists() else ""
    instruction_path = Path(data_dir) / "instructions" / "m03_meeting.md"
    user_instruction = instruction_path.read_text().strip() if instruction_path.exists() else ""
    return skill_text, user_instruction


# ── Noise domain detection ────────────────────────────────

_DEFAULT_NOISE_DOMAINS = frozenset([
    "microsoft.com", "teams.microsoft.com", "communication.microsoft.com",
    "outlook.com", "hotmail.com", "gmail.com", "googlemail.com",
    "zoom.us", "webex.com",
])


def _build_noise_domains(settings: dict) -> frozenset:
    """Combine default noise domains with owner domains from settings."""
    owner_domains = {d.lower() for d in settings.get("owner_domains", [])}
    return _DEFAULT_NOISE_DOMAINS | owner_domains


def _is_noise_domain(domain: str, noise_domains: frozenset) -> bool:
    return domain.lower() in noise_domains


# ── Attendee / header parsing ─────────────────────────────

def _parse_attendees_from_header(text: str) -> list[str]:
    return re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", text[:600])


def _parse_date_from_header(text: str) -> str:
    m = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", text[:400])
    return m.group(1) if m else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_title_from_header(text: str, filename: str) -> str:
    m = re.search(r"Title:\s*(.+)", text[:400])
    if m:
        return m.group(1).strip()
    name = re.sub(r"\d{8}[_\s]\d{6}", "", filename)
    name = re.sub(r"-Meeting Recording", "", name, flags=re.IGNORECASE)
    name = name.replace("_", " ").replace("-", " ").strip()
    name = re.sub(r"\.txt$|\.md$|\.mp4$", "", name)
    return name.strip()


def _client_domains_from_emails(emails: list[str], noise_domains: frozenset) -> list[str]:
    seen = set()
    result = []
    for email in emails:
        domain = email.lower().split("@")[-1] if "@" in email else ""
        if domain and not _is_noise_domain(domain, noise_domains) and domain not in seen:
            seen.add(domain)
            result.append(domain)
    return result


# ── Attendee resolution (Call Records + Calendar) ─────────

def _get_app_token(graph: GraphClient) -> str:
    """Get app-only token for Call Records API using client_credentials flow."""
    import base64
    import requests as _req
    client_id     = os.environ.get("PROD_CLIENT_ID", "")
    client_secret = os.environ.get("PROD_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return ""
    try:
        auth_header = graph.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "")
        parts = token.split(".")
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        claims = json.loads(base64.b64decode(padded))
        tenant_id = claims.get("tid", "")
    except Exception:
        return ""
    try:
        r = _req.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={"grant_type": "client_credentials", "client_id": client_id,
                  "client_secret": client_secret, "scope": "https://graph.microsoft.com/.default"},
            timeout=10,
        )
        return r.json().get("access_token", "") if r.ok else ""
    except Exception:
        return ""


def _attendees_from_call_records(rec: dict, app_token: str) -> list[dict]:
    import requests as _req
    if not app_token:
        return []
    headers = {"Authorization": f"Bearer {app_token}"}
    name = rec.get("name", "")
    ts_match = re.search(r"(\d{8})[_\s](\d{6})", name)
    if not ts_match:
        return []
    try:
        rec_dt = datetime.strptime(
            ts_match.group(1) + ts_match.group(2), "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return []
    try:
        call_records = _req.get(
            "https://graph.microsoft.com/v1.0/communications/callRecords",
            headers=headers, timeout=15
        ).json().get("value", [])
    except Exception:
        return []

    def _delta(cr):
        try:
            return abs((datetime.fromisoformat(
                cr["startDateTime"].replace("Z", "+00:00")
            ) - rec_dt).total_seconds())
        except Exception:
            return 9999999

    candidates = [cr for cr in call_records if _delta(cr) < 5400]
    if not candidates:
        return []
    best = min(candidates, key=_delta)
    try:
        participants = _req.get(
            f"https://graph.microsoft.com/v1.0/communications/callRecords/{best['id']}/participants_v2",
            headers=headers, timeout=10
        ).json().get("value", [])
    except Exception:
        return []

    attendees = []
    for p in participants:
        identity = p.get("identity") or {}
        user = identity.get("user") or {}
        uid = user.get("id", "")
        if not uid or "-" not in uid:
            continue
        try:
            u = _req.get(
                f"https://graph.microsoft.com/v1.0/users/{uid}",
                headers=headers,
                params={"$select": "displayName,mail,userPrincipalName"},
                timeout=10,
            )
            if u.ok:
                info = u.json()
                email = info.get("mail") or info.get("userPrincipalName", "")
                name  = info.get("displayName", "")
                if email and "@" in email:
                    attendees.append({"name": name, "email": email})
        except Exception:
            continue
    return attendees


def _attendees_from_calendar(rec: dict, graph: GraphClient) -> list[dict]:
    name = rec.get("name", "")
    ts_match = re.search(r"(\d{8})[_\s](\d{6})", name)
    meeting_dt = None
    if ts_match:
        try:
            meeting_dt = datetime.strptime(
                ts_match.group(1) + ts_match.group(2), "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if not meeting_dt:
        created = rec.get("createdDateTime") or (rec.get("remoteItem") or {}).get("createdDateTime")
        if created:
            try:
                meeting_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                pass
    if not meeting_dt:
        return []

    window_start = (meeting_dt - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window_end   = (meeting_dt + timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        events = graph.get_calendar_view(window_start, window_end, top=10)
    except Exception:
        return []
    if not events:
        return []

    def _dt(ev):
        try:
            return abs((datetime.fromisoformat(
                ev["start"]["dateTime"].replace("Z", "+00:00")
            ) - meeting_dt).total_seconds())
        except Exception:
            return 9999999

    best = min(events, key=_dt)
    attendees = []
    for att in best.get("attendees", []):
        addr = att.get("emailAddress", {}).get("address", "")
        aname = att.get("emailAddress", {}).get("name", "")
        if addr and "@" in addr:
            attendees.append({"name": aname, "email": addr})
    return attendees


# ── Project detection ─────────────────────────────────────

def _detect_project(attendee_emails: list[str], data_dir: Path) -> str | None:
    """
    Match attendee emails against projects.json participants.
    Returns project_id if found, None otherwise. No auto-registration.
    """
    try:
        projects = load_projects(data_dir).get("projects", {})
    except Exception:
        return None
    for pid, proj in projects.items():
        if proj.get("ignore"):
            continue
        proj_participants = [p.lower() for p in proj.get("participants", [])]
        for email in attendee_emails:
            if email.lower() in proj_participants:
                return pid
    return None


# ── CRM + Projects alignment ──────────────────────────────

def _align_crm(attendee_emails: list[str], meeting_date: str, data_dir: Path) -> None:
    """Update last_contact for attendees already in CRM."""
    try:
        crm = load_crm(data_dir)
        changed = False
        for email in attendee_emails:
            contact = crm.get("contacts", {}).get(email.lower())
            if contact and meeting_date > contact.get("last_contact", ""):
                contact["last_contact"] = meeting_date
                changed = True
        if changed:
            save_crm(data_dir, crm)
    except Exception as e:
        print(f"    [M03] CRM alignment failed (non-critical): {e}")


def _align_projects(
    project_id: str | None, meeting_date: str, meeting_id: str, data_dir: Path
) -> None:
    """Update last_activity and meeting_ids on the matched project."""
    if not project_id:
        return
    try:
        projects_data = load_projects(data_dir)
        proj = projects_data.get("projects", {}).get(project_id)
        if not proj:
            return
        changed = False
        if meeting_date > proj.get("last_activity", ""):
            proj["last_activity"] = meeting_date
            changed = True
        meeting_ids = proj.setdefault("meeting_ids", [])
        if meeting_id not in meeting_ids:
            meeting_ids.append(meeting_id)
            changed = True
        if changed:
            save_projects(data_dir, projects_data)
    except Exception as e:
        print(f"    [M03] Projects alignment failed (non-critical): {e}")


# ── VTT parsing ───────────────────────────────────────────

def _parse_vtt(vtt_text: str) -> str:
    lines, current_speaker, current_text = [], "", []
    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or "-->" in line:
            if current_text:
                lines.append(
                    f"{current_speaker}: {' '.join(current_text)}"
                    if current_speaker else ' '.join(current_text)
                )
                current_text = []
            continue
        m = re.match(r"<v ([^>]+)>(.*)", line)
        if m:
            if current_text and current_speaker != m.group(1):
                lines.append(f"{current_speaker}: {' '.join(current_text)}")
                current_text = []
            current_speaker = m.group(1)
            current_text.append(re.sub(r"<[^>]+>", "", m.group(2)).strip())
        else:
            cleaned = re.sub(r"<[^>]+>", "", line).strip()
            if cleaned:
                current_text.append(cleaned)
    if current_text:
        lines.append(
            f"{current_speaker}: {' '.join(current_text)}"
            if current_speaker else ' '.join(current_text)
        )
    return "\n".join(lines)


def _get_vtt_for_recording(rec: dict, graph: GraphClient) -> str | None:
    remote = rec.get("remoteItem") or {}
    drive_id  = remote.get("parentReference", {}).get("driveId")
    parent_id = (
        remote.get("parentReference", {}).get("id") or
        rec.get("parentReference", {}).get("id")
    )
    if not parent_id:
        return None
    try:
        if drive_id:
            children = graph.get(f"/drives/{drive_id}/items/{parent_id}/children", {"$top": 50}).get("value", [])
        else:
            children = graph.get(f"/me/drive/items/{parent_id}/children", {"$top": 50}).get("value", [])
        base = rec["name"].replace(".mp4", "")
        for f in children:
            name = f.get("name", "")
            if name.endswith(".vtt") and base[:30] in name:
                if drive_id:
                    vtt_bytes = graph.download(f"/drives/{drive_id}/items/{f['id']}/content")
                else:
                    vtt_bytes = graph.download_drive_item(f["id"])
                return _parse_vtt(vtt_bytes.decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"    [VTT] Could not fetch: {e}")
    return None


# ── Audio extraction + transcription ─────────────────────

def _extract_audio_and_transcribe(
    video_bytes: bytes, filename: str, ai: AIClient, progress=None
) -> str | None:
    def _log(msg):
        print(msg)
        if progress:
            progress(msg)

    mp4_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    mp3_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        mp4_tmp.write(video_bytes)
        mp4_tmp.close()
        mp3_tmp.close()
        _log(f"  [ffmpeg] {len(video_bytes)/1024/1024:.1f} MB — extracting audio...")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", mp4_tmp.name, "-vn", "-acodec", "libmp3lame", "-q:a", "4", mp3_tmp.name],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0:
            _log(f"  [ffmpeg] Error: {result.stderr.decode()[:300]}")
            return None
        audio_bytes = open(mp3_tmp.name, "rb").read()
        size_mb = len(audio_bytes) / 1024 / 1024
        _log(f"  [ffmpeg] Audio: {size_mb:.1f} MB — transcribing...")

        if size_mb <= 15:
            text = ai.transcribe_audio(audio_bytes, filename=filename.replace(".mp4", ".mp3"))
            return text if text and text.strip() else None

        # Large file: chunk into 10-minute segments
        _log(f"  [ffmpeg] Large audio — chunking...")
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", mp3_tmp.name],
            capture_output=True, text=True, timeout=30,
        )
        try:
            duration = float(json.loads(probe.stdout)["streams"][0]["duration"])
        except Exception:
            duration = size_mb * 60

        chunks = []
        start, idx = 0, 0
        while start < duration:
            chunk_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            chunk_tmp.close()
            subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_tmp.name, "-ss", str(int(start)),
                 "-t", "600", "-acodec", "copy", chunk_tmp.name],
                capture_output=True, timeout=120,
            )
            chunk_bytes = open(chunk_tmp.name, "rb").read()
            os.unlink(chunk_tmp.name)
            if len(chunk_bytes) > 5000:
                mins = int(start // 60)
                _log(f"  [ffmpeg] Chunk {idx+1} (~{mins}min)...")
                text = ai.transcribe_audio(chunk_bytes, filename=f"chunk_{idx}.mp3")
                if text and text.strip():
                    chunks.append(f"[~{mins}min]\n{text.strip()}")
            start += 600
            idx   += 1

        return "\n\n".join(chunks) if chunks else None

    except Exception as e:
        _log(f"  [ffmpeg] Failed: {e}")
        return None
    finally:
        os.unlink(mp4_tmp.name)
        try:
            os.unlink(mp3_tmp.name)
        except Exception:
            pass


def _transcribe_video_fallback(video_bytes: bytes, filename: str, ai: AIClient) -> str | None:
    """Last-resort: send full MP4 to Gemini. Retries with partial prompt on token error."""
    try:
        return ai.transcribe_video(video_bytes, filename=filename)
    except Exception as e:
        err = str(e)
        if "token" in err.lower() or "400" in err:
            print(f"    Video too long — retrying with first 20 min instruction...")
            try:
                import time
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                    f.write(video_bytes)
                    tmp_path = f.name
                try:
                    from google.genai import types
                    uploaded = ai.client.files.upload(file=tmp_path)
                    while uploaded.state.name == "PROCESSING":
                        time.sleep(5)
                        uploaded = ai.client.files.get(name=uploaded.name)
                    response = ai.client.models.generate_content(
                        model=ai.model,
                        contents=[
                            types.Part.from_uri(file_uri=uploaded.uri, mime_type="video/mp4"),
                            "Transcribe only the FIRST 20 MINUTES of speech. Include speaker labels and timestamps.",
                        ]
                    )
                    return (response.text or "") + \
                        "\n\n[NOTE: Transcript truncated — first 20 minutes only.]"
                finally:
                    os.unlink(tmp_path)
            except Exception as e2:
                print(f"    Partial transcription also failed: {e2}")
                return None
        raise


# ── AI analysis ───────────────────────────────────────────

def _analyse(
    transcript: str,
    ai: AIClient,
    skill_text: str = "",
    user_instruction: str = "",
    display_name: str = "",
    today_str: str = "",
) -> dict:
    clean = re.sub(r"\[~\d+min\]\n?", "", transcript).strip()
    if len(clean) > 60000:
        clean = clean[:60000]

    word_count = len(clean.split())
    if word_count > 3000:
        summary_instruction = "3-5 sentences per major topic discussed, covering all key points and decisions"
    else:
        summary_instruction = "2-4 sentences covering what was discussed and decided"

    if skill_text:
        prompt = (
            skill_text
            .replace("{display_name}", display_name or "the executive")
            .replace("{date}", today_str or datetime.now().strftime("%Y-%m-%d"))
            .replace("{summary_instruction}", summary_instruction)
            .replace("{user_instruction}", user_instruction or "(none)")
        )
        prompt += f"\n\nTranscript:\n{clean}"
    else:
        skill_block = f"\nMEETING INTELLIGENCE INSTRUCTIONS:\n{user_instruction}\n" if user_instruction else ""
        prompt = f"""Analyse this meeting transcript and return a JSON object with exactly these fields:
- "summary": string, {summary_instruction}
- "action_items": array of objects: {{"owner": person name, "action": what to do, "due_date": YYYY-MM-DD or null}}
- "decisions": array of strings, each a concrete decision made
- "key_topics": array of 3-8 topic strings
- "attendees": array of full name strings (no emails)

The transcript may be in any language — respond in English regardless.
Be thorough — extract EVERY action item and decision, even implicit ones.
{skill_block}
Transcript:
{clean}"""

    raw = ai.extract_json(prompt)
    try:
        return json.loads(raw)
    except Exception:
        return {"summary": "", "action_items": [], "decisions": [], "key_topics": [], "attendees": []}


# ── Draft recipient filtering ─────────────────────────────

def _filter_draft_recipients(
    attendees: list[dict],
    user_instruction: str,
    own_email: str,
    ai: AIClient,
) -> list[dict]:
    """Filter attendee list using user_instruction before sending follow-up drafts."""
    if not user_instruction or not attendees:
        return attendees
    prompt = f"""Given these meeting attendees and the organizer's instruction, return which ones should receive a follow-up email.

Organizer email: {own_email}
Attendees: {json.dumps([a["email"] for a in attendees])}
Instruction: {user_instruction}

Return only a JSON array of email addresses to include. Example: ["a@x.com", "b@y.com"]"""
    try:
        raw = ai.extract_json(prompt)
        keep = set(json.loads(raw))
        return [a for a in attendees if a["email"] in keep]
    except Exception:
        return attendees  # parsing failed → send to all


# ── Follow-up draft + To-Do ───────────────────────────────

def _generate_followup_draft(record: dict) -> str:
    title   = record.get("title", "our meeting")
    date    = record.get("date", "")
    summary = record.get("summary", "")
    actions = record.get("action_items", [])

    lines = ["Hi,", "", f"Here is the meeting summary from {date} — {title}:", "", summary]
    if actions:
        lines += ["", "Action Items:"]
        for a in actions:
            if isinstance(a, dict):
                owner = a.get("owner", "")
                task  = a.get("action") or a.get("task", "")
                due   = f" (by {a['due_date']})" if a.get("due_date") else ""
                lines.append(f"• {owner + ': ' if owner else ''}{task}{due}")
            else:
                lines.append(f"• {a}")
    lines += ["", "Best regards"]
    return "\n".join(lines)


def _push_action_items_to_todo(record: dict, graph: GraphClient, own_name_hints: list) -> int:
    own_hints = [h.lower() for h in own_name_hints]
    pushed = 0
    for item in record.get("action_items", []):
        owner  = (item.get("owner") or "").lower()
        action = (item.get("action") or "").strip()
        if not action:
            continue
        if not any(h in owner for h in own_hints):
            continue
        title = f"[{record.get('title', 'Meeting')}] {action}"[:255]
        note  = f"From meeting: {record.get('title', '')} on {record.get('date', '')}"
        try:
            graph.create_todo_task(title=title, note=note, due_date=item.get("due_date"))
            pushed += 1
        except Exception:
            pass
    return pushed


# ── OneDrive backup ───────────────────────────────────────

def _backup_to_onedrive(
    record: dict, transcript_text: str, attendee_emails: list,
    graph: GraphClient, progress=None
) -> None:
    def _log(msg):
        if progress:
            progress(msg)
    try:
        date_str   = (record.get("date") or datetime.now().strftime("%Y-%m-%d"))[:10]
        title      = record.get("title", record.get("meeting_id", "meeting"))
        safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:50]
        base       = f"{date_str}_{safe_title}"

        graph.upload_to_onedrive(
            f"CEO Platform/Meetings/{base}_transcript.txt",
            transcript_text.encode("utf-8"),
            "text/plain",
        )
        analysis = {
            **{k: v for k, v in record.items() if k != "followup_draft"},
            "attendee_emails": attendee_emails,
            "processed_at":    datetime.now().isoformat(),
        }
        graph.upload_to_onedrive(
            f"CEO Platform/Meetings/{base}_analysis.json",
            json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
        _log(f"  → OneDrive backup: CEO Platform/Meetings/{base}_*")
    except Exception as e:
        _log(f"  → OneDrive backup failed (non-critical): {e}")


# ── Core processing ───────────────────────────────────────

def _process_transcript(
    meeting_id: str,
    title: str,
    transcript_text: str,
    ai: AIClient,
    source: str = "mock",
    skill_text: str = "",
    user_instruction: str = "",
    display_name: str = "",
    today_str: str = "",
) -> dict:
    attendee_emails = _parse_attendees_from_header(transcript_text)
    date_str = _parse_date_from_header(transcript_text)
    analysis = _analyse(
        transcript_text, ai,
        skill_text=skill_text,
        user_instruction=user_instruction,
        display_name=display_name,
        today_str=today_str,
    )

    return {
        "meeting_id":      meeting_id,
        "title":           title,
        "date":            date_str,
        "source":          source,
        "attendees":       analysis.get("attendees", []),
        "summary":         analysis.get("summary", ""),
        "action_items":    analysis.get("action_items", []),
        "decisions":       analysis.get("decisions", []),
        "key_topics":      analysis.get("key_topics", []),
        "transcript_file": f"transcripts/{meeting_id}.txt",
        "processed_at":    datetime.now(timezone.utc).isoformat(),
        "_attendee_emails": attendee_emails,  # popped before saving
    }


# ── Main entry point ──────────────────────────────────────

def run(
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
    force: bool = False,
    use_mock: bool = False,
    progress=None,
) -> dict:
    """
    Process all unprocessed meeting recordings.
    Writes to Meeting DB (wiki/), aligns CRM + Projects.
    Returns section-compatible result dict.
    """
    def _p(msg: str):
        print(msg)
        if progress:
            progress(msg)

    data_dir = Path(data_dir)
    wiki_dir = data_dir / "wiki"
    _s = settings or {}
    noise_domains    = _build_noise_domains(_s)
    display_name     = _s.get("display_name", "")
    own_email        = _s.get("owner_email", "")
    today_str        = datetime.now().strftime("%Y-%m-%d")
    skill_text, user_instruction = _load_skill(data_dir)

    own_hints = []
    if display_name:
        own_hints.append(display_name.split()[0].lower())
    if own_email and "@" in own_email:
        own_hints.append(own_email.split("@")[0].lower())
    if not own_hints:
        own_hints = ["me"]

    results = []

    # ── Path 1: Mock transcript files ─────────────────────
    if use_mock:
        mock_dir = wiki_dir / "transcripts" / "mock"
        mock_dir.mkdir(parents=True, exist_ok=True)
        for txt_file in sorted(mock_dir.glob("*.txt")):
            meeting_id = txt_file.stem
            if is_processed(wiki_dir, meeting_id) and not force:
                results.append({"meeting_id": meeting_id, "status": "already_processed", "source": "mock"})
                continue

            _p(f"  [mock] {txt_file.name}")
            transcript_text = txt_file.read_text(encoding="utf-8")
            title = _parse_title_from_header(transcript_text, txt_file.name)

            record = _process_transcript(
                meeting_id, title, transcript_text, ai, source="mock",
                skill_text=skill_text, user_instruction=user_instruction,
                display_name=display_name, today_str=today_str,
            )
            attendee_emails = record.pop("_attendee_emails", [])
            external = [{"name": "", "email": e} for e in attendee_emails if e.lower() != own_email.lower()]
            external = _filter_draft_recipients(external, user_instruction, own_email, ai)

            project_id = _detect_project(attendee_emails, data_dir)
            record["project_id"]       = project_id
            record["attendee_emails"]  = attendee_emails

            save_transcript(wiki_dir, meeting_id, transcript_text)
            added = add_meeting(wiki_dir, record)
            _p(f"    → project: {project_id or 'unmatched'} | wiki: {'added' if added else 'duplicate'}")

            _align_crm(attendee_emails, record["date"], data_dir)
            _align_projects(project_id, record["date"], meeting_id, data_dir)

            draft_body = _generate_followup_draft(record)
            record["followup_draft"] = draft_body
            saved, draft_link = 0, None
            if draft_body and external:
                subj = f"Follow-up: {record.get('title', 'our meeting')}"
                html = draft_body.replace("\n", "<br>")
                for att in external:
                    try:
                        resp = graph.create_draft(subj, html, att["email"])
                        saved += 1
                        if not draft_link:
                            draft_link = resp.get("webLink")
                    except Exception as _e:
                        _p(f"    → Draft failed for {att['email']}: {_e}")
            record["followup_draft_saved"] = saved > 0
            record["followup_draft_link"]  = draft_link
            record["todos_pushed"] = _push_action_items_to_todo(record, graph, own_hints)

            _backup_to_onedrive(record, transcript_text, attendee_emails, graph, progress=_p)
            results.append({**record, "status": "processed"})

    # ── Path 2: OneDrive recordings ────────────────────────
    else:
        try:
            _p("Scanning OneDrive Recordings/ folder...")
            own_mp4 = [
                f for f in graph.list_drive_folder("Recordings")
                if f.get("name", "").endswith(".mp4")
            ]
            mp4_files = own_mp4
            _p(f"Found {len(own_mp4)} recording(s) in Recordings/")
        except Exception as e:
            _p(f"[OneDrive] Could not fetch recordings: {e}")
            mp4_files = []

        app_token = _get_app_token(graph)

        for rec in mp4_files:
            item_id    = rec["id"]
            name       = rec["name"]
            meeting_id = f"ondrive_{item_id[:16]}"

            if is_processed(wiki_dir, meeting_id) and not force:
                results.append({"meeting_id": meeting_id, "title": name, "status": "already_processed", "source": "ondrive"})
                continue

            _p(f"Processing: {name}")
            title = _parse_title_from_header("", name)

            transcript_text = None
            try:
                _p("  Checking for .vtt transcript...")
                transcript_text = _get_vtt_for_recording(rec, graph)
                if transcript_text:
                    _p(f"  [VTT] Found ({len(transcript_text)} chars)")
                else:
                    _p("  No .vtt — downloading MP4...")
                    if rec.get("remoteItem"):
                        video_bytes = graph.download_shared_item(rec)
                    else:
                        video_bytes = graph.download_drive_item(item_id)
                    size_mb = len(video_bytes) / 1024 / 1024
                    _p(f"  Downloaded {size_mb:.1f} MB — extracting audio...")
                    transcript_text = _extract_audio_and_transcribe(video_bytes, name, ai, progress=_p)
                    if transcript_text:
                        _p(f"  Audio transcription done ({len(transcript_text)} chars)")
                    else:
                        _p("  Audio failed — sending full video to Gemini...")
                        transcript_text = _transcribe_video_fallback(video_bytes, name, ai)
                        if transcript_text:
                            _p(f"  Video transcription done ({len(transcript_text)} chars)")
            except Exception as e:
                _p(f"  ERROR on {name}: {e}")
                save_unprocessed(wiki_dir, {"meeting_id": meeting_id, "title": title, "status": "error", "error": str(e)})
                results.append({"meeting_id": meeting_id, "title": title, "status": "error", "source": "ondrive"})
                continue  # don't mark processed — allow retry

            if transcript_text is None:
                _p(f"  {name} → could not transcribe (stored for manual review)")
                save_unprocessed(wiki_dir, {"meeting_id": meeting_id, "title": title, "status": "too_long"})
                # Mark as processed to avoid infinite retry on permanently-too-long files
                from src.modules.wiki import load_index, save_index
                idx = load_index(wiki_dir)
                idx["meetings"][meeting_id] = {"title": title, "date": "", "project_id": None, "status": "too_long"}
                save_index(wiki_dir, idx)
                results.append({"meeting_id": meeting_id, "title": title, "status": "too_long", "source": "ondrive"})
                continue

            _p("  Analysing transcript...")
            record = _process_transcript(
                meeting_id, title, transcript_text, ai, source="ondrive",
                skill_text=skill_text, user_instruction=user_instruction,
                display_name=display_name, today_str=today_str,
            )
            raw_emails     = record.pop("_attendee_emails", [])
            attendees_info = [{"name": "", "email": e} for e in raw_emails]

            if not attendees_info:
                attendees_info = _attendees_from_call_records(rec, app_token)
                if attendees_info:
                    _p(f"  [CallRecords] {len(attendees_info)} attendee(s)")
            if not attendees_info:
                attendees_info = _attendees_from_calendar(rec, graph)
                if attendees_info:
                    _p(f"  [Calendar] {len(attendees_info)} attendee(s)")

            external_attendees = [a for a in attendees_info if a["email"].lower() != own_email.lower()]
            external_attendees = _filter_draft_recipients(external_attendees, user_instruction, own_email, ai)
            attendee_emails    = [a["email"] for a in external_attendees]

            project_id = _detect_project(attendee_emails, data_dir)
            record["project_id"]      = project_id
            record["attendee_emails"] = attendee_emails

            save_transcript(wiki_dir, meeting_id, transcript_text)
            add_meeting(wiki_dir, record)
            _p(f"    → project: {project_id or 'unmatched'}")

            _align_crm(attendee_emails, record["date"], data_dir)
            _align_projects(project_id, record["date"], meeting_id, data_dir)

            draft_body = _generate_followup_draft(record)
            record["followup_draft"] = draft_body
            saved, draft_link = 0, None
            if draft_body and external_attendees:
                subj = f"Follow-up: {record.get('title', 'our meeting')}"
                html = draft_body.replace("\n", "<br>")
                for att in external_attendees:
                    try:
                        resp = graph.create_draft(subj, html, att["email"])
                        saved += 1
                        if not draft_link:
                            draft_link = resp.get("webLink")
                    except Exception as _e:
                        _p(f"    → Draft failed for {att['email']}: {_e}")
            record["followup_draft_saved"] = saved > 0
            record["followup_draft_link"]  = draft_link
            record["todos_pushed"] = _push_action_items_to_todo(record, graph, own_hints)

            _backup_to_onedrive(record, transcript_text, attendee_emails, graph, progress=_p)
            results.append({**record, "status": "processed"})

    processed_count = sum(1 for r in results if r.get("status") == "processed")
    skipped_count   = sum(1 for r in results if r.get("status") == "already_processed")
    error_count     = sum(1 for r in results if r.get("status") in ("error", "too_long"))
    _p(f"M03: {processed_count} processed | {skipped_count} skipped | {error_count} errors")

    return {
        "id":           "recent_meetings",
        "status":       "fresh" if processed_count > 0 else "not_run",
        "last_run":     datetime.now(timezone.utc).isoformat(),
        "processed":    processed_count,
        "skipped":      skipped_count,
        "errors":       error_count,
        "results":      results,
    }


# ── Pre-meeting brief ─────────────────────────────────────

def build_premeet_brief(
    event: dict,
    graph: GraphClient,
    ai: AIClient,
    data_dir: Path,
    settings: dict = None,
) -> str:
    """
    Generate a pre-meeting brief for Teams. Called ~30 min before a scheduled meeting.
    Pulls CRM info and past meeting records for attendees, AI generates a 3-5 bullet summary.
    Returns plain text ready for Teams message send.
    """
    data_dir = Path(data_dir)
    wiki_dir = data_dir / "wiki"
    _s       = settings or {}
    display  = _s.get("display_name", "you")
    today    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    title     = event.get("subject", "(no subject)")
    start_raw = event.get("start", {}).get("dateTime", "")
    try:
        from zoneinfo import ZoneInfo
        tz     = ZoneInfo(_s.get("timezone", "UTC"))
        dt     = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
        start  = dt.astimezone(tz).strftime("%H:%M")
    except Exception:
        start = start_raw[:16].replace("T", " ")

    attendee_emails = [
        a["emailAddress"]["address"]
        for a in event.get("attendees", [])
        if a.get("emailAddress", {}).get("address")
    ]

    # CRM context per attendee
    crm_contacts = load_crm(data_dir).get("contacts", {})
    crm_snippets = []
    for email in attendee_emails:
        c = crm_contacts.get(email.lower())
        if c:
            company = c.get("company", "")
            role    = c.get("role", "")
            summary = c.get("summary", "")
            last    = c.get("last_contact", "")
            line    = f"- {c.get('name', email)}"
            if company or role:
                line += f" ({role + ' @ ' if role else ''}{company})"
            if last:
                line += f" — last contact {last}"
            if summary:
                line += f"\n  {summary[:120]}"
            crm_snippets.append(line)

    # Recent meetings with same attendees
    recent = get_recent_meetings(wiki_dir, days=90)
    meeting_snippets = []
    for m in recent[:5]:
        overlap = set(m.get("attendee_emails", [])) & set(attendee_emails)
        if overlap:
            actions = "; ".join(
                f"{a.get('owner','')}: {a.get('action','')}"
                for a in m.get("action_items", [])[:2]
            )
            meeting_snippets.append(
                f"- {m.get('date', '')} {m.get('title', '')}: {m.get('summary', '')[:120]}"
                + (f"\n  Open actions: {actions}" if actions else "")
            )

    crm_block     = "\n".join(crm_snippets)  or "No CRM data for these attendees."
    meeting_block = "\n".join(meeting_snippets) or "No recent meeting history."

    prompt = (
        f"You are {display}'s executive assistant. Write a pre-meeting brief as a Teams message (plain text, no markdown headers).\n\n"
        f"Meeting: {title} at {start}\n"
        f"Attendees: {', '.join(attendee_emails) or 'none listed'}\n\n"
        f"CRM context:\n{crm_block}\n\n"
        f"Recent meeting history:\n{meeting_block}\n\n"
        f"Write 3-5 bullet points. Flag open action items if any. End with one suggested talking point.\n"
        f"Start with: 📋 Pre-meeting brief: {title} ({start})\n"
    )
    try:
        return ai.generate(prompt).strip()
    except Exception:
        return f"📋 Pre-meeting brief: {title} ({start})\nAttendees: {', '.join(attendee_emails)}"
