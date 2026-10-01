"""Context-variable implementation of ``ModelUsageTracker``.

Context variables keep concurrent API requests apart: each request (thread or
task) sees only its own ``collect()`` list and its own current agent.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from src.domain.entities import ModelCall
from src.domain.interfaces import ModelUsageTracker

_calls: ContextVar[Optional[list[ModelCall]]] = ContextVar("model_calls", default=None)
_agent: ContextVar[str] = ContextVar("model_call_agent", default="")


class ContextModelUsageTracker(ModelUsageTracker):
    """Collects ``ModelCall`` records per request, tagged with the running agent."""

    @contextmanager
    def collect(self) -> Iterator[list[ModelCall]]:
        calls: list[ModelCall] = []
        token = _calls.set(calls)
        try:
            yield calls
        finally:
            _calls.reset(token)

    @contextmanager
    def step(self, agent: str) -> Iterator[None]:
        token = _agent.set(agent)
        try:
            yield
        finally:
            _agent.reset(token)

    def record(self, requested_model: str, answered_model: str, cached: bool) -> None:
        calls = _calls.get()
        if calls is not None:
            calls.append(ModelCall(_agent.get(), requested_model, answered_model, cached))
