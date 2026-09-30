"""Tests for FTS5 availability check."""

from __future__ import annotations

from src.infrastructure.search.fts5_check import verify_fts5


class TestFTS5Check:
    """Verify FTS5 check passes on this Python build."""

    def test_fts5_available(self) -> None:
        # Should not raise
        verify_fts5()
