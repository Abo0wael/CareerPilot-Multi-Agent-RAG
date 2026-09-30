"""Tests for chunkers: section split, fallback, max length, empty input, label preservation."""

from __future__ import annotations

import pytest

from src.domain.entities import ChunkSection, JobPosting
from src.infrastructure.chunking.chunkers import (
    ChunkerFactory,
    CompositeChunker,
    ParagraphChunker,
    SectionChunker,
)


def _make_posting(description: str, **kwargs) -> JobPosting:
    """Helper to create a ``JobPosting`` with minimal required fields."""
    defaults = {
        "job_id": 1,
        "title": "Test Engineer",
        "company_name": "TestCo",
    }
    defaults.update(kwargs)
    return JobPosting(description=description, **defaults)


# ── SectionChunker tests ────────────────────────────────────────────

class TestSectionChunker:
    """Tests for section-based chunking."""

    def test_detects_requirements_header(self) -> None:
        desc = (
            "About the company.\n\n"
            "Requirements\n"
            "Must know Python.\n"
            "Must know SQL.\n"
        )
        chunker = SectionChunker(max_length=2000)
        posting = _make_posting(desc)
        chunks = chunker.chunk(posting)

        assert len(chunks) >= 2  # pre-header text + requirements
        sections = {c.section for c in chunks}
        assert ChunkSection.REQUIREMENTS in sections

    def test_detects_multiple_sections(self) -> None:
        desc = (
            "Introduction text.\n\n"
            "Responsibilities\n"
            "Build APIs.\n\n"
            "Requirements\n"
            "3+ years experience.\n\n"
            "Nice to have\n"
            "AWS certification.\n"
        )
        chunker = SectionChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))

        sections = {c.section for c in chunks}
        assert ChunkSection.RESPONSIBILITIES in sections
        assert ChunkSection.REQUIREMENTS in sections
        assert ChunkSection.NICE_TO_HAVE in sections

    def test_pre_header_text_labeled_full(self) -> None:
        """Text before the first header should get the FULL label."""
        desc = (
            "We are a startup building great things.\n\n"
            "Requirements\n"
            "Python experience required.\n"
        )
        chunker = SectionChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))

        full_chunks = [c for c in chunks if c.section == ChunkSection.FULL]
        assert len(full_chunks) >= 1
        assert "startup" in full_chunks[0].text

    def test_no_headers_returns_empty(self) -> None:
        """SectionChunker returns empty list when no headers detected."""
        desc = "We are looking for a great candidate with skills."
        chunker = SectionChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))
        assert chunks == []

    def test_long_section_splits_by_paragraph_keeping_label(self) -> None:
        """Sections longer than max_length are split but keep the section label."""
        long_requirements = "Requirements\n" + "\n\n".join(
            [f"Requirement item {i}: " + "x" * 100 for i in range(20)]
        )
        chunker = SectionChunker(max_length=300, overlap=0)
        chunks = chunker.chunk(_make_posting(long_requirements))

        assert len(chunks) > 1
        for c in chunks:
            # All sub-chunks should keep the REQUIREMENTS label
            assert c.section == ChunkSection.REQUIREMENTS

    def test_chunk_metadata_propagated(self) -> None:
        desc = "Requirements\nPython required."
        posting = _make_posting(
            desc,
            job_id=42,
            title="Senior Dev",
            company_name="BigCorp",
            location="NYC",
            remote_allowed=True,
        )
        chunker = SectionChunker(max_length=2000)
        chunks = chunker.chunk(posting)
        assert len(chunks) >= 1
        assert chunks[0].job_id == 42
        assert chunks[0].title == "Senior Dev"
        assert chunks[0].company_name == "BigCorp"
        assert chunks[0].location == "NYC"
        assert chunks[0].remote_allowed is True


# ── ParagraphChunker tests ──────────────────────────────────────────

class TestParagraphChunker:
    """Tests for paragraph-based chunking."""

    def test_splits_by_paragraph(self) -> None:
        desc = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunker = ParagraphChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))
        # With large max_length, all paragraphs fit in one chunk
        assert len(chunks) >= 1

    def test_respects_max_length(self) -> None:
        desc = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
        chunker = ParagraphChunker(max_length=150, overlap=0)
        chunks = chunker.chunk(_make_posting(desc))
        assert len(chunks) >= 2
        for c in chunks:
            # Chunks should be at most max_length (or slightly over if
            # a single paragraph exceeds it)
            assert c.section == ChunkSection.FULL

    def test_all_chunks_labeled_full(self) -> None:
        desc = "Para one.\n\nPara two.\n\nPara three."
        chunker = ParagraphChunker(max_length=30, overlap=0)
        chunks = chunker.chunk(_make_posting(desc))
        for c in chunks:
            assert c.section == ChunkSection.FULL

    def test_single_line_description(self) -> None:
        desc = "Short description without any line breaks."
        chunker = ParagraphChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))
        assert len(chunks) == 1
        assert chunks[0].text == desc


# ── CompositeChunker tests ──────────────────────────────────────────

class TestCompositeChunker:
    """Tests for the composite (section-first, paragraph-fallback) chunker."""

    def test_uses_section_when_headers_present(self) -> None:
        desc = "Intro.\n\nRequirements\nPython required."
        chunker = CompositeChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))
        sections = {c.section for c in chunks}
        assert ChunkSection.REQUIREMENTS in sections

    def test_falls_back_to_paragraph(self) -> None:
        desc = "No headers here, just plain text with paragraphs.\n\nAnother paragraph."
        chunker = CompositeChunker(max_length=2000)
        chunks = chunker.chunk(_make_posting(desc))
        assert len(chunks) >= 1
        for c in chunks:
            assert c.section == ChunkSection.FULL


# ── ChunkerFactory tests ───────────────────────────────────────────

class TestChunkerFactory:
    """Tests for the chunker factory / registry (OCP)."""

    def test_create_builtin_chunkers(self) -> None:
        factory = ChunkerFactory()
        assert isinstance(factory.create("section"), SectionChunker)
        assert isinstance(factory.create("paragraph"), ParagraphChunker)
        assert isinstance(factory.create("composite"), CompositeChunker)

    def test_unknown_chunker_raises(self) -> None:
        factory = ChunkerFactory()
        with pytest.raises(KeyError, match="Unknown chunker"):
            factory.create("nonexistent")

    def test_register_custom_chunker(self) -> None:
        """OCP: new chunkers can be added without modifying existing code."""
        factory = ChunkerFactory()

        class CustomChunker(ParagraphChunker):
            pass

        factory.register("custom", CustomChunker)
        assert isinstance(factory.create("custom"), CustomChunker)


# ── Hierarchical splitting & length enforcement tests ────────────────

class TestHierarchicalChunking:
    """Tests for hierarchical splitting (\n\n -> \n -> sentence -> hard cap) and min_length merge."""

    def test_single_newline_bullets_split_under_max_length(self) -> None:
        """Postings with single newlines (bullets) must be split to satisfy max_length."""
        bullets = "\n".join([f"• Key responsibility bullet point {i}: must know tech stack." for i in range(30)])
        desc = "Responsibilities\n" + bullets
        chunker = SectionChunker(max_length=300, min_length=50, overlap=0)
        chunks = chunker.chunk(_make_posting(desc))

        assert len(chunks) > 1
        for c in chunks:
            assert len(c.text) <= 300
            assert c.section == ChunkSection.RESPONSIBILITIES

    def test_strict_max_length_enforcement_zero_percent_above(self) -> None:
        """Guarantee 0% of chunks exceed max_length even with long unbroken text."""
        long_unbroken = "Word " * 200 + "SuperLongUnbrokenTokenWithoutSpaces" * 10
        chunker = ParagraphChunker(max_length=250, min_length=50, overlap=0)
        chunks = chunker.chunk(_make_posting(long_unbroken))

        assert len(chunks) > 1
        for c in chunks:
            assert len(c.text) <= 250

    def test_merges_tiny_chunks_below_min_length(self) -> None:
        """Chunks smaller than min_length must be merged into neighboring chunks."""
        desc = "Paragraph one with reasonable content.\n\nTiny.\n\nParagraph three with more content."
        chunker = ParagraphChunker(max_length=500, min_length=50, overlap=0)
        chunks = chunker.chunk(_make_posting(desc))

        # "Tiny." should be merged, so no chunk with len < 50
        for c in chunks:
            assert len(c.text) >= 50

