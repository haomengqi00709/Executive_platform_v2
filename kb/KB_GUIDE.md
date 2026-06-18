# KB_GUIDE — how this knowledge base works

> Read this first. It tells a future Claude Code session (and any human) the
> conventions of `kb/` and the workflows for keeping it correct. You and the LLM
> co-evolve this file as the domain teaches you what works.

## 1. Purpose & non-goals

**Purpose.** `kb/` is a distilled, LLM-maintained description of *what the CEO
platform does and how it's structured*, so the internal team can self-serve
answers ("can it do X? / what does section Y do? / how does Z work?") instead of
pinging the founder. It powers the `feedback-board` service's AI chat.

**Non-goals — do NOT:**
- ❌ Call this a "wiki". `wiki` is reserved for the meeting database
  (`src/modules/wiki.py`, a JSON store). This is the **KB**.
- ❌ Copy `skill.md` prompt text into pages. Prompts are volatile and surfaced
  *live* (see §6). Pages describe *behavior*, not prompt internals.
- ❌ Build embeddings / vector search. At ~17 sections, `index.md` is the router.
- ❌ Store per-user data here. The KB is **repo-wide**, lives in git, describes
  the shared codebase. It is never under `.data/{user_id}/`.

## 2. The mutable-source rule (the core adaptation)

The "LLM Wiki" pattern assumes **immutable** sources (articles, papers) that only
accumulate. Our source is **code, which changes every commit** — so a KB page can
become *wrong*, not merely incomplete. That is the one failure mode that destroys
this KB's value: a confident page describing code that no longer exists → the team
gets wrong answers → files wrong requests.

Defense = provenance + lint:
- Every page records `describes_files` (the sources whose behavior it summarizes)
  and `derived_from_commit` (the commit it was last reconciled against).
- `python kb/lint.py` asks git whether any described file changed since that
  commit. Changed ⇒ STALE ⇒ a human/Claude must re-sync the page.

**AI-boundary rule (mirrors the main CLAUDE.md):** pages state *what a capability
does*; they never freeze volatile facts — exact current prompt text, current known
bugs, live counts. Those are surfaced from their live source (§6).

## 3. Directory & file conventions

```
kb/
  KB_GUIDE.md            # this file
  index.md               # catalog: every page, one-line summary, link (the router)
  log.md                 # append-only changelog
  lint.py                # staleness detector (stdlib + git only)
  capabilities/*.md      # one page per user-facing capability cluster
  architecture/*.md      # one page per cross-cutting system concern
```

Granularity = **capability cluster, not one-page-per-section** (a per-section page
would just restate the `skill.md` we surface live). Group related sections
(e.g. `email-triage.md` = reply_needed + followup_needed).

**`index.md`** is a flat catalog the chat loads whole. One bullet per page:
`- [title](path) — one-line summary.` Update it on every ingest.

**`log.md`** is append-only, newest at the bottom, one line per event with a fixed,
greppable header grammar:
```
## [YYYY-MM-DD] ingest|sync|lint | <title> @<short-sha>
```
`grep '^## \[' kb/log.md | tail -5` gives the recent history.

## 4. Frontmatter spec

Every page under `capabilities/` and `architecture/` starts with:
```yaml
---
title: Email Triage
describes_files:
  - src/sections/reply_needed.py
  - src/skills/reply_needed/skill.md
derived_from_commit: 46c63d6
last_synced: 2026-06-15
volatile_pointers:
  - src/skills/reply_needed/skill.md
---
```
- `describes_files` — the source files whose *behavior* this page summarizes. The
  lint signal. List the runner/logic files AND the skill/validator docs.
- `derived_from_commit` — short SHA the page was last reconciled against. **Every
  commit that edits a `describes_files` source obligates a sync of this page.**
- `last_synced` — human date of last reconciliation.
- `volatile_pointers` (optional) — files the chat serves *raw* rather than trusting
  the page's prose (the `skill.md` prompts). Documents the AI-boundary contract.

## 5. Workflows (the four verbs)

- **ingest** — create a page from a curated doc / code reading. Stamp
  `derived_from_commit=$(git rev-parse --short HEAD)`, add a bullet to `index.md`,
  append an `ingest` line to `log.md`.
- **query** — how the chat answers (the feedback-board does this): load `index.md`
  + relevant pages; for prompt questions inject the live `skill.md`; for
  known-issue questions inject live `requests.json`. Answer ONLY from context;
  if uncovered, say "not documented" and offer to file a request.
- **sync** — after changing a section's behavior/prompt, edit its capability page,
  bump `derived_from_commit` + `last_synced`, append a `sync` line to `log.md`.
- **lint** — run `python kb/lint.py`. For each stale page, either re-sync the prose
  or, if the change was non-behavioral, just bump the commit with a `lint` note.
  Inverse lookup: `python kb/lint.py --files <changed files>` lists affected pages.

## 6. Volatile vs frozen — what lives where

| Question type | Answered from | Frozen in KB? |
|---|---|---|
| "Can the platform do X / what does section Y do?" | KB capability pages | ✅ yes |
| "What's the current prompt for section X?" | raw `src/skills/{X}/skill.md` (live) | ❌ never paraphrase |
| "What are the known issues / open requests?" | feedback-board `data/requests.json` (live) | ❌ live registry |

## 7. Definition of done for a KB edit

- Page body accurate and describes behavior (not prompt text / live facts).
- Frontmatter `describes_files` complete; `derived_from_commit` + `last_synced` bumped.
- `index.md` summary still correct.
- `kb/log.md` appended.
- `python kb/lint.py` exits clean.
