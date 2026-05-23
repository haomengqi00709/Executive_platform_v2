"""
Email screener — binary keep/screen-out decision before M02 classification.

Two-stage filter:
  1. CRM ignore list — instant screen-out, no AI call.
  2. AI batch screening — one prompt per 50-email batch, parallel execution.

Returns the same messages list with two fields added per message:
  screened_out: bool
  screen_reason: str  (empty if kept; standardized code if screened out)
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.ai import AIClient


_BATCH_SIZE_DEFAULT = 50
_MAX_WORKERS = 5

_VALID_REASONS = frozenset({
    "meeting acceptance",
    "auto reply",
    "marketing newsletter",
    "platform notification",
    "short acknowledgment",
    "billing receipt",
    "automated notification",
})


def _addr(msg: dict) -> str:
    return ((msg.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()


def _name(msg: dict) -> str:
    ea = (msg.get("from") or {}).get("emailAddress") or {}
    return (ea.get("name") or "").strip() or ea.get("address", "").split("@")[0]


def _build_prompt(batch: list[dict], business_context: str, display_name: str) -> str:
    email_lines = "\n".join(
        f"[{i}] From: {_name(m)} <{_addr(m)}> | "
        f"Subject: {(m.get('subject') or '(no subject)')[:100]} | "
        f"Preview: {(m.get('bodyPreview') or '')[:200]}"
        for i, m in enumerate(batch)
    )

    bc_block = (
        "BUSINESS CONTEXT (use this to identify known contacts and real business relationships):\n"
        f"{business_context.strip()}\n\n"
    ) if business_context.strip() else ""

    return f"""You are an email filter for {display_name}, a busy executive.

This is a BUSINESS email inbox. The only emails worth showing are those with direct business value:
a real person writing about work, money, a client relationship, a decision, or a commitment.

{bc_block}FILTERING PHILOSOPHY: Screen out anything that does not require {display_name}'s attention
as a business professional. The question is not "could this theoretically be important?" —
it is "does a CEO need to read or act on this to run their business?"

━━━ SCREEN OUT (keep=false) ━━━

1. MEETING RESPONSES: Calendar accept / decline / tentative / cancellation notifications.
   Signal: subject contains "Accepted:", "Declined:", "Tentative:", "Canceled:", "Cancelled:"
   or language equivalents anywhere in the subject:
     Chinese: "已接受", "已拒绝", "暂定", "已取消"
     French: "Accepté", "Refusé", "Provisoire", "Annulé"
     Spanish: "Aceptado", "Rechazado", "Provisional", "Cancelado"

2. AUTO-REPLIES & SYSTEM BOUNCES: Out-of-office, vacation replies, undeliverable/bounce notices,
   read receipts, delivery status notifications.

3. MARKETING & NEWSLETTERS: Promotional emails, newsletters, subscription digests, retail offers,
   welcome emails from any consumer or SaaS service, re-engagement campaigns.
   Examples: Morning Brew, product updates from Notion/Canva/HubSpot, Azure promotional emails,
   "Welcome to [service]", "Get started with [product]", "Tips for using [app]".

4. PLATFORM & BOT NOTIFICATIONS: Automated activity emails from any software tool or internal bot.
   Examples: Slack digests, GitHub notifications, Jira updates, Salesforce reports,
   DocuSign "viewed" alerts, Calendly bookings, Zoom recordings, Teams chat notifications,
   report emails whose subject starts with "[CEO Platform]", "[Executive AI]", or a similar
   bracketed platform prefix — these are ALWAYS platform notifications regardless of sender name,
   even if sent from a real person's address (the platform generated the content, not the person).

5. CONSUMER & PERSONAL ACCOUNT EMAILS: Anything from a consumer brand, retailer, sports or
   entertainment service, or personal account management. These have zero business value.
   Examples: order confirmations, shipping updates, loyalty program emails, account welcome emails,
   one-time login codes or password resets from non-business services (Nike, Amazon, Apple,
   Tennis Warehouse, airline loyalty programs, streaming services, etc.).

6. VERIFICATION CODES & OTP: One-time passwords, verification codes, "confirm your email" messages
   from any service. Automated, no reply needed, no business value.

7. SAAS SUBSCRIPTION RECEIPTS ONLY: Automated renewal confirmations for recurring software
   subscriptions where no review is needed — e.g. "Your Notion subscription has been renewed",
   "AWS monthly invoice", "Your Adobe plan was charged".
   DO NOT filter receipts from restaurants, hotels, transport (Uber, Lyft, taxi), airlines,
   or any other real-world business expense — those are needed for expense tracking.

8. PURE ACKNOWLEDGMENTS: A reply whose entire visible body is only: "ok", "thanks", "noted",
   "got it", "received", "will do", "sounds good", "sure", "perfect", "great", or a trivial
   combination. Screen out ONLY when there is zero additional content — no question, no update,
   no new information of any kind.

━━━ KEEP (keep=true) — business-value emails only ━━━

PRIORITY RULE: If the email is FROM a real identifiable person — meaning the sender has a
real name and a non-automated email address (not a no-reply@, notifications@, noreply@,
info@massmailer, or similar automated address) — KEEP IT regardless of the subject line.
A person forwarding a receipt, sending a short note, or writing "something for tomorrow"
is a real human who chose to send that email. Subject line alone never overrides a real sender.

- A real person writing about a client, project, contract, deal, or business decision
- Any email requiring a reply, an action, or follow-up from {display_name}
- Invoices or contracts requiring review, approval, or signature
- Receipts from restaurants, hotels, transport services (Uber, Lyft, taxi, rideshare), airlines,
  or any real-world business expense — these are needed for expense tracking
- Any complaint, escalation, or expression of dissatisfaction from a real person
- New business inquiries or cold outreach from a potential client or partner
- Any email where ignoring it could damage a business relationship or miss a deadline
- When genuinely uncertain whether the sender is a real business contact: KEEP

REMEMBER: Categories 3, 5, and 6 above (marketing, consumer, verification) apply ONLY to
emails sent BY automated systems or consumer brands — never to emails sent by a real person.

━━━ STANDARDIZED REASON CODES (use exactly these strings when keep=false) ━━━

"meeting acceptance"      — calendar accept/decline/tentative
"auto reply"              — out-of-office or automated reply
"marketing newsletter"    — commercial email, newsletter, promotion
"platform notification"   — SaaS tool notification (Slack, Jira, GitHub, DocuSign, etc.)
"short acknowledgment"    — entire message is only ok/thanks/noted/received/etc.
"billing receipt"         — automated payment confirmation from known billing service
"automated notification"  — other automated system message that doesn't fit above categories

━━━ OUTPUT FORMAT ━━━

Return a JSON array. One object per input email, in the same order:
[
  {{"index": 0, "keep": true, "reason": ""}},
  {{"index": 1, "keep": false, "reason": "platform notification"}},
  ...
]

Rules:
- Every input index must appear exactly once in the output.
- "reason" must be empty string when keep=true.
- "reason" must be one of the standardized codes above when keep=false.
- Do not add any fields beyond "index", "keep", "reason".

Emails to screen:
{email_lines}"""


def _screen_batch(
    batch_idx: int,
    batch: list[dict],
    ai: AIClient,
    business_context: str,
    display_name: str,
    progress,
    total_batches: int,
    completed_counter: list,
    lock: threading.Lock,
) -> tuple[int, list[dict]]:
    if not batch:
        return batch_idx, batch

    prompt = _build_prompt(batch, business_context, display_name)

    try:
        raw = ai.extract_json(prompt)
        results = json.loads(raw)
        if not isinstance(results, list):
            raise ValueError("non-list response")
    except Exception:
        for msg in batch:
            msg["screened_out"] = False
            msg["screen_reason"] = ""
        with lock:
            completed_counter[0] += 1
            if progress:
                progress(f"Screening emails — {completed_counter[0]}/{total_batches} batches done")
        return batch_idx, batch

    result_map: dict[int, dict] = {}
    for item in results:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if idx is None or not isinstance(idx, int) or not (0 <= idx < len(batch)):
            continue
        result_map[idx] = item

    for i, msg in enumerate(batch):
        item = result_map.get(i)
        if item is None:
            msg["screened_out"] = False
            msg["screen_reason"] = ""
            continue

        keep = item.get("keep")
        if not isinstance(keep, bool):
            msg["screened_out"] = False
            msg["screen_reason"] = ""
            continue

        reason = (item.get("reason") or "").strip()
        if not keep and reason not in _VALID_REASONS:
            msg["screened_out"] = False
            msg["screen_reason"] = ""
        else:
            msg["screened_out"] = not keep
            msg["screen_reason"] = reason if not keep else ""

    with lock:
        completed_counter[0] += 1
        if progress:
            progress(f"Screening emails — {completed_counter[0]}/{total_batches} batches done")

    return batch_idx, batch


def screen_emails(
    messages: list[dict],
    ai: AIClient,
    ignored_emails: set[str],
    business_context: str = "",
    display_name: str = "the executive",
    batch_size: int = _BATCH_SIZE_DEFAULT,
    progress=None,
) -> list[dict]:
    """
    Screen a list of raw Graph API email objects.

    Returns the same list with two fields added to each message:
      screened_out: bool
      screen_reason: str
    """
    if not messages:
        return messages

    ignored_lower = {e.lower() for e in (ignored_emails or set())}
    remaining: list[dict] = []

    for msg in messages:
        addr = _addr(msg)
        if addr and addr in ignored_lower:
            msg["screened_out"] = True
            msg["screen_reason"] = "user_ignored"
        else:
            msg["screened_out"] = False
            msg["screen_reason"] = ""
            remaining.append(msg)

    if not remaining:
        return messages

    pre_filtered = len(messages) - len(remaining)
    if progress:
        detail = f" ({pre_filtered} pre-filtered by CRM ignore list)" if pre_filtered else ""
        progress(f"Screening {len(remaining)} emails via AI{detail}...")

    batches = [remaining[i:i + batch_size] for i in range(0, len(remaining), batch_size)]
    total_batches = len(batches)
    completed_counter = [0]
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _screen_batch,
                i, batch, ai,
                business_context, display_name,
                progress, total_batches,
                completed_counter, lock,
            ): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            future.result()

    return messages
