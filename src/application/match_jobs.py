"""Match Jobs use case.

Orchestrates query building, expansion, retrieval, aggregation, and reranking
to find the top-K matching jobs for a candidate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from src.domain.entities import CandidateProfile, JobMatch, ScoredChunk, SearchQuery
from src.domain.scoring import aggregate_chunk_scores_by_job, fuse_weighted

if TYPE_CHECKING:
    from src.domain.interfaces import JobRepository, QueryExpander, Reranker, Retriever

logger = logging.getLogger(__name__)


def _extract_query_terms(profile: CandidateProfile, preferences: str) -> str:
    """Build a search string from candidate skills, target role, and user preferences."""
    terms: list[str] = []
    if preferences.strip():
        terms.append(preferences.strip())

    # Add top technical skills
    if profile.skills:
        terms.extend(profile.skills[:5])

    # If still empty, pull words from headline/summary
    if not terms and profile.raw_text:
        lines = [line.strip() for line in profile.raw_text.split("\n") if line.strip()]
        if lines:
            terms.append(lines[0][:100])

    return " ".join(terms).strip() or "software engineer"


def _extract_filters(preferences: str) -> dict[str, str | bool]:
    """Extract metadata filters from preferences text."""
    filters: dict[str, str | bool] = {}
    pref_lower = preferences.lower()

    if "remote" in pref_lower:
        filters["remote_allowed"] = True

    for level in ["Internship", "Entry level", "Mid-Senior level", "Director", "Executive"]:
        if level.lower() in pref_lower:
            filters["formatted_experience_level"] = level
            break

    return filters


class MatchJobsUseCase:
    """Find top-K matching jobs for a candidate profile + preferences.

    Single Responsibility: orchestrating the retrieval pipeline.
    Dependency Inversion: depends on domain ABCs only.
    """

    def __init__(
        self,
        retriever: Retriever,
        query_expander: QueryExpander,
        reranker: Reranker,
        job_repository: JobRepository,
        top_n: int = 50,
        top_k: int = 10,
        expansion_weight: Optional[float] = None,
    ) -> None:
        """
        Args:
            expansion_weight: ``None`` ORs expansion terms into one BM25 query (all terms equal).
                A float ``w`` runs two BM25 queries (candidate terms, expansion terms) and fuses
                them as ``score = original + w * expansion``, so expansion adds recall without
                outweighing the candidate's own terms.
        """
        self._retriever = retriever
        self._query_expander = query_expander
        self._reranker = reranker
        self._job_repo = job_repository
        self._top_n = top_n
        self._top_k = top_k
        self._expansion_weight = expansion_weight

    def _retrieve(self, query: SearchQuery) -> list[ScoredChunk]:
        if self._expansion_weight is None or not query.expanded_terms:
            return self._retriever.search(query=query, top_n=self._top_n)
        original = SearchQuery(raw_query=query.raw_query, filters=query.filters)
        expansion = SearchQuery(raw_query=" ".join(query.expanded_terms), filters=query.filters)
        return fuse_weighted(
            self._retriever.search(query=original, top_n=self._top_n),
            self._retriever.search(query=expansion, top_n=self._top_n),
            self._expansion_weight,
        )

    def execute(
        self,
        profile: CandidateProfile,
        preferences: str = "",
        top_k: Optional[int] = None,
    ) -> list[JobMatch]:
        """Find and rank the best jobs for *profile* with given *preferences*.

        Pipeline:
        1. Form query & filters from candidate profile + preferences.
        2. Expand query using ``QueryExpander``.
        3. Retrieve BM25 chunks using ``Retriever`` (excluding Benefits/About).
        4. Aggregate chunk scores per job using MAX (preventing length bias).
        5. Fetch full parent documents via ``JobRepository``.
        6. Rerank using ``Reranker`` (Groq fast model) to produce grounded reasons.
        7. Return top-K ``JobMatch`` instances.
        """
        raw_query = _extract_query_terms(profile, preferences)
        filters = _extract_filters(preferences)

        initial_query = SearchQuery(raw_query=raw_query, filters=filters)
        logger.info("Matching jobs with initial query: '%s', filters=%s", raw_query, filters)

        # 1. Query expansion
        expanded_query = self._query_expander.expand(initial_query)

        # 2. BM25 retrieval
        scored_chunks = self._retrieve(expanded_query)
        if not scored_chunks:
            logger.warning("No chunks matched search query.")
            return []

        # 3. Score aggregation by MAX per job
        job_scores = aggregate_chunk_scores_by_job(scored_chunks, method="max")
        top_job_ids = [jid for jid, _ in job_scores[: self._top_n]]

        # 4. Parent-document retrieval
        postings = self._job_repo.get_by_ids(top_job_ids)
        score_map = dict(job_scores)

        initial_matches = [
            JobMatch(
                job=p,
                score=score_map.get(p.job_id, 0.0),
                reason=f"BM25 lexical match for {p.title}",
            )
            for p in postings
        ]

        # 5. LLM Reranking with grounded rationales
        k = top_k or self._top_k
        reranked_matches = self._reranker.rerank(
            profile=profile,
            matches=initial_matches,
            top_k=k,
        )

        logger.info("Match pipeline complete. Returning %d matches.", len(reranked_matches))
        return reranked_matches
