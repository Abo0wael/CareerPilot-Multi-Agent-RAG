"""Pure scoring logic for turning chunk-level BM25 scores into job-level scores.

Lives in the domain because it is a business rule (how a job's relevance is
derived from its chunks) with no dependency on SQLite or any framework.
"""

from __future__ import annotations

from .entities import ScoredChunk


def aggregate_chunk_scores_by_job(
    scored_chunks: list[ScoredChunk],
    method: str = "max",
) -> list[tuple[int, float]]:
    """Aggregate chunk-level BM25 scores into overall job-level scores.

    A job posting can have multiple chunks matching search terms (e.g.
    one match in 'requirements' and another in 'responsibilities').
    This function groups chunks by `job_id` and computes a unified job score.

    Aggregation Methods:
        - "max" (Default & Recommended):
            Job score = MAX(chunk_score for chunk in job).
            Chosen because:
            1. Document length bias: SUM reintroduces length bias because longer
               job postings split into 8 chunks accumulate higher total scores than
               concise 2-chunk postings, defeating BM25's length normalization.
            2. Core qualification focus: Job postings describe many peripheral topics
               (benefits, team culture, company history). The single most relevant chunk
               (typically the core requirements) provides the purest signal of match.
            3. Average penalty avoidance: AVG would penalize a job with an exceptional
               100% requirements match if its intro or about chunk has a lower score.

        - "sum":
            Job score = SUM(chunk_scores).
            Trade-off: Penalizes concise postings; rewards verbose multi-section postings.

        - "avg":
            Job score = MEAN(chunk_scores).
            Trade-off: Dilutes strong signals from focused requirements sections.

    Trade-offs of MAX:
        - Discards cumulative evidence: A candidate who matches both 'requirements'
          AND 'responsibilities' receives the same score as someone matching only
          'requirements'. However, downstream LLM reranking (Phase 3) inspects the
          entire job description for top-N candidates anyway, making MAX an ideal,
          unbiased first-stage retriever.

    Args:
        scored_chunks: List of `ScoredChunk` instances from BM25 search.
        method: Aggregation strategy ("max", "sum", "avg"). Default "max".

    Returns:
        List of (job_id, aggregate_score) tuples sorted in descending score order.
    """
    if not scored_chunks:
        return []

    # Group scores by job_id
    job_scores: dict[int, list[float]] = {}
    for sc in scored_chunks:
        job_scores.setdefault(sc.chunk.job_id, []).append(sc.score)

    aggregated: list[tuple[int, float]] = []
    for job_id, scores in job_scores.items():
        if method == "max":
            agg = max(scores)
        elif method == "sum":
            agg = sum(scores)
        elif method == "avg":
            agg = sum(scores) / len(scores)
        else:
            raise ValueError(f"Unknown aggregation method: {method}. Use 'max', 'sum', or 'avg'.")
        aggregated.append((job_id, agg))

    # Sort descending by aggregate score
    aggregated.sort(key=lambda x: x[1], reverse=True)
    return aggregated




def fuse_weighted(
    primary: list[ScoredChunk],
    secondary: list[ScoredChunk],
    secondary_weight: float,
) -> list[ScoredChunk]:
    """Linearly fuse two BM25 result lists over the same index.

    ``score(chunk) = primary_score + secondary_weight * secondary_score``
    (a missing score counts as 0). Used to let LLM expansion terms add recall
    without outweighing the candidate's own terms (``secondary_weight < 1``).

    Returns:
        Fused chunks sorted by descending score.
    """
    fused: dict[str, ScoredChunk] = {sc.chunk_id: ScoredChunk(sc.chunk, sc.score) for sc in primary}
    for sc in secondary:
        weighted = secondary_weight * sc.score
        if sc.chunk_id in fused:
            fused[sc.chunk_id].score += weighted
        else:
            fused[sc.chunk_id] = ScoredChunk(sc.chunk, weighted)
    return sorted(fused.values(), key=lambda sc: sc.score, reverse=True)
