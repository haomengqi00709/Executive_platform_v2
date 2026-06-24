---
title: Workflow Tools (Outreach / Draft Composer)
describes_files:
  - src/modules/outreach.py
  - src/bot.py
  - src/bot_tools/projects/modify_project/tool.py
  - src/bot_tools/email/open_email/tool.py
  - src/bot_tools/contacts/list_crm_contacts/tool.py
derived_from_commit: 617a540
last_synced: 2026-06-24
---

# Workflow Tools (Outreach / Draft Composer)

User-triggered, one-shot AI tasks (as opposed to standing data or scheduled
pushes).

## Outreach
Batch-generates personalized outreach email drafts for a group of contacts.
- **Triggers:** (1) ask the Teams bot (e.g. "draft outreach for contacts tagged
  Berlin Summit"); (2) drop a contact file (business-card photos / CSV / Excel /
  PDF) into a watched OneDrive folder → AI extracts contacts, then drafts.
- **Output:** all drafts saved to **Outlook Drafts** for the user to review and
  send. Endpoint `/api/outreach/run`; bot tool `run_outreach`. Implemented in
  `src/modules/outreach.py` (it is a tool, **not** a section).

## Draft Composer
Single-email AI drafting + multi-turn refine, embedded in Reply Needed, Followup
Needed, CRM, etc. The user clicks "Draft reply", the AI writes a draft, and the
user can iterate ("more formal", "add a thank-you") before saving.

### Conversational draft flow (Teams bot — stage, refine, then save)
When the user asks the bot to "draft / write / compose an email", `create_reply_draft`
does **not** save to Outlook immediately. It **stages** the draft in conversation
state (`pending_draft`) and the bot **shows the full draft (To / Subject / Body) in
the chat**. The user then:
- **refines by talking** — "make it warmer", "add a line", "shorter" → the bot
  re-composes and re-stages the new version (no "editing a saved draft"; it simply
  re-drafts). This replaced an earlier dead end where the bot refused to revise an
  already-saved draft.
- **saves** — replies `1` (or "save" / "looks good") → `approve_draft()` writes it to
  **Outlook Drafts**.
- **discards** — "no" / "skip" → `skip_draft()`.

Only on save is anything written to Outlook. **Nothing is ever sent** — there is no
send capability; the drafts-only safety boundary holds.

### Conversational behavior rules (system prompt)
The bot's system prompt encodes a few standing rules, in addition to the [#N] /
disambiguation / completion-gate rules above:
- **Act, don't ask** — when it can reasonably proceed it does, then shows the
  result: it composes a draft from context rather than asking "what should it
  say"; it auto-books a *solo* calendar block at a sensible default time. A
  meeting *with other attendees* and a vague time is the exception — it proposes a
  specific slot and waits, so no invite goes out at a guessed time.
- **Multiple requests in one message** — "do X and also Y" is handled in full this
  turn, not just the first half.
- **[#N] binds by type** — `snooze/mark N` → commitments list, `reply N` → email
  list, `meeting N` → meetings list, `contact N` → contacts list, `project N` →
  projects list, regardless of which list was shown most recently. Each list source
  keeps its own bucket (e.g. a frequency report vs a name search vs a CRM-by-attribute
  list are separate), so a "#N" from one list never resolves against another.
- **When it can't** — for actions with no tool (cancel/reschedule a meeting,
  forward/delete email, out-of-office, SMS, filter a group by role) it says so
  plainly and offers the closest supported alternative; it never fakes success
  (creating a new event is not "moving" an existing one).
- **Empty-response retry** — the agent loop retries a blank (`out=0`) model
  response a few times before falling back, so a transient blank doesn't surface
  as "I looked into that but didn't finish".

## Conversational bot — list & pick, look before you ask
The Teams bot (`src/bot.py` `reply()`) shares one **[#N] convention** across every
list-returning tool: `_with_indices()` stamps each item with a 1-based `index`, the
bot displays items as `[#1] … [#2] …`, and a later "do #2" is resolved back to the
item's canonical id (email_id / event_id / draft_id / contact email). Contacts
(`find_contacts_by_name`) and groups (`list_my_groups`) are part of this too.

**Disambiguation rule:** when the user names a person/target for an action
("schedule a meeting with Daniel"), the bot must **look first** —
`find_contacts_by_name` — before asking anything. One match → proceed; several →
present them as a `[#N]` list and ask which; none → ask for the email. It never
replies a vague "I found a few, please specify" without first looking them up and
listing them.

**Completion gate:** every turn is verified against ground-truth (which action
tools actually succeeded), not the draft reply's own claims. A blind "please
specify" with no lookup is treated as *actionable* and re-driven to look + list;
the bot only stops to ask the user when info is genuinely user-only (a time, a
confirmation) or several candidates genuinely match after a lookup.

**The gate only runs when there is something to verify.** A deterministic
pre-filter enters the gate only when (1) an action tool was attempted, (2) the
reply claims an action it may not have performed, or (3) the bot asked the user
to pick among candidates without looking them up. Pure reads ("show my emails",
"my commitments"), chat, and honest questions skip the gate entirely — earlier,
running the flaky checker on reads occasionally re-drove them and overwrote the
correct answer with a false "I was unable to retrieve…". Reads now resolve in
one pass with no verifier call.

## Other bot actions (recently added)
- **`modify_project`** — change one field on a project (status / momentum / category / ignore) by
  name or `#N`; writes straight to the store, reflects immediately. See [projects](projects.md).
- **`open_email`** — fetch the FULL verbatim body of an original email by id (the cached lists only
  carry a preview). Accepts a commitment's id too (resolved to its source email). Used only when the
  user wants the full text — "where is it from / what's it about" is answered from the item's own fields.
- **`list_crm_contacts`** — list the curated CRM by status/priority/tag (see [data-management](data-management.md)).

## The hard rule
**Drafts are never auto-sent.** Everything the AI writes is saved to Outlook Drafts;
a human approves and sends. This is a platform-wide safety boundary.

## Common questions
- *"Did it email the client?"* — No. It only creates a draft; sending is always a
  manual human action.
