# Data retention and deletion — SaaS tier

**Audience:** internal team and (on request) customer security teams.

## 1. Retention summary

| Data class | Retention while account active | After deletion request |
|---|---|---|
| User profile (name, email) | Indefinite | Removed within 7 days |
| User content (`.data/{user_id}/`) | Indefinite | Removed within 7 days |
| OAuth tokens | Indefinite (auto-refreshed) | Removed within 7 days |
| Application logs (with PII redacted) | 30 days | 30 days from generation |
| PG backups containing deleted user data | 30 days | Purged automatically as the backup window rolls |
| Off-site volume tarballs containing deleted user data | 30 days | Purged automatically |
| Audit logs of vendor (human) access | N/A (not yet implemented) | TBD |

## 2. Account deletion procedure

### 2.1 Customer-initiated (preferred path)

1. Customer signs in.
2. Navigates to Settings → "Delete my account".
3. Confirms via modal: "This will delete all your data. Are you sure?".
4. Frontend calls `DELETE /api/account`.
5. Backend:
   - `shutil.rmtree(DATA_DIR / user_id)` — removes all user content.
   - Removes `.data/_sessions/{user_id}.json` — invalidates session.
   - Sends a deletion-confirmation email to the user's authorized email.
6. Frontend redirects to a "Your account has been deleted" page.
7. Customer should separately revoke OAuth consent at
   https://myaccount.microsoft.com → Permissions.

### 2.2 Email-initiated (fallback)

If the in-app deletion is broken or the customer cannot sign in:

1. Customer emails the deletion address with a request and the email used
   to sign up.
2. We confirm identity (reply to the same email, ask for the user's OAuth
   subject ID if available, or use the partner relationship for known
   customers).
3. We manually run the deletion (currently `rm -rf .data/{uid}` via
   Railway shell; a maintenance script is a future improvement).
4. We reply to confirm deletion within 7 days of the original request.

## 3. What survives deletion

After a deletion request runs through both 2.1/2.2 and the 30-day backup
window:

- Nothing in production storage.
- Nothing in backups.
- Application logs may contain redacted references (e.g., "user X
  triggered email triage at time T") — these expire at 30 days.

## 4. Data portability (export)

Customers may request a JSON archive of all their data. As of beta, this
is **manual**:

1. Customer emails request.
2. We run `tar -czf user_export.tar.gz .data/{uid}/`.
3. Send the file via encrypted transfer (or password-protected link).

An in-app self-service export is on the roadmap.

## 5. Lawful retention exceptions

If we receive a valid legal order (subpoena, court order) requiring
retention beyond a deletion request:

1. We consult counsel before acting.
2. We may retain the relevant data, isolated from production, only as
   long as the order requires.
3. We notify the customer of the order (unless legally prohibited from
   doing so).

This has never happened. It's documented here for completeness.

## 6. Audit log of deletions

We maintain an internal log (currently a manual notes file; future: a
dedicated DB table) of all deletion requests with:

- Date received
- Date completed
- Method (in-app vs email)
- Any complications

This protects us if a customer later claims their data wasn't deleted.
