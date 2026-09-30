"""Build the SQLite FTS5 search index from the tech subset.

Composition root: instantiates concrete classes and wires dependencies.
No LLM calls are made during index building.

Usage:
    python scripts/build_index.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# UTF-8 logging (fix #7: Windows cp1252 errors)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(
            stream=open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
        )
    ],
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Build the index end-to-end through the same use case as POST /ingest."""
    from src.application.ingest_jobs import IngestJobsUseCase
    from src.infrastructure.chunking.chunkers import ChunkerFactory
    from src.infrastructure.config import get_settings
    from src.infrastructure.data.loader import KaggleDataLoader
    from src.infrastructure.search.fts5_check import verify_fts5
    from src.infrastructure.search.sqlite_index import SQLiteFTSIndex

    verify_fts5()
    settings = get_settings()
    logger.info("Index will be written to: %s", settings.index_path)

    index = SQLiteFTSIndex(settings.index_path)
    index.initialize()
    chunker = ChunkerFactory().create(
        "composite",
        max_length=settings.paragraph_chunk_max_length,
        min_length=settings.chunk_min_length,
        overlap=settings.paragraph_chunk_overlap,
    )
    use_case = IngestJobsUseCase(job_source=KaggleDataLoader(settings), chunker=chunker, index_writer=index)

    t0 = time.perf_counter()
    result = use_case.execute(clear_existing=True)
    elapsed = time.perf_counter() - t0

    stats = index.get_chunk_stats(max_length=settings.paragraph_chunk_max_length)
    logger.info("=" * 70)
    logger.info("INDEX BUILD COMPLETE")
    logger.info("  Postings: %d", result.jobs_ingested)
    logger.info("  Total chunks: %d", stats["total_chunks"])
    logger.info("  Chunks > %d chars: %d (%.2f%%)", settings.paragraph_chunk_max_length, stats["chunks_above_max"], stats["pct_above_max"])
    logger.info("  Build time: %.1f seconds", elapsed)
    logger.info("  Chunks per section:")
    for s in stats["by_section"]:
        logger.info(
            "    %-20s: %6d chunks  (avg=%4.0f chars, min=%d, max=%d, >%d: %d)",
            s["section"], s["count"], s["avg_length"],
            s["min_length"], s["max_length"],
            settings.paragraph_chunk_max_length, s["above_max"],
        )
    index.vacuum()
    logger.info("  Index file size (compacted): %.1f MB", settings.index_path.stat().st_size / 1e6)
    logger.info("=" * 70)
    index.close()


if __name__ == "__main__":
    main()
