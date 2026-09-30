"""Abstract base class for CareerPilot LangGraph agent nodes.

Every agent is a thin node: it reads what it needs from the workflow state,
delegates the work to one application use case, and returns only the state
keys it produced (LangGraph merges them into the state).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.domain.exceptions import WorkflowStateError

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Common interface for all workflow nodes (polymorphic ``run``)."""

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the node and return the state updates it produced."""

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph calls nodes as plain callables."""
        logger.info("Executing agent [%s]", self.name)
        return self.run(state)

    def _require(self, state: dict[str, Any], key: str) -> Any:
        """Return ``state[key]`` or raise ``WorkflowStateError`` if it is missing."""
        value = state.get(key)
        if value is None:
            raise WorkflowStateError(f"{self.name} requires '{key}' in the workflow state.")
        return value
