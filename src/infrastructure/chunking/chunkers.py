"""Hierarchical section-based and paragraph-based chunkers with factory registry.

Chunking strategy:
- **Hierarchical decomposition:**
  `\\n\\n` (paragraphs) -> `\\n` (lines/bullets) -> sentence boundaries -> word boundaries -> hard cap.
  Guarantees that 100% of chunks satisfy ``len(chunk) <= max_length``.
- **Tiny chunk merging:**
  Chunks smaller than ``min_length`` (default 100 chars) are merged into the
  neighboring chunk of the same section label without exceeding ``max_length``.
- **Section label preservation:**
  Sections exceeding ``max_length`` are sub-split hierarchically but **retain
  their section label** (e.g. ``requirements_0``, ``requirements_1``).
- **Composite chunker:**
  Attempts ``SectionChunker`` first (detected headers); falls back to
  ``ParagraphChunker`` for unstructured postings (labeled ``FULL``).
- **Open/Closed Principle:**
  New chunkers are registered in ``ChunkerFactory`` without modifying existing code.
"""

from __future__ import annotations

import logging
import re

from src.domain.entities import ChunkSection, JobChunk, JobPosting
from src.domain.interfaces import Chunker

logger = logging.getLogger(__name__)

# ── Section-header regex patterns ────────────────────────────────────
# Order matters: more specific patterns first.
_SECTION_PATTERNS: list[tuple[ChunkSection, re.Pattern[str]]] = [
    (
        ChunkSection.RESPONSIBILITIES,
        re.compile(
            r"(?:^|\n)\s*(?:#+\s*)?(?:key\s+)?(?:roles?\s*(?:and|&)\s*)?responsibilities\b",
            re.IGNORECASE,
        ),
    ),
    (
        ChunkSection.REQUIREMENTS,
        re.compile(
            r"(?:^|\n)\s*(?:#+\s*)?(?:minimum\s+|basic\s+|required\s+)?(?:requirements?|qualifications?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ChunkSection.NICE_TO_HAVE,
        re.compile(
            r"(?:^|\n)\s*(?:#+\s*)?(?:nice\s*to\s*have|preferred|bonus|desired|plus)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ChunkSection.BENEFITS,
        re.compile(
            r"(?:^|\n)\s*(?:#+\s*)?(?:benefits?|perks?|compensation|what\s+we\s+offer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        ChunkSection.ABOUT,
        re.compile(
            r"(?:^|\n)\s*(?:#+\s*)?(?:about\s+(?:us|the\s+company|the\s+role)|company\s+(?:overview|description)|who\s+we\s+are)\b",
            re.IGNORECASE,
        ),
    ),
]


def _decompose_text(text: str, max_length: int) -> list[str]:
    """Decompose *text* hierarchically until every atomic piece is <= max_length.

    Hierarchy:
    1. Double newlines (\\n\\n)
    2. Single newlines (\\n - bullet points, list items)
    3. Sentence boundaries (. ! ?)
    4. Word boundaries (spaces)
    5. Hard slicing (unbroken tokens)
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    # Level 1: Double newlines
    parts_lvl1 = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts_lvl1) > 1:
        atoms: list[str] = []
        for p in parts_lvl1:
            atoms.extend(_decompose_text(p, max_length))
        return atoms

    # Level 2: Single newlines
    parts_lvl2 = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts_lvl2) > 1:
        atoms = []
        for p in parts_lvl2:
            atoms.extend(_decompose_text(p, max_length))
        return atoms

    # Level 3: Sentence boundaries
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) > 1:
        atoms = []
        for s in sentences:
            atoms.extend(_decompose_text(s, max_length))
        return atoms

    # Level 4: Word boundaries
    words = text.split(" ")
    if len(words) > 1:
        atoms = []
        curr = ""
        for w in words:
            if not curr:
                curr = w
            elif len(curr) + 1 + len(w) <= max_length:
                curr += " " + w
            else:
                atoms.append(curr)
                curr = w
        if curr:
            atoms.append(curr)

        final_atoms: list[str] = []
        for a in atoms:
            if len(a) <= max_length:
                final_atoms.append(a)
            else:
                # Level 5: Hard slice if a single unbroken word > max_length
                for i in range(0, len(a), max_length):
                    final_atoms.append(a[i : i + max_length])
        return final_atoms

    # Level 5: Hard slice unbroken string
    return [text[i : i + max_length] for i in range(0, len(text), max_length)]


def _split_hierarchical(
    text: str,
    max_length: int = 800,
    min_length: int = 100,
    overlap: int = 50,
) -> list[str]:
    """Hierarchically split *text* into chunks of at most *max_length* characters.

    1. Decompose text into atoms of len <= max_length.
    2. Greedily pack atoms into chunks up to max_length (with optional overlap).
    3. Merge tiny chunks (< min_length) into neighboring chunks without exceeding max_length.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    atoms = _decompose_text(text, max_length)
    if not atoms:
        return []

    # Greedily pack atoms into chunks
    chunks: list[str] = []
    current = ""

    for atom in atoms:
        if not current:
            current = atom
        elif len(current) + 1 + len(atom) <= max_length:
            current = current + "\n" + atom
        else:
            chunks.append(current)
            if overlap > 0 and len(current) > overlap:
                prefix = current[-overlap:]
                if len(prefix) + 1 + len(atom) <= max_length:
                    current = prefix + "\n" + atom
                else:
                    current = atom
            else:
                current = atom

    if current:
        chunks.append(current)

    # Merge tiny chunks (< min_length) into neighbors
    if len(chunks) > 1 and min_length > 0:
        merged: list[str] = []
        for c in chunks:
            if not merged:
                merged.append(c)
            elif len(c) < min_length and len(merged[-1]) + 1 + len(c) <= max_length:
                merged[-1] = merged[-1] + "\n" + c
            elif len(merged[-1]) < min_length and len(merged[-1]) + 1 + len(c) <= max_length:
                merged[-1] = merged[-1] + "\n" + c
            else:
                merged.append(c)

        if len(merged) > 1 and len(merged[-1]) < min_length:
            if len(merged[-2]) + 1 + len(merged[-1]) <= max_length:
                merged[-2] = merged[-2] + "\n" + merged[-1]
                merged.pop()
        chunks = merged

    return chunks


def _make_chunk(
    posting: JobPosting,
    section: ChunkSection,
    text: str,
    seq: int,
) -> JobChunk:
    """Create a ``JobChunk`` with metadata from *posting*."""
    return JobChunk(
        chunk_id=f"{posting.job_id}_{section.value}_{seq}",
        job_id=posting.job_id,
        section=section,
        text=text,
        title=posting.title,
        company_name=posting.company_name,
        location=posting.location,
        formatted_experience_level=posting.formatted_experience_level,
        formatted_work_type=posting.formatted_work_type,
        remote_allowed=posting.remote_allowed,
        min_salary=posting.min_salary,
        max_salary=posting.max_salary,
    )


# ── SectionChunker ──────────────────────────────────────────────────

class SectionChunker(Chunker):
    """Splits job descriptions by detected section headers hierarchically.

    Sections longer than *max_length* are sub-split hierarchically
    but **keep their section label**. Chunks < *min_length* are merged.
    """

    def __init__(
        self,
        max_length: int = 800,
        min_length: int = 100,
        overlap: int = 50,
    ) -> None:
        self._max_length = max_length
        self._min_length = min_length
        self._overlap = overlap

    def chunk(self, posting: JobPosting) -> list[JobChunk]:
        """Split *posting* into section-labelled chunks."""
        text = posting.description
        matches: list[tuple[int, ChunkSection]] = []
        for section, pattern in _SECTION_PATTERNS:
            for m in pattern.finditer(text):
                matches.append((m.start(), section))

        if not matches:
            return []

        matches.sort(key=lambda x: x[0])

        chunks: list[JobChunk] = []
        seq = 0

        # Text before first header is unlabeled content (FULL section)
        if matches[0][0] > 0:
            pre_text = text[: matches[0][0]].strip()
            if pre_text:
                for sub in _split_hierarchical(
                    pre_text, self._max_length, self._min_length, self._overlap
                ):
                    if sub.strip():
                        chunks.append(
                            _make_chunk(posting, ChunkSection.FULL, sub.strip(), seq)
                        )
                        seq += 1

        # Each detected section
        for i, (start, section) in enumerate(matches):
            end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()

            if not section_text:
                continue

            for sub in _split_hierarchical(
                section_text, self._max_length, self._min_length, self._overlap
            ):
                if sub.strip():
                    chunks.append(_make_chunk(posting, section, sub.strip(), seq))
                    seq += 1

        return chunks


# ── ParagraphChunker ────────────────────────────────────────────────

class ParagraphChunker(Chunker):
    """Splits job descriptions hierarchically into chunks of at most *max_length*.

    Used as fallback when no section headers are detected.
    All chunks receive the ``FULL`` section label.
    """

    def __init__(
        self,
        max_length: int = 800,
        min_length: int = 100,
        overlap: int = 50,
    ) -> None:
        self._max_length = max_length
        self._min_length = min_length
        self._overlap = overlap

    def chunk(self, posting: JobPosting) -> list[JobChunk]:
        """Split *posting* into hierarchical chunks with ``FULL`` label."""
        pieces = _split_hierarchical(
            posting.description, self._max_length, self._min_length, self._overlap
        )
        return [
            _make_chunk(posting, ChunkSection.FULL, piece.strip(), seq)
            for seq, piece in enumerate(pieces)
            if piece.strip()
        ]


# ── Composite Chunker ───────────────────────────────────────────────

class CompositeChunker(Chunker):
    """Tries ``SectionChunker`` first; falls back to ``ParagraphChunker``.

    This is the default chunker used in production.
    """

    def __init__(
        self,
        max_length: int = 800,
        min_length: int = 100,
        overlap: int = 50,
    ) -> None:
        self._section = SectionChunker(max_length, min_length, overlap)
        self._paragraph = ParagraphChunker(max_length, min_length, overlap)

    def chunk(self, posting: JobPosting) -> list[JobChunk]:
        """Chunk using sections if headers are detected, else paragraphs."""
        chunks = self._section.chunk(posting)
        if chunks:
            return chunks
        return self._paragraph.chunk(posting)


# ── Factory / Registry ──────────────────────────────────────────────

class ChunkerFactory:
    """Registry for chunker implementations.

    Open/Closed Principle: new chunkers are registered via ``register()``
    without modifying existing code.
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[Chunker]] = {}
        self.register("section", SectionChunker)
        self.register("paragraph", ParagraphChunker)
        self.register("composite", CompositeChunker)

    def register(self, name: str, chunker_class: type[Chunker]) -> None:
        """Register a chunker class under *name*."""
        self._registry[name] = chunker_class
        logger.debug("Registered chunker: %s -> %s", name, chunker_class.__name__)

    def create(
        self, name: str = "composite", **kwargs: int
    ) -> Chunker:
        """Create a chunker by *name*.

        Args:
            name: Registered chunker name.
            **kwargs: Passed to the chunker constructor (e.g. max_length, min_length, overlap).

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._registry:
            available = ", ".join(sorted(self._registry))
            raise KeyError(
                f"Unknown chunker '{name}'. Available: {available}"
            )
        return self._registry[name](**kwargs)
