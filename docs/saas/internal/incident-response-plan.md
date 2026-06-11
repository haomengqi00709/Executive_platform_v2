# Incident response plan — SaaS tier

**Audience:** internal team. Drives behavior during a security incident,
outage, or data breach.

## 1. Definitions

- **Incident**: any event that disrupts normal service or may indicate a
  security problem. Includes outages, unexpected errors, and anomalies.
- **Breach**: an incident in which unauthorized parties access, alter, or
  exfiltrate customer data. A breach is a subset of incidents.
- **Outage**: an incident in which the service is wholly or partially
  unavailable to users. May or may not be a breach.

## 2. Severity levels

| Level | Definition | Examples |
|---|---|---|
| **P0** | Customer data breach (confirmed or strongly suspected) | Cross-user leak, OAuth token exfiltration, leaked database |
| **P1** | Service-wide outage or broken authentication | App returns 5xx for >5 min, OAuth callback failing for all users |
| **P2** | Significant degradation affecting many users, or single-user data integrity loss | A module produces broken output for >25% of users, one user reports missing data |
| **P3** | Minor or cosmetic, single-user, easily worked around | UI rendering bug, slow response on one endpoint |

## 3. Detection

We detect incidents via, in priority order:

1. **Automated monitoring** (UptimeRobot pings `/api/auth/status` every 5
   minutes; emails Jason on failure).
2. **Application error logs** (FastAPI structured logs; checked daily).
3. **Customer reports** (email to support contact; partner relay from
   Slack/Teams).
4. **Sub-processor status pages** (Microsoft, Google, Railway).

## 4. Response team

- **Incident commander**: Jason (technical lead). Makes containment and
  remediation calls.
- **Customer communications**: Partner (sales / relationship). Owns the
  customer-facing message.
- **Legal escalation**: outside counsel (TBD — to be retained before
  commercial launch).

## 5. Response procedure

### 5.1 Triage (target: P0/P1 within 1h business hours, 4h after-hours)

1. Confirm the incident is real (reproduce or verify in logs).
2. Assign severity per Section 2.
3. Open an incident log file (private team repo or notes doc): timeline,
   hypotheses, actions taken. Update continuously.

### 5.2 Contain

1. If credentials may be exposed: rotate immediately (`SESSION_SECRET`,
   sub-processor API keys).
2. If a specific user account is affected: temporarily invalidate that
   user's session.
3. If the whole service is compromised: shut down the Railway service
   until contained.

### 5.3 Mitigate / patch

1. Identify root cause.
2. Develop and deploy the fix.
3. Verify in production.

### 5.4 Notify affected customers (P0 breaches: target 72h)

Send a notification email with at minimum:

- What happened
- What data was affected (or "we are still investigating")
- When it happened
- What we've done about it
- What the customer should do
- Who to contact

Templates in Section 7.

### 5.5 Resolve and verify

1. Confirm metrics and logs return to baseline.
2. Re-enable any disabled features.
3. Close the incident with a summary message to affected customers.

### 5.6 Post-mortem (target: 5 business days)

For P0 and P1, write a post-mortem covering:

- Timeline (detection → resolution)
- Root cause
- What worked
- What didn't
- Action items to prevent recurrence

Post-mortems are internal-only by default; share with affected customers
on request.

## 6. Sub-processor incidents

If Microsoft, Google, or Railway has the incident, our role is:

1. Acknowledge to affected customers.
2. Link the sub-processor's public status page.
3. Apply any vendor-recommended mitigations on our side.
4. Notify affected customers when the sub-processor declares resolution.

## 7. Communication templates

### 7.1 P0 customer breach notification (email)

```
Subject: Security notice — your CEO Platform account

Hi [name],

We're writing to inform you of a security incident affecting your CEO
Platform account.

What happened: [1-2 sentences, plain language]

When: [start and end times, customer's local time zone]

What data was affected: [specific list, or "we are still investigating"]

What we've done: [actions taken]

What you should do: [specific instructions; for our setup we don't hold
passwords, so usually nothing on the customer's end]

We are investigating and will follow up with [target time / "more
information as we learn more"]. If you have questions or concerns, reply
to this email directly.

[Sender name]
CEO Platform
```

### 7.2 P1 service-wide outage notification

```
Subject: CEO Platform service incident — [date]

We're experiencing a service incident that is affecting all users.

What's affected: [scope]
Start time: [time]
Status: [investigating / mitigating / resolved]

We'll update you when the service is fully restored.

[Sender name]
```

## 8. Contact info

- Incident commander: **_Jason — email + phone_**
- Customer communications: **_Partner — email + phone_**
- Legal escalation: **_TBD_**
- Microsoft 365 support: M365 admin portal
- Google Cloud support: Google AI Studio billing portal
- Railway support: railway.com support widget

## 9. Drills

Annual tabletop exercise. Low priority during beta — schedule the first
one when paid customer count ≥ 3. Walk through a synthetic P0 with the
response team and identify gaps.
