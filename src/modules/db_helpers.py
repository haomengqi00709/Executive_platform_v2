"""SQLite helpers that are safe over network filesystems (Azure Files SMB).

Default SQLite journal mode is DELETE, which relies on file locks.
SMB file locks are unreliable (delays, retry gaps) and the bot polling loop
+ HTTP request handlers concurrently writing to bot_history.db / bot.sqlite
will eventually trigger "database disk image is malformed" without WAL mode.

WAL keeps the journal in a separate .db-wal file and tolerates SMB much better.
"""
import sqlite3
from pathlib import Path


def open_sqlite(path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection with SMB-safe settings.

    - WAL mode: writers don't block readers; .db-wal file used instead of locks
    - busy_timeout: retry for up to 10s on transient lock contention
    - timeout=10.0: also covers the connect() call
    """
    con = sqlite3.connect(str(path), timeout=10.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=10000")
    return con
