#!/usr/bin/env python3
"""kb/lint.py — staleness detector for the code knowledge base.

WHY this exists: the LLM-Wiki pattern assumes immutable sources. Our source is
code, which changes every commit, so a KB page can go *wrong*, not just
incomplete. Each page records the source files it describes (`describes_files`)
and the commit it was last reconciled against (`derived_from_commit`). This tool
asks git: "did any described file change since that commit?" If yes, the page is
STALE and a human/Claude must re-sync it.

No pip dependencies — stdlib + `git` only, so it runs anywhere (CI, pre-push).

Usage:
  python kb/lint.py                 # check every page; exit 1 if any stale
  python kb/lint.py --files a b ...  # inverse: which pages describe these files?
"""
import re
import subprocess
import sys
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent
REPO_ROOT = KB_DIR.parent
SKIP = {"index.md", "log.md", "KB_GUIDE.md", "README.md"}


def _git(*args: str) -> tuple[int, str]:
    """Run a git command at the repo root; return (exit_code, stdout)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip()


def parse_frontmatter(text: str) -> dict | None:
    """Parse the leading YAML frontmatter. Returns None if absent.

    Deliberately tiny — supports only the flat scalars and string lists this KB
    uses, in both block form (`key:` then `  - item`) and inline (`key: [a, b]`).
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end].strip("\n")

    data: dict = {}
    current_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # A block-list item belonging to the previous key.
        m_item = re.match(r"^\s+-\s+(.*)$", line)
        if m_item and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(m_item.group(1).strip().strip("'\""))
            continue
        # A `key: value` line.
        m_kv = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if not m_kv:
            continue
        key, val = m_kv.group(1), m_kv.group(2).strip()
        current_key = key
        if val == "":
            data[key] = []  # block list follows
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            data[key] = [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        else:
            data[key] = val.strip("'\"")
    return data


def kb_pages() -> list[Path]:
    pages = []
    for p in sorted(KB_DIR.rglob("*.md")):
        if p.name in SKIP:
            continue
        pages.append(p)
    return pages


def lint() -> int:
    pages = kb_pages()
    if not pages:
        print("no KB pages with frontmatter found under kb/")
        return 0

    stale_pages = 0
    warnings = 0
    for page in pages:
        rel = page.relative_to(REPO_ROOT)
        fm = parse_frontmatter(page.read_text(encoding="utf-8"))
        if fm is None:
            print(f"⚠️  {rel}: no frontmatter — skipping")
            warnings += 1
            continue

        commit = fm.get("derived_from_commit")
        described = fm.get("describes_files") or []
        if not commit:
            print(f"⚠️  {rel}: missing derived_from_commit")
            warnings += 1
            continue
        if not described:
            print(f"⚠️  {rel}: empty describes_files (page tracks nothing)")
            warnings += 1
            continue

        # Validate the base commit exists (a rebase can orphan it).
        rc, _ = _git("cat-file", "-e", f"{commit}^{{commit}}")
        if rc != 0:
            print(f"❌ STALE {rel}: derived_from_commit {commit} not found "
                  f"(rebased?) — re-sync and re-stamp")
            stale_pages += 1
            continue

        page_stale = False
        notes: list[str] = []
        for f in described:
            if not (REPO_ROOT / f).exists():
                notes.append(f"   ⚠️  described file missing on disk: {f}")
                page_stale = True
                continue
            rc, out = _git("log", "--oneline", f"{commit}..HEAD", "--", f)
            if rc != 0:
                notes.append(f"   ⚠️  git log failed for {f}")
                continue
            if out:
                n = len(out.splitlines())
                notes.append(f"   • {f} changed in {n} commit(s) since {commit}:")
                for cl in out.splitlines():
                    notes.append(f"       {cl}")
                page_stale = True

        if page_stale:
            stale_pages += 1
            print(f"❌ STALE {rel}")
            for line in notes:
                print(line)
        else:
            print(f"✅ FRESH {rel}")

    print()
    if stale_pages:
        print(f"{stale_pages} stale page(s). Re-sync them, bump "
              f"derived_from_commit/last_synced, and append a `sync` line to kb/log.md.")
        return 1
    print(f"All {len(pages)} page(s) fresh." + (f" ({warnings} warning(s))" if warnings else ""))
    return 0


def inverse(files: list[str]) -> int:
    """Given changed files, list which KB pages reference them."""
    targets = {f.lstrip("./") for f in files}
    hit = False
    for page in kb_pages():
        fm = parse_frontmatter(page.read_text(encoding="utf-8")) or {}
        described = set(fm.get("describes_files") or [])
        overlap = described & targets
        if overlap:
            hit = True
            rel = page.relative_to(REPO_ROOT)
            print(f"{rel}  ←  {', '.join(sorted(overlap))}")
    if not hit:
        print("No KB pages reference those files.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--files":
        sys.exit(inverse(sys.argv[2:]))
    sys.exit(lint())
