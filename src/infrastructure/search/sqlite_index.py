"""SQLite FTS5 search index and job repository.

Implements ``SearchIndexWriter``, ``Retriever``, and ``JobRepository``
from the domain layer using SQLite with the FTS5 extension.

Score aggregation uses MAX (not SUM) to avoid reintroducing length bias.
FTS5 ``bm25()`` returns negative values where lower (more negative) is better;
we negate scores so higher is better in our domain model.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from src.domain.entities import (
    ChunkSection,
    IndexStats,
    JobChunk,
    JobPosting,
    ScoredChunk,
    SearchQuery,
)
from src.domain.exceptions import (
    IndexNotFoundError,
    JobNotFoundError,
)
from src.domain.interfaces import IndexStatsReader, JobRepository, Retriever, SearchIndexWriter
from src.infrastructure.search.fts5_check import is_fts5_available

logger = logging.getLogger(__name__)

# ── Schema ──────────────────────────────────────────────────────────

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            INTEGER PRIMARY KEY,
    title             TEXT NOT NULL,
    company_name      TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL,
    location          TEXT NOT NULL DEFAULT '',
    formatted_work_type TEXT NOT NULL DEFAULT '',
    formatted_experience_level TEXT NOT NULL DEFAULT '',
    remote_allowed    INTEGER NOT NULL DEFAULT 0,
    min_salary        REAL,
    max_salary        REAL,
    currency          TEXT NOT NULL DEFAULT '',
    skills            TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_CHUNKS_TABLE = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          TEXT PRIMARY KEY,
    job_id            INTEGER NOT NULL,
    section           TEXT NOT NULL,
    text              TEXT NOT NULL,
    title             TEXT NOT NULL DEFAULT '',
    company_name      TEXT NOT NULL DEFAULT '',
    location          TEXT NOT NULL DEFAULT '',
    formatted_experience_level TEXT NOT NULL DEFAULT '',
    formatted_work_type TEXT NOT NULL DEFAULT '',
    remote_allowed    INTEGER NOT NULL DEFAULT 0,
    min_salary        REAL,
    max_salary         REAL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id)
);
"""

_CREATE_FTS_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    content='chunks',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

_CREATE_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
END;
"""


class SQLiteFTSIndex(SearchIndexWriter, Retriever, IndexStatsReader):
    """SQLite FTS5-based search index.

    Implements both ``SearchIndexWriter`` (write) and ``Retriever`` (read).
    While both interfaces are implemented in one class for convenience,
    consumers receive only the interface they need (ISP).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connection management ────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Lazy-init connection with WAL mode for concurrent reads."""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            # FastAPI runs sync endpoints on worker threads; the sqlite3 module is built
            # in serialized mode (threadsafety == 3), so one shared connection is safe.
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def initialize(self) -> None:
        """Create schema if it does not exist."""
        conn = self._get_conn()
        conn.executescript(_CREATE_JOBS_TABLE)
        conn.executescript(_CREATE_CHUNKS_TABLE)
        conn.executescript(_CREATE_FTS_TABLE)
        conn.executescript(_CREATE_FTS_TRIGGERS)
        conn.commit()
        logger.info("Index schema initialized at %s", self._db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── SearchIndexWriter ────────────────────────────────────────────

    def add_chunks(self, chunks: list[JobChunk]) -> int:
        """Insert chunks into the index. Returns count of inserted chunks."""
        conn = self._get_conn()
        inserted = 0
        for chunk in chunks:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO chunks
                       (chunk_id, job_id, section, text, title, company_name,
                        location, formatted_experience_level, formatted_work_type,
                        remote_allowed, min_salary, max_salary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk.chunk_id,
                        chunk.job_id,
                        chunk.section.value,
                        chunk.text,
                        chunk.title,
                        chunk.company_name,
                        chunk.location,
                        chunk.formatted_experience_level,
                        chunk.formatted_work_type,
                        int(chunk.remote_allowed),
                        chunk.min_salary,
                        chunk.max_salary,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # duplicate chunk_id, skip
        conn.commit()
        return inserted

    def add_jobs(self, postings: list[JobPosting]) -> int:
        """Insert full job postings for parent-document retrieval."""
        conn = self._get_conn()
        inserted = 0
        for p in postings:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (job_id, title, company_name, description, location,
                        formatted_work_type, formatted_experience_level,
                        remote_allowed, min_salary, max_salary, currency, skills)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        p.job_id, p.title, p.company_name, p.description,
                        p.location, p.formatted_work_type,
                        p.formatted_experience_level,
                        int(p.remote_allowed), p.min_salary, p.max_salary,
                        p.currency, ",".join(p.skills),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        return inserted

    def clear(self) -> None:
        """Remove all data from the index."""
        conn = self._get_conn()
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM jobs")
        conn.commit()
        logger.info("Index cleared.")

    # ── Retriever ────────────────────────────────────────────────────

    def search(
        self,
        query: SearchQuery,
        top_n: int = 50,
        sections: Optional[list[str]] = None,
        excluded_sections: Optional[list[str]] = None,
    ) -> list[ScoredChunk]:
        """BM25 search over indexed chunks.

        Args:
            query: Search query with optional expanded terms.
            top_n: Maximum results.
            sections: If provided, restrict strictly to these section types (allow-list).
            excluded_sections: If provided, exclude these section types (deny-list).
                If neither `sections` nor `excluded_sections` is provided, defaults to
                excluding ['benefits', 'about'] so that Requirements, Responsibilities,
                Nice-to-Have, and unlabeled/fallback chunks ('full') remain searchable.

        Returns:
            Scored chunks sorted by descending relevance (higher = better).

        Note on FTS5 scoring:
            ``bm25()`` returns negative values where *lower* is better.
            We negate the score so that *higher* is better in our domain.
        """
        conn = self._get_conn()

        # Build FTS5 query: combine raw query with expanded terms
        tokens: list[str] = []
        for word in _clean_fts_query(query.raw_query).split():
            if word and word.upper() not in ("AND", "OR", "NOT") and len(word) > 1:
                tokens.append(word)

        if query.expanded_terms:
            for term in query.expanded_terms:
                for word in _clean_fts_query(term).split():
                    if word and word.upper() not in ("AND", "OR", "NOT") and len(word) > 1:
                        if word not in tokens:
                            tokens.append(word)

        fts_query = " OR ".join(tokens)
        if not fts_query:
            return []

        # Build SQL with section filtering
        sql = """
            SELECT c.*, -bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
        """
        params: list = [fts_query]

        if sections:
            placeholders = ",".join("?" for _ in sections)
            sql += f" AND c.section IN ({placeholders})"
            params.extend(sections)
        elif excluded_sections is not None:
            if excluded_sections:
                placeholders = ",".join("?" for _ in excluded_sections)
                sql += f" AND c.section NOT IN ({placeholders})"
                params.extend(excluded_sections)
        else:
            # Default search scope: exclude only positively-labeled Benefits and About.
            # Paragraph fallback ('full') and unlabeled text before headers remain searchable.
            default_excluded = ["benefits", "about"]
            placeholders = ",".join("?" for _ in default_excluded)
            sql += f" AND c.section NOT IN ({placeholders})"
            params.extend(default_excluded)

        # Apply metadata filters from query
        for key, value in query.filters.items():
            if key == "remote_allowed":
                sql += " AND c.remote_allowed = ?"
                params.append(int(value))
            elif key == "formatted_experience_level" and value:
                sql += " AND c.formatted_experience_level = ?"
                params.append(value)
            elif key == "location" and value:
                sql += " AND c.location LIKE ?"
                params.append(f"%{value}%")

        sql += " ORDER BY score DESC LIMIT ?"
        params.append(top_n)

        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 query error: %s (query=%s)", e, fts_query)
            return []

        results: list[ScoredChunk] = []
        for row in rows:
            chunk = JobChunk(
                chunk_id=row["chunk_id"],
                job_id=row["job_id"],
                section=ChunkSection(row["section"]),
                text=row["text"],
                title=row["title"],
                company_name=row["company_name"],
                location=row["location"],
                formatted_experience_level=row["formatted_experience_level"],
                formatted_work_type=row["formatted_work_type"],
                remote_allowed=bool(row["remote_allowed"]),
                min_salary=row["min_salary"],
                max_salary=row["max_salary"],
            )
            results.append(ScoredChunk(chunk=chunk, score=row["score"]))

        return results

    def get_stats(self) -> IndexStats:
        """Return job/chunk counts and FTS5 availability (``IndexStatsReader``)."""
        conn = self._get_conn()
        return IndexStats(
            total_jobs=conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            total_chunks=conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            fts5_available=is_fts5_available(),
        )

    def vacuum(self) -> None:
        """Compact the database file after a rebuild."""
        self._get_conn().execute("VACUUM")

    def get_chunk_stats(self, max_length: int = 800) -> dict:
        """Return index statistics for reporting."""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if total == 0:
            return {
                "total_chunks": 0,
                "chunks_above_max": 0,
                "pct_above_max": 0.0,
                "by_section": [],
            }

        above_max = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE LENGTH(text) > ?", (max_length,)
        ).fetchone()[0]

        by_section = conn.execute(
            "SELECT section, COUNT(*), AVG(LENGTH(text)), "
            "MIN(LENGTH(text)), MAX(LENGTH(text)), "
            "SUM(CASE WHEN LENGTH(text) > ? THEN 1 ELSE 0 END) "
            "FROM chunks GROUP BY section",
            (max_length,),
        ).fetchall()
        return {
            "total_chunks": total,
            "chunks_above_max": above_max,
            "pct_above_max": round(100.0 * above_max / total, 2),
            "by_section": [
                {
                    "section": row[0],
                    "count": row[1],
                    "avg_length": round(row[2], 1),
                    "min_length": row[3],
                    "max_length": row[4],
                    "above_max": row[5],
                }
                for row in by_section
            ],
        }


class SQLiteJobRepository(JobRepository):
    """Read-only job repository backed by the SQLite index.

    Separate from ``SQLiteFTSIndex`` to respect Interface Segregation:
    agents/use-cases receive only the read interface they need.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._db_path.exists():
                raise IndexNotFoundError(
                    f"Index not found at {self._db_path}. Run build_index.py first."
                )
            # FastAPI runs sync endpoints on worker threads; the sqlite3 module is built
            # in serialized mode (threadsafety == 3), so one shared connection is safe.
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def get_by_id(self, job_id: int) -> JobPosting:
        """Return the full ``JobPosting`` for *job_id*."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return self._row_to_posting(row)

    def get_by_ids(self, job_ids: list[int]) -> list[JobPosting]:
        """Return ``JobPosting`` objects for the given IDs."""
        if not job_ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in job_ids)
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE job_id IN ({placeholders})", job_ids
        ).fetchall()

        # Preserve order
        row_map = {row["job_id"]: row for row in rows}
        return [self._row_to_posting(row_map[jid]) for jid in job_ids if jid in row_map]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_posting(row: sqlite3.Row) -> JobPosting:
        skills_str = row["skills"] if row["skills"] else ""
        return JobPosting(
            job_id=row["job_id"],
            title=row["title"],
            company_name=row["company_name"],
            description=row["description"],
            location=row["location"],
            formatted_work_type=row["formatted_work_type"],
            formatted_experience_level=row["formatted_experience_level"],
            remote_allowed=bool(row["remote_allowed"]),
            min_salary=row["min_salary"],
            max_salary=row["max_salary"],
            currency=row["currency"],
            skills=[s.strip() for s in skills_str.split(",") if s.strip()],
        )


# ── Helpers ─────────────────────────────────────────────────────────

def _clean_fts_query(text: str) -> str:
    """Remove characters that break FTS5 query syntax."""
    # Keep alphanumeric, spaces, and basic operators
    cleaned = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
