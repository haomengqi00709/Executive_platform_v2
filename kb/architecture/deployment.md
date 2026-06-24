---
title: Deployment
describes_files:
  - Dockerfile
  - Procfile
  - CLAUDE.md
derived_from_commit: 617a540
last_synced: 2026-06-24
---

# Deployment

**One codebase (`main` branch) → Railway is the live deploy target.**

```
GitHub main ──▶ Railway  (auto-rebuild on push)
```

- **Railway** is the live host (main backend + the sibling internal services). Code changes default to
  `main`; use a feature branch only for genuinely experimental work.
- **Azure App Service was decommissioned (2026-06-24)** — the old dual-track (Railway + Azure customer
  demo) is gone; only a free Bot Service (F0) + Key Vault remain. CLAUDE.md still documents the historical
  dual-track setup; treat Railway as the source of truth for where things run.
- Config adapts via env vars (`DATA_DIR` etc.); the OAuth app registration is shared.
- **Railway's `.data/` is ephemeral** — production needs a mounted volume or the data (incl. each
  user's `store.db`) resets on redeploy.
- A stale-image gotcha: a push can re-run a cached image; force a real rebuild by bumping the
  Dockerfile cache-bust token and verify the image digest changes.

## Sibling internal services (same repo, separate Railway services)
- **`ops-dashboard/`** — standalone fleet monitor (auth health, job health, push
  QA). Polls the main backend; its own deploy root.
- **`feedback-board/`** — the internal team's AI-Q&A + bug/feature request board.
  It consumes a read-only copy of this `kb/` and `src/skills/`. **Fully isolated**
  from the main program: separate service/process/deploy, never imports the main
  `src/`, never writes `.data/`.

## Common questions
- *"If I push, what redeploys?"* — Railway services on auto-deploy rebuild from
  `main` (main backend, ops-dashboard, feedback-board). Azure is manual.
