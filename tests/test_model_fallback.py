"""Model fallback on persistent rate limits, and reporting which model answered each agent.

A fake Groq SDK returns 429 for the rate-limited models; nothing calls Groq.
"""

from __future__ import annotations

from typing import Any, Generator
from unittest.mock import MagicMock

import groq
import httpx
import pytest
from fastapi.testclient import TestClient

from src.agents.graph import create_careerpilot_graph
from src.agents.profile_agent import ProfileAgent
from src.agents.workflow import CareerPilotWorkflow
from src.api.dependencies import build_workflow, get_model_usage_tracker, get_workflow
from src.api.main import app
from src.application.build_profile import BuildProfileUseCase
from src.domain.exceptions import LLMRateLimitError
from src.infrastructure.config import Settings
from src.infrastructure.llm.client import GroqClient
from src.infrastructure.llm.model_usage import ContextModelUsageTracker
from src.infrastructure.llm.profile_extractor import GroqProfileExtractor
from src.infrastructure.parsing.cv_parser import UniversalCVParser

PRIMARY = "openai/gpt-oss-120b"
FAST = "openai/gpt-oss-20b"
OTHER = "qwen/qwen3.8-27b"


def _rate_limit_error(retry_after: str | None = None) -> groq.RateLimitError:
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"), headers=headers)
    return groq.RateLimitError("429", response=response, body=None)


class FakeGroq:
    """Stands in for the Groq SDK: models in *limited* always answer 429."""

    def __init__(self, limited: set[str], content: str = '{"answer": "ok"}', retry_after: str | None = None) -> None:
        self.limited = limited
        self.content = content
        self.retry_after = retry_after
        self.models_called: list[str] = []
        self.chat = MagicMock()
        self.chat.completions.create.side_effect = self._create

    def _create(self, model: str, **_: Any) -> Any:
        self.models_called.append(model)
        if model in self.limited:
            raise _rate_limit_error(self.retry_after)
        response = MagicMock()
        response.choices[0].message.content = self.content
        response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens = 10, 5, 15
        return response


def _settings(tmp_path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "groq_api_key": "fake",
        "llm_cache_dir": tmp_path / "cache",
        "llm_max_retries": 2,
        "llm_retry_min_wait": 0,
        "llm_retry_max_wait": 0,
        "groq_agent_model": PRIMARY,
        "groq_fast_model": FAST,
        "groq_fallback_models": f"{PRIMARY},{FAST},{OTHER}",
    }
    values.update(overrides)
    return Settings(**values)


def _client(tmp_path, fake: FakeGroq, **overrides: Any) -> tuple[GroqClient, ContextModelUsageTracker]:
    tracker = ContextModelUsageTracker()
    return GroqClient(settings=_settings(tmp_path, **overrides), client=fake, usage_tracker=tracker), tracker


# ── Settings ─────────────────────────────────────────────────────────

def test_fallback_chain_starts_with_requested_model_without_duplicates(tmp_path) -> None:
    settings = _settings(tmp_path)
    assert settings.fallback_chain(PRIMARY) == [PRIMARY, FAST, OTHER]
    assert settings.fallback_chain(FAST) == [FAST, PRIMARY, OTHER]
    assert settings.fallback_chain("custom-model") == ["custom-model", PRIMARY, FAST, OTHER]


def test_empty_fallback_list_disables_fallback(tmp_path) -> None:
    assert _settings(tmp_path, groq_fallback_models="").fallback_chain(PRIMARY) == [PRIMARY]


# ── GroqClient ───────────────────────────────────────────────────────

def test_429_on_first_model_is_answered_by_next_model(tmp_path) -> None:
    fake = FakeGroq(limited={PRIMARY})
    client, tracker = _client(tmp_path, fake)

    with tracker.collect() as calls:
        assert client.generate_json("Extract skills", model=PRIMARY) == {"answer": "ok"}

    assert fake.models_called == [PRIMARY, PRIMARY, FAST]  # existing retries first, then fallback
    assert [(c.requested_model, c.answered_model, c.used_fallback, c.cached) for c in calls] == [
        (PRIMARY, FAST, True, False)
    ]
    assert client.fallback_count == 1


def test_walks_the_whole_chain_until_a_model_answers(tmp_path) -> None:
    fake = FakeGroq(limited={PRIMARY, FAST})
    client, tracker = _client(tmp_path, fake)

    with tracker.collect() as calls:
        client.generate_json("x", model=PRIMARY)

    assert fake.models_called == [PRIMARY, PRIMARY, FAST, FAST, OTHER]
    assert calls[0].answered_model == OTHER


def test_every_model_rate_limited_raises_domain_error(tmp_path) -> None:
    client, _ = _client(tmp_path, FakeGroq(limited={PRIMARY, FAST, OTHER}))
    with pytest.raises(LLMRateLimitError):
        client.generate_json("x", model=PRIMARY)


def test_long_retry_after_falls_back_without_waiting(tmp_path) -> None:
    """A wait longer than llm_retry_max_wait (e.g. a daily limit) cannot be retried in time."""
    fake = FakeGroq(limited={PRIMARY}, retry_after="3600")
    client, _ = _client(tmp_path, fake, llm_max_retries=6, llm_retry_max_wait=60)

    client.generate_json("x", model=PRIMARY)

    assert fake.models_called == [PRIMARY, FAST]


def test_primary_cache_hit_is_unchanged_and_never_calls_groq(tmp_path) -> None:
    fake = FakeGroq(limited=set())
    client, tracker = _client(tmp_path, fake)
    client.generate_json("demo prompt", model=PRIMARY)  # fills the cache for the primary model

    fake.limited = {PRIMARY}  # even if the primary model is now rate-limited...
    with tracker.collect() as calls:
        assert client.generate_json("demo prompt", model=PRIMARY) == {"answer": "ok"}

    assert fake.models_called == [PRIMARY]  # ...the cached answer is served
    assert [(c.answered_model, c.cached, c.used_fallback) for c in calls] == [(PRIMARY, True, False)]


def test_fallback_answer_is_not_cached_as_the_primary_model(tmp_path) -> None:
    fake = FakeGroq(limited={PRIMARY})
    client, tracker = _client(tmp_path, fake)
    client.generate_json("x", model=PRIMARY)

    fake.limited = set()  # the primary model recovered
    with tracker.collect() as calls:
        client.generate_json("x", model=PRIMARY)

    assert fake.models_called[-1] == PRIMARY  # asked again, not replayed from the fallback
    assert calls[0].answered_model == PRIMARY
    # The fallback answer stays reusable for direct requests to the fallback model.
    with tracker.collect() as direct:
        client.generate_json("x", model=FAST)
    assert direct[0].cached


def test_nothing_is_recorded_outside_a_collect_scope(tmp_path) -> None:
    client, tracker = _client(tmp_path, FakeGroq(limited=set()))
    client.generate_json("x", model=PRIMARY)  # must not fail or leak into the next scope
    with tracker.collect() as calls:
        pass
    assert calls == []


# ── Attribution per agent through the LangGraph workflow ─────────────

def _profile_workflow(tmp_path, fake: FakeGroq) -> tuple[CareerPilotWorkflow, ContextModelUsageTracker]:
    """The real graph, with the Groq-backed profile step on the agent model."""
    client, tracker = _client(tmp_path, fake)
    content = '{"name": "Alice", "skills": ["Python"]}'
    fake.content = content
    profile_agent = ProfileAgent(
        BuildProfileUseCase(UniversalCVParser(), GroqProfileExtractor(client, model=PRIMARY))
    )
    unused = MagicMock()
    graph = create_careerpilot_graph(profile_agent, unused, unused, unused, unused, usage_tracker=tracker)
    return CareerPilotWorkflow(graph), tracker


def test_graph_tags_each_call_with_the_agent_that_made_it(tmp_path) -> None:
    workflow, tracker = _profile_workflow(tmp_path, FakeGroq(limited={PRIMARY}))
    with tracker.collect() as calls:
        profile = workflow.build_profile(raw_text="Alice\nPython developer")
    assert profile.name == "Alice"
    assert [(c.agent, c.answered_model, c.used_fallback) for c in calls] == [("ProfileAgent", FAST, True)]


def test_build_workflow_accepts_a_tracker(tmp_path) -> None:
    settings = _settings(tmp_path)
    assert build_workflow(settings, MagicMock(), ContextModelUsageTracker()) is not None


# ── API response ─────────────────────────────────────────────────────

@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_profile_endpoint_reports_the_fallback_model(tmp_path, api_client: TestClient) -> None:
    workflow, tracker = _profile_workflow(tmp_path, FakeGroq(limited={PRIMARY}))
    app.dependency_overrides[get_workflow] = lambda: workflow
    app.dependency_overrides[get_model_usage_tracker] = lambda: tracker

    body = api_client.post("/profile", data={"raw_text": "Alice\nPython developer"}).json()

    assert body["name"] == "Alice"
    assert body["model_calls"] == [
        {"agent": "ProfileAgent", "requested_model": PRIMARY, "answered_model": FAST, "used_fallback": True, "cached": False}
    ]
