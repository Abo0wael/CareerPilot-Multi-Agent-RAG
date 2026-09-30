"""Ingest Jobs use case.

Loads postings from a ``JobSource``, stores them as parent documents, chunks
them, and indexes the chunks. Depends only on domain interfaces.
"""

from __future__ import annotations

import logging

from src.domain.entities import IngestResult, JobChunk
from src.domain.interfaces import Chunker, JobSource, SearchIndexWriter

logger = logging.getLogger(__name__)


class IngestJobsUseCase:
    """(Re)build the search index from a job source."""

    def __init__(
        self,
        job_source: JobSource,
        chunker: Chunker,
        index_writer: SearchIndexWriter,
        batch_size: int = 1000,
    ) -> None:
        self._job_source = job_source
        self._chunker = chunker
        self._index_writer = index_writer
        self._batch_size = batch_size

    def execute(self, clear_existing: bool = True) -> IngestResult:
        """Index every posting from the source.

        Args:
            clear_existing: Remove all previously indexed jobs and chunks first.
        """
        postings = self._job_source.load_postings()
        logger.info("Starting ingestion of %d postings.", len(postings))
        if clear_existing:
            self._index_writer.clear()

        jobs_stored = 0
        for start in range(0, len(postings), self._batch_size):
            jobs_stored += self._index_writer.add_jobs(postings[start : start + self._batch_size])

        chunks_indexed = 0
        buffer: list[JobChunk] = []
        for posting in postings:
            buffer.extend(self._chunker.chunk(posting))
            if len(buffer) >= self._batch_size:
                chunks_indexed += self._index_writer.add_chunks(buffer)
                buffer.clear()
        if buffer:
            chunks_indexed += self._index_writer.add_chunks(buffer)

        logger.info("Ingestion complete: %d jobs, %d chunks.", jobs_stored, chunks_indexed)
        return IngestResult(jobs_ingested=jobs_stored, chunks_indexed=chunks_indexed)
