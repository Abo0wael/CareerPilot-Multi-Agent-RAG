"""Per-step LLM metering shared by the evaluation and demo-warming scripts."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from src.domain.interfaces import LLMClient
from src.infrastructure.llm.client import GroqClient
from src.infrastructure.llm.prompts.gap_prompts import GAP_SYSTEM_PROMPT
from src.infrastructure.llm.prompts.profile_prompts import PROFILE_SYSTEM_PROMPT
from src.infrastructure.llm.prompts.tailor_prompts import TAILOR_SYSTEM_PROMPT
from src.infrastructure.llm.prompts.verifier_prompts import VERIFIER_SYSTEM_PROMPT
from src.infrastructure.retrieval.expander import EXPANDER_SYSTEM_PROMPT
from src.infrastructure.retrieval.reranker import RERANKER_SYSTEM_PROMPT

STEP_BY_SYSTEM_PROMPT = {
    PROFILE_SYSTEM_PROMPT: "profile_extraction",
    EXPANDER_SYSTEM_PROMPT: "query_expansion",
    RERANKER_SYSTEM_PROMPT: "rerank",
    GAP_SYSTEM_PROMPT: "gap_analysis",
    TAILOR_SYSTEM_PROMPT: "tailoring",
    VERIFIER_SYSTEM_PROMPT: "verification",
}


@dataclass
class StepStats:
    calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rate_limit_hits: int = 0
    requests: int = 0
    live_latencies: list[float] = field(default_factory=list)  # requests that reached Groq

    def as_dict(self) -> dict[str, Any]:
        total = self.prompt_tokens + self.completion_tokens
        lat = self.live_latencies
        return {
            "requests": self.requests,
            "groq_calls": self.calls,
            "cache_hits": self.cache_hits,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": total,
            "tokens_per_groq_call": round(total / self.calls) if self.calls else 0,
            "avg_live_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
            "max_live_latency_s": round(max(lat), 2) if lat else None,
            "rate_limit_429s": self.rate_limit_hits,
        }


class MeteredLLMClient(LLMClient):
    """Wraps ``GroqClient`` and attributes calls, tokens, latency and 429s to a pipeline step."""

    def __init__(self, inner: GroqClient) -> None:
        self._inner = inner
        self.stats: dict[str, StepStats] = defaultdict(StepStats)

    def _metered(self, system_prompt: str, call: Any) -> Any:
        inner = self._inner
        stats = self.stats[STEP_BY_SYSTEM_PROMPT.get(system_prompt, "other")]
        before = (inner.call_count, inner.cache_hits, inner.total_prompt_tokens,
                  inner.total_completion_tokens, inner.rate_limit_hits)
        t0 = time.perf_counter()
        try:
            return call()
        finally:
            stats.requests += 1
            if inner.call_count > before[0]:
                stats.live_latencies.append(time.perf_counter() - t0)
            stats.calls += inner.call_count - before[0]
            stats.cache_hits += inner.cache_hits - before[1]
            stats.prompt_tokens += inner.total_prompt_tokens - before[2]
            stats.completion_tokens += inner.total_completion_tokens - before[3]
            stats.rate_limit_hits += inner.rate_limit_hits - before[4]

    def generate(self, prompt: str, system_prompt: str = "", model: Optional[str] = None,
                 temperature: float = 0.0, max_tokens: int = 4096) -> str:
        return self._metered(
            system_prompt, lambda: self._inner.generate(prompt, system_prompt, model, temperature, max_tokens)
        )

    def generate_json(self, prompt: str, system_prompt: str = "", model: Optional[str] = None,
                      temperature: float = 0.0, max_tokens: int = 4096) -> dict:
        return self._metered(
            system_prompt, lambda: self._inner.generate_json(prompt, system_prompt, model, temperature, max_tokens)
        )

    def summary(self) -> dict[str, dict[str, Any]]:
        return {step: s.as_dict() for step, s in sorted(self.stats.items())}
