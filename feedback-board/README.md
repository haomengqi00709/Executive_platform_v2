# feedback-board

Internal-team AI Q&A + bug/feature/optimization request board. A standalone
FastAPI service (mirrors `ops-dashboard/`), deployed as its own Railway service.

## What it does

1. **Ask about the platform** — an AI chat grounded in the code knowledge base
   (`kb/`). The team self-serves "can it do X / what does section Y do / what's the
   current prompt for Z" instead of pinging the founder.
2. **Report a request** — bug / feature / optimization, each gets a `REQ-N` with a
   status (`new → in_progress → done`).
3. **Auto-close on push** — push a commit whose message mentions `REQ-7` and the
   GitHub webhook flips REQ-7 to `done`. The team never touches GitHub; only the
   developer pushes.

## Isolation (zero impact on the main program)

Separate service, process, and deploy. It **does not import the main `src/`** and
**never writes the main app's `.data/`**. At build time it bakes in a **read-only
copy** of `kb/` and `src/skills/`. If it crashes, the platform is unaffected.

## Chat: three-layer context (`kb_loader.py`)

| Question | Answered from |
|---|---|
| "Can it do X / what does section Y do?" | the frozen KB pages in `kb/` |
| "What's the current prompt for section X?" | the **live** `src/skills/{X}/skill.md`, quoted verbatim |
| "What are the known issues / open requests?" | the **live** `data/requests.json` |

Volatile facts (prompt text, bug status) are never frozen into KB prose — they're
surfaced live so the chat can't be confidently wrong. The system prompt forbids
inventing capabilities/prompts/bugs; uncovered questions get "not documented — file
a request".

## Auth (two tiers, HTTP Basic)

- **Team** — shared `TEAM_PASSWORD` (any username): open the page, chat, list/submit
  requests.
- **Admin** — `ADMIN_USER` / `ADMIN_PASSWORD`: change request status.
- **Webhook** — GitHub `X-Hub-Signature-256` HMAC against `GITHUB_WEBHOOK_SECRET`
  (not Basic — GitHub can't send it).

## Routes

| Path | Auth | Purpose |
|---|---|---|
| `GET /` | team | board + chat UI |
| `GET /health` | none | healthcheck |
| `GET /api/requests` | team | list requests |
| `POST /api/requests` | team | create a request |
| `POST /api/requests/{id}/status` | admin | change status |
| `POST /api/chat` | team | KB-grounded Q&A |
| `POST /webhook/github` | HMAC | push → auto-close `REQ-N` |

## Local dev

```bash
cd feedback-board
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in TEAM_PASSWORD, ADMIN_*, GEMINI_API_KEY, GITHUB_WEBHOOK_SECRET
DATA_DIR=./data uvicorn src.main:app --reload --port 8099
```
In local dev `kb_loader` reads `../kb` and `../src/skills` automatically (the repo
copies); in Docker it reads the baked-in `./kb` and `./skills`.

## Deploy (Railway)

The Dockerfile's build context **must be the repo root** so it can copy `kb/` +
`src/skills/` in (fresh on every push):

1. New Railway service in the same project, connect the GitHub repo.
2. **Root Directory = repo root**, **Dockerfile path = `feedback-board/Dockerfile`**.
   *(If Railway can't set the build root to repo root, fall back to a pre-build copy
   script — see plan "办法二".)*
3. Set env vars from `.env.example` (`TEAM_PASSWORD`, `ADMIN_USER`,
   `ADMIN_PASSWORD`, `GEMINI_API_KEY`, optional `GEMINI_MODEL`,
   `GITHUB_WEBHOOK_SECRET`, `DATA_DIR=/data`).
4. **Mount a volume at `/data`** — otherwise `requests.json` resets on every
   redeploy (same trap as ops-dashboard).
5. Generate a domain.
6. GitHub repo → **Settings → Webhooks** → add `https://<domain>/webhook/github`,
   content type `application/json`, secret = `GITHUB_WEBHOOK_SECRET`, event = "Just
   the push event".

## Keeping the KB fresh

The chat is only as accurate as `kb/`. After changing a section's behavior, update
its `kb/capabilities/*.md` page and run `python kb/lint.py` before pushing — see the
repo `CLAUDE.md` and `kb/KB_GUIDE.md`.
