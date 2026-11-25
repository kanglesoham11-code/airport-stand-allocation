"""Database connections (section 23.48).

db.py only opens connections and sets their options. All SQL text lives in
repository.py. Every connection uses its own short-lived handle; none is shared
between threads.
"""

from __future__ import annotations

import sqlite3

from stand_allocation import config


def connect(path) -> sqlite3.Connection:
    """Open a read/write connection with the standard options."""
    conn = sqlite3.connect(
        path,
        timeout=config.SQLITE_BUSY_TIMEOUT_MS / config.MS_PER_SECOND,
        isolation_level=None,  # autocommit; transactions are managed explicitly
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {config.SQLITE_BUSY_TIMEOUT_MS}")
    return conn
