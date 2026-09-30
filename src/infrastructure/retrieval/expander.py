"""Query expander using Groq LLM to enrich search terms with synonyms and tech stacks."""

from __future__ import annotations

import logging
from typing import Optional

from src.domain.entities import SearchQuery
from src.domain.exceptions import LLMResponseParseError
from src.domain.interfaces import LLMClient, QueryExpander

logger = logging.getLogger(__name__)

EXPANDER_SYSTEM_PROMPT = """\
You are an expert technical recruiter and search specialist.
Your task is to expand a technical job search query with 3 to 6 highly relevant domain terms,
including common acronyms, related frameworks, libraries, and core technical skills.
Output MUST be a JSON object with a single key "expanded_terms" containing a list of strings.
Example:
Query: "Python backend developer"
Output: {"expanded_terms": ["FastAPI", "Django", "REST API", "PostgreSQL", "Docker", "AsyncIO"]}
"""


class GroqQueryExpander(QueryExpander):
    """Enriches candidate queries using Groq fast model."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: Optional[str] = None,
    ) -> None:
        self._llm = llm_client
        self._model = model

    def expand(self, query: SearchQuery) -> SearchQuery:
        """Return a new ``SearchQuery`` with ``expanded_terms`` populated."""
        if not query.raw_query.strip():
            return query

        prompt = f'Expand this technical job search query: "{query.raw_query}"'
        try:
            response = self._llm.generate_json(
                prompt=prompt,
                system_prompt=EXPANDER_SYSTEM_PROMPT,
                model=self._model,
                temperature=0.0,
            )
        except LLMResponseParseError as err:
            # Expansion is optional: unreadable output degrades to the original query.
            # Rate limits and API errors are not caught and reach the caller.
            logger.warning("Query expansion output unreadable; using unexpanded query: %s", err)
            return query

        raw_terms = response.get("expanded_terms", [])
        expanded = [
            t.strip()
            for t in (raw_terms if isinstance(raw_terms, list) else [])
            if isinstance(t, str) and t.strip() and t.strip().lower() != query.raw_query.lower()
        ]
        logger.info("Expanded query '%s' -> %s", query.raw_query, expanded)
        return SearchQuery(raw_query=query.raw_query, expanded_terms=expanded, filters=query.filters)
