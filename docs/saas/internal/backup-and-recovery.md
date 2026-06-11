# Backup and recovery — SaaS tier

**Audience:** internal operations.

## 1. Scope

What is backed up:

| Component | Backup mechanism | Frequency | Retention |
|---|---|---|---|
| Railway PostgreSQL (sessions, jobs metadata) | Railway-managed snapshot | Daily | 7 days |
| Volume `.data/` (user files, settings, results) | Manual `tar` to off-site (S3 / Backblaze B2) | Weekly | 30 days |
| Container image | Built from source in CI; source in GitHub | On every push | All git history |
| Source code | GitHub primary; mirrored to private backup | On every push | All git history |
| Env-var configuration | Manually documented in `operations/deployment-runbook.md` + Railway's own change history | On every change | Indefinite |

**Off-site backup configuration is currently TODO** — track as a Phase B
follow-up before commercial launch.

## 2. Retention policy

- **Daily PG snapshots**: 7 days (Railway default).
- **Weekly volume tarballs**: 30 days.
- **Annual archive**: not kept (no regulatory requirement at beta stage).

## 3. Restore procedures

### 3.1 PostgreSQL restore (Railway-managed)

1. Open Railway dashboard → project → PostgreSQL service.
2. Navigate to the Backups tab.
3. Select the snapshot to restore from.
4. Choose **Restore to a new database** (preferred — preserves the broken
   primary for forensics).
5. Update the app's connection string env var to point to the restored
   database.
6. Restart the app.
7. Verify by signing in as a known user and confirming recent data is
   present. Up to 24h of data loss is possible per the RPO target.

### 3.2 Volume restore (manual)

1. Identify the most recent off-site tarball that pre-dates the
   corruption.
2. Provision a new Railway volume.
3. Download the tarball from off-site storage.
4. Extract into the new volume.
5. Update the app's `DATA_DIR` env var.
6. Restart the app.
7. Verify per 3.1 step 7.

### 3.3 Container image restore

1. In Railway, navigate to previous deployments.
2. "Redeploy" the desired prior image.

## 4. RTO / RPO targets

- **RTO (Recovery Time Objective)**:
  - Single user issue: 24h
  - Full service outage: 72h
- **RPO (Recovery Point Objective)**: 24h (worst case = one daily
  snapshot ago)

These are beta-stage targets. Production-grade SLAs will tighten when
paid customers come on.

## 5. Verification

**Monthly restore drill** (target — currently not scheduled, add to
calendar):

1. Snapshot the PG to a scratch Railway project.
2. Verify a known user's data integrity (sign in, check sections).
3. Document the result.
4. Delete the scratch project.

Failing to test backups is the single most common backup failure mode.
Treat the drill as load-bearing, not optional.

## 6. Off-site backup setup (TODO)

Required before commercial launch:

1. Provision a Backblaze B2 bucket (or AWS S3 + lifecycle to Glacier).
2. Add a weekly GitHub Actions job that `tar`s the live `.data/` (via a
   dedicated backup endpoint or `railway run`) and uploads.
3. Encrypt with `gpg --symmetric` using a key stored separately from
   Railway secrets.
4. Document the restore-from-off-site procedure here.
