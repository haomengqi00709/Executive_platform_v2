---
title: Deployment
describes_files:
  - Dockerfile
  - Procfile
  - CLAUDE.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
---

# Deployment

**One codebase (`main` branch), two deploy targets; differences live in config, not
code.**

```
GitHub main
  ├──▶ Railway  (internal testing / auto-rebuild on push)
  └──▶ Azure App Service  (customer demo / manual `az acr build`)
```

- Code changes default to `main`; both platforms benefit. Use a feature branch only
  for genuinely experimental work that could break the other side.
- Platform differences (config only): `DATA_DIR` (`.data` vs `/mnt/data`), volume
  source (Railway volume vs Azure Files), image source, port injection, shared OAuth
  app registration with both redirect URIs listed.
- **Railway's `.data/` is ephemeral** — production needs a mounted volume or the
  data resets on redeploy.

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
