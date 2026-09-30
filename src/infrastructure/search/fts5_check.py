"""SQLite FTS5 availability check.

Called at application startup to fail fast with a clear message
if the Python build does not include the FTS5 extension.
"""

from __future__ import annotations

import sqlite3

from src.domain.exceptions import FTS5NotAvailableError


def verify_fts5() -> None:
    """Verify that SQLite FTS5 is available.

    Raises:
        FTS5NotAvailableError: If FTS5 is not compiled in.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(content)")
        conn.execute("DROP TABLE _fts5_test")
    except sqlite3.OperationalError as exc:
        raise FTS5NotAvailableError() from exc
    finally:
        conn.close()


def is_fts5_available() -> bool:
    """Return True if SQLite FTS5 is available, False otherwise."""
    try:
        verify_fts5()
        return True
    except FTS5NotAvailableError:
        return False
