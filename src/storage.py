"""Concurrency-safe atomic file writes.

The deployment target (Azure Files SMB / Railway volume) plus multiple
APScheduler threads writing the same file caused "Extra data" JSON corruption
(the 2026-06 token-cache incident: a complete JSON object + 1 stray trailing
byte). The existing tmp+os.replace was not enough because the tmp filename was
SHARED (two writers of the same path collided on it) and read-modify-write was
not serialized. This module fixes both:

  1. UNIQUE tmp filename per write (pid + random) — two writers of the same
     path never share a tmp file.
  2. A per-path REENTRANT lock — a read-modify-write caller holds file_lock()
     around the whole load→modify→save cycle; the lock is reentrant so the
     inner atomic_write_*() can re-acquire it on the same thread.
"""
import json
import os
import secrets
import threading
from collections import defaultdict
from pathlib import Path

# RLock (reentrant): the same thread may hold the lock for an outer
# read-modify-write AND re-enter it inside atomic_write_text.
_locks: "defaultdict[str, threading.RLock]" = defaultdict(threading.RLock)


def _key(path) -> str:
    # Normalize to a stable absolute path string (no filesystem access, so it
    # works for not-yet-existing files like a fresh per-bot cache).
    return os.path.abspath(str(path))


def file_lock(path) -> threading.RLock:
    """Process-wide reentrant lock for a file path. Hold this around a full
    read-modify-write cycle so concurrent writers don't lose each other's
    updates (atomic_write_* alone prevents corruption, not lost updates)."""
    return _locks[_key(path)]


def atomic_write_text(path, text: str) -> None:
    """Atomically replace `path` with `text`. Unique tmp name + lock + replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)            # atomic on POSIX; moves tmp away
        except BaseException:
            tmp.unlink(missing_ok=True)      # only reached if write/replace failed
            raise


def atomic_write_json(path, data) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str))
