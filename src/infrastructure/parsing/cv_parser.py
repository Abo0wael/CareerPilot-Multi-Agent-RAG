"""CV parsing implementations for PDF and plain text documents.

Implements ``CVParser`` from the domain layer.
Clean Architecture: infrastructure adapter converting raw binary files to domain text.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from src.domain.exceptions import CVParsingError
from src.domain.interfaces import CVParser

logger = logging.getLogger(__name__)


class UniversalCVParser(CVParser):
    """Parses plain text (.txt) and PDF (.pdf) CV files.

    Single Responsibility: file format detection and text extraction.
    Open/Closed: easily extensible for additional formats (e.g. DOCX).
    """

    def parse(self, file_bytes: bytes, filename: str) -> str:
        """Extract and clean plain text from *file_bytes*.

        Args:
            file_bytes: Raw bytes of the uploaded file.
            filename: Original filename (used to identify extension).

        Returns:
            Clean extracted text string.

        Raises:
            CVParsingError: If parsing fails or the extracted text is empty.
        """
        if not file_bytes:
            raise CVParsingError(filename, "Uploaded file is empty (0 bytes).")

        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            return self._parse_pdf(file_bytes, filename)
        elif ext in (".txt", ".md", ".text", ""):
            return self._parse_text(file_bytes, filename)
        else:
            raise CVParsingError(
                filename,
                f"Unsupported file format '{ext}'. Supported formats: .pdf, .txt",
            )

    def _parse_pdf(self, file_bytes: bytes, filename: str) -> str:
        """Extract text from PDF pages using pypdf."""
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as err:
                    raise CVParsingError(filename, f"PDF is password-protected: {err}") from err

            extracted_pages: list[str] = []
            for idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(page_text.strip())

            full_text = "\n\n".join(extracted_pages).strip()
            if not full_text:
                raise CVParsingError(
                    filename,
                    "PDF file contains no extractable text (it may be a scanned image).",
                )

            logger.info("Successfully parsed PDF '%s' (%d pages, %d chars)", filename, len(reader.pages), len(full_text))
            return full_text
        except PyPdfError as err:
            raise CVParsingError(filename, f"Invalid or corrupted PDF file: {err}") from err
        except Exception as err:
            if isinstance(err, CVParsingError):
                raise
            raise CVParsingError(filename, f"Error extracting text from PDF: {err}") from err

    def _parse_text(self, file_bytes: bytes, filename: str) -> str:
        """Decode plain text file using utf-8 with latin-1 fallback."""
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")  # every byte sequence is valid latin-1

        text = text.strip()
        if not text:
            raise CVParsingError(filename, "Text file is empty.")

        logger.info("Successfully parsed text document '%s' (%d chars)", filename, len(text))
        return text
