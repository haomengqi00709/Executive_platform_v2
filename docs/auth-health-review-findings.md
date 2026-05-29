# Auth Health & Email Notification — Code Review Findings

Review date: 2026-05-27
Commit reviewed: `568aa08` — *Surface auth failures to users: status indicator + email alerts*
Methodology: 5 independent finder agents × 8 candidates → 1-vote verify → sweep. 21 confirmed + 8 sweep additions, top 15 below.

---

## How to use this doc

Each finding has: **what's wrong**, **how it fails**, **fix sketch**. Check off as you fix. Don't fix in order — read first, group fixes that share a root cause.

The bug pattern across most findings: the state machine was designed for single-threaded happy path. It doesn't handle (a) concurrent access from APScheduler's polling threads, (b) non-transition states (every-failure-past-threshold vs. just-broke), or (c) closing the reconnect-UX loop.

---

## TIER 1 — Will bite Daniel today

### 1. Reconnecting doesn't clear the red dot for ~55 minutes

- [ ] **Fix**
- **File**: `src/server.py` (OAuth `/auth/callback` and bot device-flow completion routes)
- **What**: Successful re-login saves new tokens via `save_user_tokens` but never calls `_record_auth_success`. The `.auth_health.json` still says status=broken. Red dot + "Reconnect" CTA stay visible until the cached access token naturally expires (~55 min) and the next refresh path finally writes status=healthy.
- **Failure**: User sees red dot, clicks Reconnect, completes OAuth, looks at dashboard — still red. Thinks the reconnect button is broken.
- **Fix sketch**: After every successful interactive auth (web callback + device-flow completion), call `auth._record_auth_success(user_id, op="reauth")` to immediately clear health state.

### 2. One broken user blocks bot polling for everyone

- [ ] **Fix**
- **File**: `src/auth_notifier.py:222` (and the call chain back to `_record_auth_failure`)
- **What**: `check_and_notify` runs synchronously inside `_record_auth_failure`, inside `get_valid_access_token`, inside the APScheduler poll thread. `send_mail` (1–30s sync HTTPS) + possible `classify_aadsts` Gemini call (5–15s) can block for ~30s. APScheduler `max_instances=1` means the next 10s tick coalesces — bot polling for all other users pauses.
- **Failure**: Audrey's token broken → every 10s the bot-poll thread spends 30s sending an email → during those 30s, no other user's bot is polled.
- **Fix sketch**: Move `check_and_notify` to a background thread (`threading.Thread(target=..., daemon=True).start()`) or a dedicated APScheduler job that the failure path only enqueues, never blocks on.

### 3. Email "click here" link goes to the wrong page

- [ ] **Fix**
- **File**: `src/auth_notifier.py:32` (`RECONNECT_PATH = "/#settings"`)
- **What**: The React SPA has no hash router. `page` is local `useState<Page>` defaulting to `'dashboard'`. `window.location.hash` is never read.
- **Failure**: User clicks the email link, lands on Dashboard, has to figure out where to go.
- **Fix sketch**: Either (a) add a `useEffect` in `App.tsx` that reads `window.location.hash` on mount and calls `setPage('settings')`, or (b) change the link to a query param (`?page=settings`) and parse it in the same place, or (c) point at `/auth/login` for owner re-login (which already works as a real route).

### 4. Gemini gets hammered for every un-cacheable AADSTS code

- [ ] **Fix**
- **File**: `src/auth_errors.py:148-156`
- **What**: The AI-fallback path returns a generic message when Gemini fails (returns None) but does **not** write to `.aadsts_cache.json`. Frontend polls `/api/auth/health` every 30s. server.py `_account_health_dot` calls `classify_aadsts` per request when `status=="broken"`. Each call re-invokes Gemini.
- **Failure**: Broken user + unknown AADSTS code + Gemini transient failure → ~120 Gemini calls/hour for one user. Real $$$.
- **Fix sketch**: Cache the fallback result too (with a `source: "fallback"` marker and short TTL like 1h, so a future deploy with better mapping kicks in). Or: cache aggressively, never hit Gemini twice for the same code in the same hour regardless of success.

---

## TIER 2 — State-machine correctness

### 5. After recover → re-break, no email is sent

- [ ] **Fix**
- **File**: `src/auth.py:255-264` (`_record_auth_success`)
- **What**: Recovery overwrites `status`, `consecutive_failures`, `last_success_at`, `broken_since`. Leaves `notifications.sent_count` and `notifications.first_sent_at` intact.
- **Failure**: Account breaks → email #1 (sent_count=1, first_sent_at=T0). Recovers. Breaks again 1 hour later → `_should_send` reads sent_count=1, now-T0 < 7d → returns "skip". User gets NO email about the second outage. At T0+7d returns "reminder" — but reminder for what? The second break may have happened 6 days ago.
- **Fix sketch**: In `_record_auth_success`, add `health["notifications"] = {}` (or set `sent_count=0, first_sent_at=None`).

### 6. `check_and_notify` runs on every failure past threshold, not just the transition

- [ ] **Fix**
- **File**: `src/auth.py:301-304` (in `_record_auth_failure`)
- **What**: Condition is `if health.get("status") == "broken":` — once broken, stays broken. Every subsequent failure (10s bot poll, 1min email_monitor) re-enters check_and_notify. `_should_send` mostly returns "skip" but everything upstream of it still runs: load health, call classify_aadsts, call `_pick_sender_uid` (with its candidate-mutating side effects).
- **Failure**: Hundreds of useless notifier invocations per hour per broken user, driving all the other cascade bugs (especially #7).
- **Fix sketch**: Gate the call on the local `just_broke` flag we already compute: `if just_broke: check_and_notify(user_id)`. (Single-line fix that eliminates most of the cascade pain.)

### 7. Probing a sender candidate corrupts ITS health

- [ ] **Fix**
- **File**: `src/auth_notifier.py:108`
- **What**: `auth.get_valid_access_token(uid)` is used to check "can this account send?" — but it's not side-effect-free. On failure it runs `_record_auth_failure(uid)` which increments the candidate's consecutive_failures.
- **Failure**: Bot B broken. Notifier probes owner O. O has transient Microsoft 500. O's counter bumps. Over many B-poll iterations, transient O probes accumulate 4 failures → O flips to broken too. Cascade emails about O being broken when O is fine.
- **Fix sketch**: Replace probe with a non-mutating check — `tokens = auth.load_user_tokens(uid); not_expired = datetime.fromisoformat(tokens["expiry"]) > now + buffer`. Only call the real refresh once you've decided to send.

### 8. Race condition: lost failure-counter increments

- [ ] **Fix**
- **File**: `src/auth.py:275-289` (`_record_auth_failure`)
- **What**: No lock around load-mutate-save. Two scheduler threads both load `consecutive_failures=N`, both write `N+1`. Second is lost.
- **Failure**: Six real failures can sit at counter=3 forever, never crossing the threshold of 4, never triggering notification. Or: both threads cross threshold simultaneously → both fire `just_broke=True` → duplicate first email.
- **Fix sketch**: Per-user `threading.Lock` keyed by user_id (dict-of-locks with a guard lock for dict creation). Or use file locking (`fcntl.flock`) around load-mutate-save. Or accept the race but make the threshold check idempotent (compare-and-set on disk via a sequence number).

### 9. `check_and_notify` saves stale health → wipes concurrent failure increments

- [ ] **Fix**
- **File**: `src/auth_notifier.py:200` (load) → `:233` (save)
- **What**: `health` loaded once at line 200. send_mail blocks for seconds. During that window, other threads call `_record_auth_failure` and bump consecutive_failures via their own load-mutate-save cycles. At 233, we save the stale health dict back.
- **Failure**: Failure counter regresses from N+2 back to N, and `last_error` / `last_failure_at` may go backward in time.
- **Fix sketch**: After send_mail, reload health from disk, merge only the `notifications` subkey, save. (Same lock as #8 would also fix this.)

### 10. Send-before-save → failed save means duplicate emails

- [ ] **Fix**
- **File**: `src/auth_notifier.py:222` (send) precedes `:233` (save)
- **What**: send_mail succeeds. Process crashes (Railway redeploy, OOM, signal). Next failure 10s later sees notifications={}, decides "first", sends another email.
- **Failure**: User receives N copies of the "initial" alert, one per restart cycle.
- **Fix sketch**: Write `sent_count=1, first_sent_at=now()` BEFORE calling send_mail. If send fails, log to dead-letter and accept that we may not retry (which is what the "max 2" invariant kind of wants anyway). At-most-once is the right semantics here.

---

## TIER 3 — UX inconsistencies

### 11. `/api/teams/bot` reports `connected: True` even when owner is broken

- [ ] **Fix**
- **File**: `src/server.py:628` (bot-bound branch) + `:639` (no-bot branch)
- **What**: `connected` is computed only from BOT health. Hardcoded True for the no-bot branch. Frontend Settings page reads `botStatus?.connected !== false` to render "AI assistant connected".
- **Failure**: HealthDot (which calls `/api/auth/health` and DOES check owner) shows red. Settings page shows green. User clicks Reconnect bot → nothing helps because the actual broken account is the owner.
- **Fix sketch**: Include owner health in the response: `"connected": owner_health.status != "broken" and (bot_health.status != "broken" if bot_uid else True)`. Or split into two booleans `bot_connected` + `owner_connected`.

### 12. Infrastructure errors get labeled as "please reconnect"

- [ ] **Fix**
- **File**: `src/auth.py:194-197` (the try/except around `acquire_token_silent_with_error`)
- **What**: Any Python exception (IOError on token cache, JSONDecodeError on corrupt cache, etc.) gets wrapped into `{"error": "exception", "error_description": str(e)}`. Then `extract_aadsts_code` finds no AADSTS code and falls back to "Please try signing in again."
- **Failure**: Disk permission bug on the server → user gets an email saying "reconnect", does so, problem persists. Admin never learns there's an infra issue.
- **Fix sketch**: Tag the wrapped exception specifically (`error_codes=[-1]` or `error="infra_exception"`) and route to a different action_type like `"admin-investigate"` with a message that says "this is a server-side error, the engineering team has been notified" and writes a loud log line.

---

## TIER 4 — Pre-existing bugs newly exposed (NOT introduced by this PR but related)

### 13. `refresh_crm` daily wipes manual website/phone/linkedin/writing_style edits

- [ ] **Fix**
- **File**: `src/modules/crm.py:604-619` (preserve list in `refresh_crm`)
- **What**: `build_crm` preserves `("priority", "writing_style", "phone", "linkedin", "website", "ignore")`. `refresh_crm` (cron 06:30 UTC) only preserves `("priority", "ignore")` and assigns `contacts[addr] = enriched`. Any manual edit to phone/linkedin/website/writing_style is overwritten by whatever AI re-derived (often empty).
- **Failure**: User adds a website to a contact. Next morning the value is gone.
- **Fix sketch**: Sync the preserve list with `build_crm`'s. (One-line change, but verify no callers depend on the current "AI is authoritative" semantics.)
- **Note**: The new Website field added in user's WIP exposes this pre-existing bug on a freshly-visible column.

### 14. `email_monitor.py` drops priority emails after one digest

- [ ] **Fix** (this is in user's WIP, not yet committed)
- **File**: `src/modules/email_monitor.py:468`
- **What**: New code unconditionally clears `pending_priority_followup` after each digest. Old comment intended "persist until replied or 7 days old."
- **Failure**: CEO ignores immediate Teams card → digest mentions it once → cleared → email permanently forgotten. The "don't drop the ball" track is defeated.
- **Fix sketch**: Re-introduce the per-email check — clear only if `_check_replied(email_id)` returned true OR `received_date < now - 7d`.

### 15. Disabled bots are still used as email senders

- [ ] **Fix**
- **File**: `src/auth_notifier.py:73` (`_find_bot_owned_by`)
- **What**: Filter checks `owner_uid == owner and is_registered_bot` but NOT `enabled`. Compare with `server.py:313` `_find_bot_for_user` which DOES check `enabled`.
- **Failure**: User disabled their bot in Settings. Owner's account later breaks. `_pick_sender_uid` picks the disabled bot, sends email from "Audrey's mailbox" — the bot the user explicitly turned off.
- **Fix sketch**: Add `and s.get("enabled")` to the filter at line ~73.

---

## Suggested fix order

If we batch-fix this, my recommendation:

1. **#6** (gate notifier on `just_broke`) — single-line, kills most cascade pain in this list
2. **#1** (reconnect resets health) — visible UX win, small code surface
3. **#2** (move email send off scheduler thread) — solves perf cliff, prerequisite for sane behavior under load
4. **#3** (fix reconnect link) — paste a `useEffect` reading hash → 5 min
5. **#5** (`_record_auth_success` clears `notifications`) — same function as #1, fix together
6. **#10** (save before send) — change ordering, idempotent
7. **#7** (non-mutating sender probe) — replace one line
8. **#4** (cache fallback) — small but real cost
9. **#11** (owner health in /api/teams/bot) — affects Settings page consistency
10. **#15** (`enabled` check in `_find_bot_owned_by`) — one line
11. **#13** (`refresh_crm` preserve list) — one line, affects WIP feature
12. **#14** (priority email persistence) — small but uses user's WIP
13. **#8 + #9** (race condition with lock) — bigger change, do once we've reduced contention via #6
14. **#12** (infra-error classification) — distinguish-and-route work

---

## Out of scope (acknowledged, not in top 15)

These survived verification but were trimmed for severity:

- HealthDot tooltip stays visible after click+navigation (UI polish)
- useEffect lacks AbortController on `/api/auth/health` poll (latent, harmless today)
- Web-refresh error overwritten by legacy error (edge case)
- `_account_email` None → `<b>None</b>` in email body (cosmetic)
- `_save_cache` non-atomic write in `auth_errors.py` (cache rebuild on crash)
- Shared global `.auth_diag.log` / `.aadsts_cache.json` violates multi-user isolation principle
- `parse_when` rejects "1.5h" / "1h30m" (diag CLI quality of life)
- REDIRECT_URI parsing fallthrough when path lacks `/auth/` (deployment footgun)
- Yellow dot persists for ~55 min after single transient blip (UX confusion)
- `_account_label.capitalize()` mangles "AI" to "ai" (cosmetic, every email)
- `_should_send` can dead-end on corrupted `first_sent_at` JSON (rare edge case)
- Mutual-broken (both bot and owner) silently dead-letters (rare, has dead-letter log)
- Regex `\{[^{}]+\}` can't match nested JSON from AI (degrades gracefully today)

If we hit any of these in practice, promote to top tier.
