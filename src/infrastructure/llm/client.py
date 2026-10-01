"""Groq LLM client implementation with retries, disk caching, and JSON repair.

Implements ``LLMClient`` from the domain layer.
Zero vector DB or embeddings dependencies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional

from groq import APIConnectionError, APIError, Groq, RateLimitError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    wait_exponential,
)

from src.domain.exceptions import LLMError, LLMRateLimitError, LLMResponseParseError
from src.domain.interfaces import LLMClient, ModelUsageTracker
from src.infrastructure.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _extract_json_substring(text: str) -> str:
    """Extract a JSON object or array from LLM output that might contain markdown fences."""
    text = text.strip()
    # Remove markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # Search for first { to last } or first [ to last ]
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1].strip()

    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        return text[first_bracket : last_bracket + 1].strip()

    return text


def _retry_after_seconds(exc: BaseException | None) -> Optional[float]:
    """Seconds Groq asked us to wait (``retry-after`` header on a 429), if any."""
    response = getattr(exc, "response", None)
    value = response.headers.get("retry-after") if response is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


class GroqClient(LLMClient):
    """Concrete LLM client connecting exclusively to Groq API.

    Features:
    - Retries on rate limits (429) and connection errors, waiting as long as
      Groq's ``retry-after`` header asks (exponential backoff otherwise).
    - Model fallback: if a model is still rate-limited after its retries, the same
      request is sent to the next model in ``Settings.fallback_chain``.
    - Optional ``reasoning_effort`` for gpt-oss models to cut hidden reasoning tokens.
    - Persistent disk-based caching (SHA-256 key) to prevent redundant API calls.
    - JSON extraction and repair fallback for structured responses.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[Groq] = None,
        usage_tracker: Optional[ModelUsageTracker] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or Groq(api_key=self._settings.groq_api_key)
        self._usage = usage_tracker
        self._cache_dir = self._settings.llm_cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # Usage tracking
        self.call_count: int = 0
        self.cache_hits: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_tokens: int = 0
        self.rate_limit_hits: int = 0
        self.fallback_count: int = 0

    def get_metrics(self) -> dict[str, int]:
        """Return cumulative Groq API calls and token counts."""
        return {
            "call_count": self.call_count,
            "cache_hits": self.cache_hits,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "rate_limit_hits": self.rate_limit_hits,
            "fallback_count": self.fallback_count,
        }

    def reset_metrics(self) -> None:
        """Reset usage metrics to zero."""
        self.call_count = 0
        self.cache_hits = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.rate_limit_hits = 0
        self.fallback_count = 0

    def _reasoning_effort(self, model_name: str) -> str:
        """Reasoning effort applies to gpt-oss models only ('' = provider default)."""
        return self._settings.groq_reasoning_effort if model_name.startswith("openai/gpt-oss") else ""

    def _wait_before_retry(self, retry_state: RetryCallState) -> float:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        retry_after = _retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, self._settings.llm_retry_max_wait)
        backoff = wait_exponential(multiplier=self._settings.llm_retry_min_wait, max=self._settings.llm_retry_max_wait)
        return backoff(retry_state)

    def _stop_retrying(self, retry_state: RetryCallState) -> bool:
        """Stop after ``llm_max_retries`` attempts, or at once if Groq asks for a longer wait
        than ``llm_retry_max_wait`` (e.g. a daily limit): retrying that model cannot succeed soon."""
        if retry_state.attempt_number >= self._settings.llm_max_retries:
            return True
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        retry_after = _retry_after_seconds(exc)
        return retry_after is not None and retry_after > self._settings.llm_retry_max_wait

    def _cache_key(self, payload: dict[str, Any]) -> str:
        """Compute deterministic SHA-256 hash of prompt and parameters."""
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_from_cache(self, key: str) -> Optional[str]:
        """Read cached text response from disk if present."""
        path = self._cache_dir / f"{key}.txt"
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError as err:
                logger.warning("Cache read failed for key %s: %s", key, err)
        return None

    def _write_to_cache(self, key: str, content: str) -> None:
        """Save text response to disk cache."""
        path = self._cache_dir / f"{key}.txt"
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as err:
            logger.warning("Cache write failed for key %s: %s", key, err)

    def _complete(
        self,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        """Call Groq with retries on 429/connection errors and record token usage.

        Raises:
            LLMRateLimitError: If the rate limit persists after all retries.
            LLMError: For connection failures after retries and any other API error.
        """
        extra: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
        if self._reasoning_effort(model_name):
            extra["reasoning_effort"] = self._reasoning_effort(model_name)

        @retry(
            retry=retry_if_exception_type((RateLimitError, APIConnectionError)),
            stop=self._stop_retrying,
            wait=self._wait_before_retry,
            reraise=True,
        )
        def _call_api() -> str:
            try:
                response = self._client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **extra,
                )
            except RateLimitError:
                self.rate_limit_hits += 1
                raise
            self.call_count += 1
            self._record_usage(model_name, getattr(response, "usage", None))
            return response.choices[0].message.content or ""

        try:
            return _call_api()
        except RateLimitError as e:
            raise LLMRateLimitError(f"Groq rate limit persisted on {model_name}: {e}") from e
        except APIConnectionError as e:
            raise LLMError(f"Could not reach Groq after {self._settings.llm_max_retries} attempts: {e}") from e
        except APIError as e:
            raise LLMError(f"Groq API error: {e}") from e

    def _complete_with_fallback(
        self,
        model_name: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> tuple[str, str]:
        """Run ``_complete`` on *model_name*, then on each fallback model while rate-limited.

        Returns:
            The response text and the model that produced it.

        Raises:
            LLMRateLimitError: If every model in the chain is rate-limited.
        """
        chain = self._settings.fallback_chain(model_name)
        for position, candidate in enumerate(chain):
            try:
                text = self._complete(candidate, messages, temperature, max_tokens, json_mode)
            except LLMRateLimitError:
                if position == len(chain) - 1:
                    raise
                logger.warning("%s is rate-limited; falling back to %s", candidate, chain[position + 1])
                continue
            if candidate != model_name:
                self.fallback_count += 1
            return text, candidate
        raise AssertionError("fallback chain always contains the requested model")

    def _record_model(self, requested: str, answered: str, cached: bool) -> None:
        if self._usage is not None:
            self._usage.record(requested, answered, cached)

    def _key_for(
        self, model_name: str, prompt: str, system_prompt: str, temperature: float, max_tokens: int, mode: str
    ) -> str:
        return self._cache_key({
            "model": model_name, "prompt": prompt, "system_prompt": system_prompt,
            "temperature": temperature, "max_tokens": max_tokens, "mode": mode,
            "reasoning_effort": self._reasoning_effort(model_name),
        })

    def _record_usage(self, model_name: str, usage: Any) -> None:
        if not usage:
            logger.info("Groq call (%s) completed (call #%d)", model_name, self.call_count)
            return
        p_tok = getattr(usage, "prompt_tokens", 0) or 0
        c_tok = getattr(usage, "completion_tokens", 0) or 0
        t_tok = getattr(usage, "total_tokens", 0) or (p_tok + c_tok)
        self.total_prompt_tokens += p_tok
        self.total_completion_tokens += c_tok
        self.total_tokens += t_tok
        logger.info(
            "Groq call (%s): prompt=%d, completion=%d, total=%d tokens (calls=%d, cumulative=%d)",
            model_name, p_tok, c_tok, t_tok, self.call_count, self.total_tokens,
        )

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a text completion from Groq API with caching, retries and model fallback."""
        model_name = model or self._settings.groq_fast_model
        cached = self._get_from_cache(
            self._key_for(model_name, prompt, system_prompt, temperature, max_tokens, "text")
        )
        if cached is not None:
            self.cache_hits += 1
            self._record_model(model_name, model_name, cached=True)
            return cached

        messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
        messages.append({"role": "user", "content": prompt})
        result, answered = self._complete_with_fallback(model_name, messages, temperature, max_tokens, json_mode=False)
        self._record_model(model_name, answered, cached=False)
        # Cached under the model that answered: a later request for the primary
        # model asks the primary model again instead of replaying a fallback answer.
        self._write_to_cache(self._key_for(answered, prompt, system_prompt, temperature, max_tokens, "text"), result)
        return result

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate a JSON object from Groq (JSON mode), with one repair attempt on parse failure."""
        model_name = model or self._settings.groq_fast_model
        cache_key = self._key_for(model_name, prompt, system_prompt, temperature, max_tokens, "json")
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            try:
                parsed = json.loads(cached)
                self.cache_hits += 1
                self._record_model(model_name, model_name, cached=True)
                return parsed
            except json.JSONDecodeError:
                logger.warning("Ignoring corrupt cache entry %s", cache_key)

        sys_msg = system_prompt or "You are a helpful assistant that responds strictly in valid JSON."
        if "JSON" not in sys_msg:
            sys_msg += "\nRespond ONLY with a valid JSON object."
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        raw_text, answered = self._complete_with_fallback(model_name, messages, temperature, max_tokens, json_mode=True)
        self._record_model(model_name, answered, cached=False)

        try:
            parsed = self._parse_json_object(raw_text)
        except json.JSONDecodeError as err:
            logger.warning("JSON decode failed; attempting one repair call. Raw: %s", raw_text[:500])
            repaired = self.generate(
                f"Fix this invalid JSON and return ONLY the valid JSON object:\n\n{raw_text}",
                system_prompt="Output valid JSON only.",
                model=answered,
            )
            try:
                parsed = self._parse_json_object(repaired)
            except json.JSONDecodeError as repair_err:
                raise LLMResponseParseError(raw_text, f"Could not parse or repair JSON: {repair_err}") from err

        self._write_to_cache(
            self._key_for(answered, prompt, system_prompt, temperature, max_tokens, "json"),
            json.dumps(parsed, ensure_ascii=False),
        )
        return parsed

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        parsed = json.loads(_extract_json_substring(text))
        return parsed if isinstance(parsed, dict) else {"data": parsed}
