"""Tests for SQLite FTS5 search index, SQLiteJobRepository, and score aggregation.

Validates:
- FTS5 table and trigger initialization
- Chunks and postings persistence
- BM25 score negation (higher = better)
- Default search scope exclusion of Benefits/About while preserving unlabeled and core sections
- Metadata filtering (remote, experience level, location)
- Score aggregation by MAX (avoiding document length bias)
- SQLiteJobRepository read-side adherence to ISP
- IngestJobsUseCase orchestration
"""

from __future__ import annotations

from pathlib import Path
import pytest

from src.domain.entities import (
    IngestResult,
    ChunkSection,
    JobChunk,
    JobPosting,
    ScoredChunk,
    SearchQuery,
)
from src.domain.exceptions import IndexNotFoundError, JobNotFoundError
from src.domain.interfaces import JobRepository, JobSource, Retriever, SearchIndexWriter
from src.infrastructure.chunking.chunkers import ParagraphChunker
from src.domain.scoring import aggregate_chunk_scores_by_job
from src.infrastructure.search.sqlite_index import (
    SQLiteFTSIndex,
    SQLiteJobRepository,
)
from src.application.ingest_jobs import IngestJobsUseCase


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture providing a temporary SQLite database path."""
    return tmp_path / "test_careerpilot.db"


@pytest.fixture
def fts_index(temp_db: Path) -> SQLiteFTSIndex:
    """Fixture providing an initialized SQLiteFTSIndex."""
    index = SQLiteFTSIndex(temp_db)
    index.initialize()
    return index


def _sample_posting(job_id: int = 1, title: str = "Backend Engineer", **kwargs) -> JobPosting:
    defaults = {
        "job_id": job_id,
        "title": title,
        "company_name": "Acme Corp",
        "description": "We are seeking a Backend Engineer with Python and FastAPI skills.",
        "location": "San Francisco, CA",
        "formatted_work_type": "Full-time",
        "formatted_experience_level": "Mid-Senior level",
        "remote_allowed": True,
        "min_salary": 120000.0,
        "max_salary": 160000.0,
        "currency": "USD",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
    }
    defaults.update(kwargs)
    return JobPosting(**defaults)


def _sample_chunk(
    chunk_id: str,
    job_id: int,
    section: ChunkSection,
    text: str,
    **kwargs,
) -> JobChunk:
    defaults = {
        "chunk_id": chunk_id,
        "job_id": job_id,
        "section": section,
        "text": text,
        "title": "Backend Engineer",
        "company_name": "Acme Corp",
        "location": "San Francisco, CA",
        "formatted_experience_level": "Mid-Senior level",
        "formatted_work_type": "Full-time",
        "remote_allowed": True,
        "min_salary": 120000.0,
        "max_salary": 160000.0,
    }
    defaults.update(kwargs)
    return JobChunk(**defaults)


# ── SQLiteFTSIndex tests ─────────────────────────────────────────────

class TestSQLiteFTSIndex:
    """Tests for SQLiteFTSIndex read and write operations."""

    def test_implements_domain_interfaces(self, fts_index: SQLiteFTSIndex) -> None:
        assert isinstance(fts_index, SearchIndexWriter)
        assert isinstance(fts_index, Retriever)

    def test_add_and_search_chunks(self, fts_index: SQLiteFTSIndex) -> None:
        chunks = [
            _sample_chunk("1_req_0", 1, ChunkSection.REQUIREMENTS, "Must have deep Python and Docker experience."),
            _sample_chunk("2_req_0", 2, ChunkSection.REQUIREMENTS, "Must have Java and Spring experience."),
        ]
        inserted = fts_index.add_chunks(chunks)
        assert inserted == 2

        query = SearchQuery(raw_query="Python Docker")
        results = fts_index.search(query, top_n=10)

        assert len(results) == 1
        assert results[0].job_id == 1
        assert results[0].score > 0  # Negated from FTS5 negative score

    def test_score_is_positive_higher_better(self, fts_index: SQLiteFTSIndex) -> None:
        """FTS5 bm25() returns negative values; our index negates so higher is better."""
        chunks = [
            _sample_chunk("1_req_0", 1, ChunkSection.REQUIREMENTS, "Python Python Python expert with Python development."),
            _sample_chunk("2_req_0", 2, ChunkSection.REQUIREMENTS, "Basic Python knowledge."),
        ]
        fts_index.add_chunks(chunks)

        results = fts_index.search(SearchQuery(raw_query="Python"), top_n=10)
        assert len(results) == 2
        assert results[0].score > results[1].score
        assert results[0].job_id == 1

    def test_default_search_scope_excludes_benefits_and_about(self, fts_index: SQLiteFTSIndex) -> None:
        """Critical requirement 1: Only Benefits and About are excluded by default.
        Full fallback and Requirements remain searchable.
        """
        chunks = [
            _sample_chunk("1_ben_0", 1, ChunkSection.BENEFITS, "We offer excellent Python conference benefits and health coverage."),
            _sample_chunk("2_abt_0", 2, ChunkSection.ABOUT, "About Pythonic Solutions Inc, a leader in AI."),
            _sample_chunk("3_req_0", 3, ChunkSection.REQUIREMENTS, "Required: 5+ years of Python engineering."),
            _sample_chunk("4_full_0", 4, ChunkSection.FULL, "Unlabeled posting body describing Python backend architecture."),
            _sample_chunk("5_resp_0", 5, ChunkSection.RESPONSIBILITIES, "Lead Python system optimization."),
            _sample_chunk("6_nice_0", 6, ChunkSection.NICE_TO_HAVE, "Bonus: Python packaging experience."),
        ]
        fts_index.add_chunks(chunks)

        results = fts_index.search(SearchQuery(raw_query="Python"), top_n=10)
        matched_job_ids = {r.job_id for r in results}

        # Jobs 1 (Benefits) and 2 (About) must be excluded
        assert 1 not in matched_job_ids
        assert 2 not in matched_job_ids

        # Jobs 3 (Requirements), 4 (Full/Fallback), 5 (Responsibilities), 6 (Nice to have) must match
        assert {3, 4, 5, 6}.issubset(matched_job_ids)

    def test_explicit_sections_allow_list(self, fts_index: SQLiteFTSIndex) -> None:
        chunks = [
            _sample_chunk("1_req_0", 1, ChunkSection.REQUIREMENTS, "Python skills required."),
            _sample_chunk("2_resp_0", 2, ChunkSection.RESPONSIBILITIES, "Python development responsibilities."),
        ]
        fts_index.add_chunks(chunks)

        results = fts_index.search(
            SearchQuery(raw_query="Python"),
            sections=["requirements"],
        )
        assert len(results) == 1
        assert results[0].job_id == 1

    def test_explicit_excluded_sections_deny_list(self, fts_index: SQLiteFTSIndex) -> None:
        chunks = [
            _sample_chunk("1_ben_0", 1, ChunkSection.BENEFITS, "Free Python lunches every day."),
        ]
        fts_index.add_chunks(chunks)

        # Explicitly empty exclusion list allows all sections
        results = fts_index.search(
            SearchQuery(raw_query="Python"),
            excluded_sections=[],
        )
        assert len(results) == 1
        assert results[0].job_id == 1

    def test_metadata_filters(self, fts_index: SQLiteFTSIndex) -> None:
        chunks = [
            _sample_chunk("1_req_0", 1, ChunkSection.REQUIREMENTS, "Python developer", remote_allowed=True, location="Austin, TX"),
            _sample_chunk("2_req_0", 2, ChunkSection.REQUIREMENTS, "Python developer", remote_allowed=False, location="New York, NY"),
        ]
        fts_index.add_chunks(chunks)

        # Filter by remote
        query_remote = SearchQuery(raw_query="Python", filters={"remote_allowed": True})
        res_remote = fts_index.search(query_remote)
        assert len(res_remote) == 1
        assert res_remote[0].job_id == 1

        # Filter by location
        query_loc = SearchQuery(raw_query="Python", filters={"location": "New York"})
        res_loc = fts_index.search(query_loc)
        assert len(res_loc) == 1
        assert res_loc[0].job_id == 2

    def test_clear_removes_data(self, fts_index: SQLiteFTSIndex) -> None:
        chunks = [_sample_chunk("1_req_0", 1, ChunkSection.REQUIREMENTS, "Python developer")]
        fts_index.add_chunks(chunks)
        assert fts_index.get_chunk_stats()["total_chunks"] == 1

        fts_index.clear()
        assert fts_index.get_chunk_stats()["total_chunks"] == 0


# ── Score aggregation tests ──────────────────────────────────────────

class TestScoreAggregation:
    """Tests score aggregation by MAX to eliminate length bias."""

    def test_max_aggregation_selects_highest_chunk_score(self) -> None:
        # Job 1 has 3 chunks with different scores
        c1 = ScoredChunk(chunk=_sample_chunk("1_0", 1, ChunkSection.REQUIREMENTS, "text"), score=12.5)
        c2 = ScoredChunk(chunk=_sample_chunk("1_1", 1, ChunkSection.RESPONSIBILITIES, "text"), score=5.0)
        c3 = ScoredChunk(chunk=_sample_chunk("1_2", 1, ChunkSection.FULL, "text"), score=2.0)

        # Job 2 has 1 chunk with score 10.0
        c4 = ScoredChunk(chunk=_sample_chunk("2_0", 2, ChunkSection.REQUIREMENTS, "text"), score=10.0)

        aggregated = aggregate_chunk_scores_by_job([c1, c2, c3, c4], method="max")
        # Under MAX: Job 1 has 12.5, Job 2 has 10.0
        assert aggregated == [(1, 12.5), (2, 10.0)]

    def test_max_aggregation_avoids_length_bias(self) -> None:
        """Demonstrates that a verbose posting with 5 weak matches does NOT outrank
        a concise posting with 1 stellar match under MAX aggregation.
        """
        # Job A: concise job with 1 stellar match in requirements (score = 15.0)
        stellar = ScoredChunk(chunk=_sample_chunk("A_0", 100, ChunkSection.REQUIREMENTS, "text"), score=15.0)

        # Job B: long posting with 5 mediocre matches (score = 4.0 each, total sum = 20.0)
        mediocre_chunks = [
            ScoredChunk(chunk=_sample_chunk(f"B_{i}", 200, ChunkSection.FULL, f"text {i}"), score=4.0)
            for i in range(5)
        ]

        all_chunks = [stellar] + mediocre_chunks

        # Under SUM: Job B (20.0) artificially outranks Job A (15.0) due to length bias!
        sum_scores = dict(aggregate_chunk_scores_by_job(all_chunks, method="sum"))
        assert sum_scores[200] > sum_scores[100]

        # Under MAX: Job A (15.0) rightly outranks Job B (4.0)!
        max_scores = aggregate_chunk_scores_by_job(all_chunks, method="max")
        assert max_scores[0] == (100, 15.0)
        assert max_scores[1] == (200, 4.0)


# ── SQLiteJobRepository tests ────────────────────────────────────────

class TestSQLiteJobRepository:
    """Tests SQLiteJobRepository read-only access to full postings."""

    def test_get_by_id_and_not_found(self, temp_db: Path) -> None:
        index = SQLiteFTSIndex(temp_db)
        index.initialize()
        posting = _sample_posting(job_id=42, title="Staff ML Engineer")
        index.add_jobs([posting])

        repo = SQLiteJobRepository(temp_db)
        fetched = repo.get_by_id(42)
        assert fetched.job_id == 42
        assert fetched.title == "Staff ML Engineer"
        assert fetched.company_name == "Acme Corp"
        assert "Python" in fetched.skills

        with pytest.raises(JobNotFoundError):
            repo.get_by_id(999999)

    def test_get_by_ids_preserves_order(self, temp_db: Path) -> None:
        index = SQLiteFTSIndex(temp_db)
        index.initialize()
        p1 = _sample_posting(job_id=1, title="Job One")
        p2 = _sample_posting(job_id=2, title="Job Two")
        p3 = _sample_posting(job_id=3, title="Job Three")
        index.add_jobs([p1, p2, p3])

        repo = SQLiteJobRepository(temp_db)
        # Query in reverse order: [3, 1]
        results = repo.get_by_ids([3, 1])
        assert [r.job_id for r in results] == [3, 1]

    def test_index_not_found_raises_error(self, tmp_path: Path) -> None:
        non_existent_db = tmp_path / "does_not_exist.db"
        repo = SQLiteJobRepository(non_existent_db)
        with pytest.raises(IndexNotFoundError):
            repo.get_by_id(1)


# ── IngestJobsUseCase tests ──────────────────────────────────────────

class TestIngestJobsUseCase:
    """Tests IngestJobsUseCase orchestration."""

    def test_ingest_jobs_end_to_end(self, temp_db: Path) -> None:
        index = SQLiteFTSIndex(temp_db)
        index.initialize()
        postings = [
            _sample_posting(job_id=1, description="Short description for job 1."),
            _sample_posting(job_id=2, description="Short description for job 2."),
        ]
        use_case = IngestJobsUseCase(
            job_source=_ListJobSource(postings),
            chunker=ParagraphChunker(max_length=500, overlap=20),
            index_writer=index,
        )

        result = use_case.execute(clear_existing=True)

        assert result == IngestResult(jobs_ingested=2, chunks_indexed=2)
        # Parent documents must be stored too, or every later job lookup fails.
        assert SQLiteJobRepository(temp_db).get_by_id(2).job_id == 2
        stats = index.get_stats()
        assert (stats.total_jobs, stats.total_chunks) == (2, 2)

    def test_clear_existing_false_keeps_previous_jobs(self, temp_db: Path) -> None:
        index = SQLiteFTSIndex(temp_db)
        index.initialize()
        index.add_jobs([_sample_posting(job_id=99)])
        use_case = IngestJobsUseCase(
            job_source=_ListJobSource([_sample_posting(job_id=1)]),
            chunker=ParagraphChunker(),
            index_writer=index,
        )
        use_case.execute(clear_existing=False)
        assert index.get_stats().total_jobs == 2


class _ListJobSource(JobSource):
    def __init__(self, postings: list[JobPosting]) -> None:
        self._postings = postings

    def load_postings(self) -> list[JobPosting]:
        return self._postings


def test_connections_can_be_used_and_closed_from_other_threads(temp_db: Path) -> None:
    """FastAPI serves sync endpoints on worker threads and closes resources on another thread."""
    import threading

    index = SQLiteFTSIndex(temp_db)
    index.initialize()
    repo = SQLiteJobRepository(temp_db)
    errors: list[BaseException] = []

    def use_from_worker() -> None:
        try:
            index.get_stats()
            repo.get_by_ids([1])
        except BaseException as err:  # noqa: BLE001 - collected and asserted below
            errors.append(err)

    worker = threading.Thread(target=use_from_worker)
    worker.start()
    worker.join()
    index.close()
    repo.close()
    assert errors == []
