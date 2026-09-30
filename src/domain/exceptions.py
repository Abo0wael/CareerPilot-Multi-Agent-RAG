"""Domain exceptions for CareerPilot.

All custom exceptions inherit from a single base so that upper layers
can catch domain errors generically when appropriate.
"""


class CareerPilotError(Exception):
    """Base exception for all CareerPilot domain errors."""


# ── Entity validation ────────────────────────────────────────────────

class EmptyFieldError(CareerPilotError):
    """Raised when a required text field is empty or whitespace-only."""

    def __init__(self, entity_name: str, field_name: str) -> None:
        self.entity_name = entity_name
        self.field_name = field_name
        super().__init__(
            f"{entity_name}.{field_name} must not be empty or whitespace-only."
        )


class InvalidEntityError(CareerPilotError):
    """Raised when an entity cannot be constructed due to invalid data."""

    def __init__(self, entity_name: str, reason: str) -> None:
        self.entity_name = entity_name
        self.reason = reason
        super().__init__(f"Invalid {entity_name}: {reason}")


# ── LLM / external service ──────────────────────────────────────────

class LLMError(CareerPilotError):
    """Base for all LLM-related errors."""


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider rate-limits persist after retries."""


class LLMResponseParseError(LLMError):
    """Raised when the LLM response cannot be parsed into the expected schema."""

    def __init__(self, raw_response: str, reason: str) -> None:
        self.raw_response = raw_response
        self.reason = reason
        super().__init__(f"Failed to parse LLM response: {reason}")


# ── Retrieval / search ──────────────────────────────────────────────

class IndexNotFoundError(CareerPilotError):
    """Raised when the search index does not exist on disk."""


class FTS5NotAvailableError(CareerPilotError):
    """Raised when SQLite FTS5 extension is not compiled in."""

    def __init__(self) -> None:
        super().__init__(
            "SQLite FTS5 is required but not available in this Python build. "
            "Install a Python distribution that includes FTS5 "
            "(standard CPython builds on Windows and macOS include it)."
        )


# ── CV parsing ──────────────────────────────────────────────────────

class CVParsingError(CareerPilotError):
    """Raised when CV text cannot be extracted from the uploaded file."""

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


# ── Job data ────────────────────────────────────────────────────────

class JobNotFoundError(CareerPilotError):
    """Raised when a requested job_id does not exist in the repository."""

    def __init__(self, job_id: int) -> None:
        self.job_id = job_id
        super().__init__(f"Job posting with id {job_id} not found.")


# ── Workflow ────────────────────────────────────────────────────────

class WorkflowStateError(CareerPilotError):
    """Raised when an agent node is invoked without the state it requires."""
