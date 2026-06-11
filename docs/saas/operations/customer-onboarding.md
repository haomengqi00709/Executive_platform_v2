# Customer onboarding — SaaS tier

**Audience:** Jason (engineer) and the sales partner.

## 1. Workflow for adding a new beta user

```
Partner ─────────► Jason ─────────► Railway ─────────► Customer
   1               2, 3                4               5, 6, 7
```

1. **Partner**: identify a prospect, get their Microsoft 365 sign-in
   email. Confirm it's the email they'll actually use to sign in (not a
   forwarding alias — Microsoft will reject sign-in if the alias doesn't
   match the primary on the account).
2. **Partner emails Jason** with the prospect's email.
3. **Jason** updates the `BETA_ALLOWLIST` env var in Railway:
   - Railway dashboard → service → Variables.
   - Append `,prospect@example.com` (lowercase).
   - Save.
4. Railway redeploys automatically (~1 minute).
5. **Partner** sends the prospect the signup link:
   - Link: `https://<railway-url>` (the public app URL).
   - Suggested template in Section 5.
6. **Prospect** clicks the link → Microsoft OAuth → app checks the
   allowlist.
   - In allowlist → proceeds.
   - Not in allowlist → redirected to `/?error=not_invited` with a
     friendly "you're not on the beta list" message.
7. **App** runs the first-login onboarding:
   - One-time scan of inbox, calendar, OneDrive (with progress UI).
   - Prompts the user to connect the Audrey Teams bot.
   - Prompts the user to confirm their profile context.
   - Lands the user on the dashboard.

## 2. Edge cases

### 2.1 Personal vs work Microsoft accounts

Microsoft's `preferred_username` claim may differ from the user's primary
email when they have a personal account (e.g., `user@hotmail.com`) signed
into a work tenant.

If the user can't sign in despite being on the allowlist, ask them what
email Microsoft shows on their OAuth consent screen, and add that exact
string to the allowlist.

### 2.2 Removing a user

Per a customer request (or at the end of a trial):

1. Remove the email from `BETA_ALLOWLIST` (so they can't sign in again).
2. If they ask for data deletion, additionally run the deletion
   procedure from `internal/data-retention-deletion.md` Section 2.
3. Confirm by email.

### 2.3 Multiple emails per prospect

If a prospect has two Microsoft accounts (work + personal) and might
sign in with either, add both to the allowlist. They will create two
separate accounts in the app.

### 2.4 Sign-in succeeds but onboarding hangs

Usually means OAuth scopes weren't fully granted, or Microsoft Graph
rate-limited the initial scan. Ask the user to sign out (Settings → Sign
out) and sign back in. If it persists, check logs for Graph API errors.

### 2.5 Beta participant requests BYOC

Direct them to the partner. BYOC is a separate sales conversation with
different commercial terms and a separate setup flow (see
`docs/deployment-mode-3-byoc.md`).

## 3. What the partner should communicate to the prospect

In the invitation email or call, the partner should cover:

- **What it is**: 1-sentence pitch.
- **What it does**: 5 modules, 1 sentence each.
- **What it needs**: Microsoft 365 OAuth consent.
- **What data it touches**: link to
  `customer-facing/data-handling-summary.md`.
- **Where data lives**: Railway US-east (mention proactively).
- **Cost**: free during beta.
- **Time commitment**: 15 min to set up; optional 30-min check-in after
  1 week.
- **How to give feedback**: partner email or shared Slack channel.
- **How to delete**: in Settings.

## 4. After onboarding — partner follow-up cadence

- **Day 1**: send "you're in, here's the dashboard" email.
- **Day 3**: short check-in: "any issues setting up?"
- **Day 7**: feedback call (30 min).
- **Day 14**: decide together — keep going / pause / convert to paid.

## 5. Sample invitation email (partner template)

```
Subject: CEO Platform beta — you're invited

Hi [name],

You're in for the CEO Platform beta. Here's how to start:

1. Click this link and sign in with your Microsoft 365 account:
   https://<railway-url>

2. Walk through the 15-minute setup (connect calendar, email, and the
   Audrey Teams bot).

3. You'll get a daily briefing tomorrow morning.

A few things to know:
- It's free during the beta.
- Your data lives in Railway (US-east). Full details:
  [link to data-handling-summary.md]
- You can delete your account anytime in Settings.
- Reply to this email with any question — I'll loop Jason in if it's
  technical.

I'll check in on day 7 to see how it's going.

[Partner name]
```

## 6. Future improvements

When invite count exceeds ~20:

- Move from env-var allowlist to a DB-backed allowlist table.
- Build a partner-facing admin UI to add/remove invites without
  involving Jason.
- Add per-invite tracking (sent date, accepted date, last active).
