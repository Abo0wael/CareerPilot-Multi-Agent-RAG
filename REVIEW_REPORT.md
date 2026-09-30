# CareerPilot: Review Report

> **Author:** Ahmed (CS student) | **State:** final, after the architecture, honesty and evaluation fixes (2026-10-01)
> **Tests:** 130 passing (`C:\Anaconda\envs\careerpilot\python.exe -m pytest`), none of which call Groq.

This report records what the system does, what was wrong when it was handed over, what was changed, and the measured results. The README has the user-facing overview; `outputs/evaluation/evaluation_report.md` has the generated evaluation tables.

---

## 1. Environment

- Windows, conda env `careerpilot`, Python 3.11.16 (`C:\Anaconda\envs\careerpilot\python.exe`).
- Dependencies are in `requirements.txt`. `groq` is now declared directly; the unused `langchain-groq` / `langchain-core` were removed.
- `.env` holds `GROQ_API_KEY`, `GROQ_FAST_MODEL=openai/gpt-oss-20b`, `GROQ_AGENT_MODEL=openai/gpt-oss-120b`, and optionally `ADMIN_TOKEN`, per-step models and `GROQ_REASONING_EFFORT` (see `.env.example`).
- Never committed: `data/`, `index/`, `.env`, `.llm_cache/`. `outputs/evaluation/` **is** committed (graded deliverable).

## 2. File tree (source)

```
src/
  domain/          entities.py, exceptions.py, interfaces.py (13 ports), scoring.py (MAX aggregation, weighted fusion)
  application/     build_profile, match_jobs, analyze_gap, tailor_cv, verify_tailored_cv, ingest_jobs
  agents/          base.py, profile/matcher/gap/tailor/verifier agents, graph.py (routing), workflow.py (facade)
  infrastructure/  config.py, chunking/, data/loader.py (JobSource), parsing/cv_parser.py,
                   search/sqlite_index.py (Retriever, SearchIndexWriter, IndexStatsReader, JobRepository),
                   retrieval/expander.py, retrieval/reranker.py,
                   llm/client.py, llm/{profile_extractor, gap_analyzer, cv_tailor, claim_verifier}.py,
                   llm/formatting.py, llm/prompts/
  api/             main.py (endpoints), schemas.py, error_handlers.py, dependencies.py (composition root)
scripts/           build_index.py, evaluate.py, warm_demo_cache.py, metering.py, eda_chunking.py, analysis/
tests/             130 tests + fakes.py + conftest.py
```

---

## 3. Audit findings at handover, and how each was fixed

| # | Finding (with evidence at the time) | Fix |
|---|---|---|
| 1 | **Verifier counted "unsupported" as supported:** `"supp" in verdict` matches "unsupported". The reported 100% faithfulness was wrong; the cached raw verdicts showed 34/38. It also marked every bullet supported when the LLM returned no claims. | Strict enum parsing (`ClaimVerdict.from_llm`), a new `UNVERIFIED` verdict for missing or malformed output, verdicts matched by `bullet_id`, unsupported bullets moved to `removed_bullets`. Regression tests added. |
| 2 | **Dependency rule broken:** `application` imported `agents` (3 use cases) and `infrastructure` (`match_jobs`). Agents and use cases imported each other. | New ports `ProfileExtractor`, `GapAnalyzer`, `CVTailor`, `ClaimVerifier` with Groq implementations in infrastructure. Use cases depend only on ports. `aggregate_chunk_scores_by_job` moved to `domain/scoring.py`. Enforced by `tests/test_architecture.py`. |
| 3 | **LangGraph graph unused by the API** (only a test called it). `graph.py` had an always-true edge (`"tailor_agent" if "full_pipeline" else END`), so a `gap` request also ran tailor and verifier. The router ignored `request_type`, and a router mutated state. | Every reasoning endpoint runs the graph through `CareerPilotWorkflow`. Routing is by `request_type` with pure routers. New `/pipeline`. Tests prove `gap` runs only the gap agent. |
| 4 | **Exceptions swallowed:** every agent caught `Exception`, so a Groq 429 produced an empty "fallback" result instead of 503. | Agents and services no longer catch. Only unreadable LLM output in the optional expander/reranker falls back (and it is logged). Groq connection errors are wrapped in `LLMError`. Handlers: 503 (rate limit), 502 (LLM error), 404, 400. |
| 5 | **`/ingest` could not work:** `execute(..., clear_existing=True)` did not exist on the use case, `KaggleDataLoader()` was built without its required settings, `load_tech_subset()` did not exist, `settings.chunk_max_length` did not exist, and the use case cleared the `jobs` table without refilling it. It was also unprotected. | `IngestJobsUseCase(job_source, chunker, index_writer).execute(clear_existing)` stores jobs and chunks. `KaggleDataLoader` implements `JobSource`. The endpoint requires `X-Admin-Token` (from `ADMIN_TOKEN`; disabled if unset). `build_index.py` reuses the same use case, and a rebuild reproduced 13,975 jobs / 91,190 chunks. |
| 6 | **Reranker mixed scales:** it sorted LLM scores (0–100) together with raw BM25 scores, and dropped string `job_id`s. | Sorted by LLM score; BM25 only breaks ties; unscored jobs come after, in BM25 order; string ids accepted. |
| 7 | **Wiring outside the composition root:** `/health` ran SQL through a private `_get_conn()`, and `/ingest` built the loader in the endpoint. | `IndexStatsReader` port, with all wiring in `dependencies.py`. |
| 8 | **Evaluation bugs:** the frontend fixture name was wrong (so 5 profiles, not 6); `total_fixtures_evaluated` was hard-coded to 6; the label used substring matching (`"ml"` matched "html"); the "whole posting" baseline used a different query (first skill only) on unsectioned postings only, without dedup. | All fixed (section 7). |
| 9 | **Found during the work:** the SQLite connection was shared across FastAPI worker threads with the default `check_same_thread=True`, which crashed on shutdown. | `check_same_thread=False` (the module is in serialized mode, `threadsafety == 3`), with a test. |
| 10 | **Documentation claims the code did not support:** "Production-Grade", "100% faithfulness … claims removed", "use cases never import SQLite/Groq", a Mermaid diagram with wrong arrows, "6 disciplines", "36.5% without headers" (measured: 41.1%), vector-DB claims (Java/JavaScript confusion, "hallucinated relevance", "requires local models"). | README and this report rewritten from measured data. |

The dead `InterviewCoachAgent` was removed: it had no endpoint and its prompt never received the gap report. The duplicated job-fetch/error blocks and the duplicated retry code in the Groq client were merged, `main.py` was split (schemas, handlers, endpoints), and unused imports were removed.

---

## 4. Tech subset and chunking (data)

- **Subset:** title keywords, or an ENG/IT skill tag together with a technical title qualifier, minus an exclusion list (civil/mechanical engineering, sales, clinical, legal…). Industry is not used alone. Result: **13,975 postings**.
- **Subset precision:** 47/50 = 94% on a random audit (seed 2026) made by the previous tool. It was **not re-audited**, and one "tech" label ("Senior Strategic Partner Manager, Cloud") is debatable.
- **EDA** (`scripts/eda_chunking.py`, re-run): median description 3,130 characters; 91.1% contain line breaks; **58.9%** have at least one section header and 34.8% have two or more. The index agrees: 58.9% of postings are chunked by sections and 41.1% only with the `full` fallback.
- **Chunker:** headers → sections; hierarchical split `\n\n` → `\n` → sentence → word → hard cap at 800; merge fragments under 100 characters when the merge fits.

| Section | Chunks | Avg length | Max | > 800 |
|---|---|---|---|---|
| full | 47,656 | 587 | 800 | 0 |
| requirements | 12,524 | 532 | 800 | 0 |
| responsibilities | 10,358 | 550 | 800 | 0 |
| nice_to_have | 9,107 | 563 | 800 | 0 |
| about (not searched) | 5,800 | 591 | 800 | 0 |
| benefits (not searched) | 5,745 | 528 | 800 | 0 |
| **Total** | **91,190** | | **800** | **0** |

3,069 chunks (3.37%) remain under 100 characters.

**Index:** FTS5 external-content table, `porter unicode61` tokenizer. The last rebuild took 66.3 s (CSV loading included), produced 174.0 MB after `VACUUM`, and made 0 LLM calls. The earlier 47.6 s / 156.4 MB figures could not be reproduced.

---

## 5. Retrieval and agents

- **Query:** preferences + first five profile skills → Groq expansion (20b) → BM25 over non-benefits/about chunks (top 50 chunks) → job score = MAX over its chunks → full postings → Groq rerank of the top 20 (20b) → top 10.
- **Expansion options:**
  - `expansion_weight=None` (deployed): OR all terms.
  - `expansion_weight=w`: `original + w·expansion` fusion. Evaluated and rejected (section 7).
- **Agents:** thin LangGraph nodes over one use case each. Models: profile 20b; gap, tailor and verifier 120b; `reasoning_effort=low`.
- **Prompt budget:** gap and tailor prompts receive only the requirement/responsibility/nice-to-have sections of the posting (`llm/formatting.py`), capped at 4,000 and 2,500 characters.

---

## 6. Error handling

| Error | HTTP |
|---|---|
| `LLMRateLimitError` (after retries that wait for Groq's `retry-after`) | 503 + `Retry-After` |
| `LLMError`, `LLMResponseParseError` | 502 |
| `JobNotFoundError` | 404 |
| `CVParsingError`, `EmptyFieldError`, `InvalidEntityError`, `WorkflowStateError` | 400 |
| `IndexNotFoundError` | 503 |
| other `CareerPilotError` | 500 |

API tests run the real graph with fake ports and check that a 429 raised inside a node reaches the client as 503.

---

## 7. Evaluation (final numbers)

Details and interpretation are in the README (section 6). Generated tables are in `outputs/evaluation/evaluation_report.md`; the earlier runs are kept in `outputs/evaluation/runs/`.

**Retrieval, macro Precision@10** (6 profiles, whole-word title-family label; the original label is in brackets):

| BM25 sections | BM25 whole posting | + expansion OR | + expansion weighted | Full pipeline |
|---|---|---|---|---|
| 0.633 (0.617) | 0.650 (0.633) | 0.717 (0.667) | 0.600 (0.583) | **0.733** (0.700) |

- **Sections vs whole postings:** effectively equal (2 wins each, 2 ties). A chunking precision gain is **not** shown.
- **Expansion:** helps data_scientist a lot (0.10 → 0.80), hurts devops, frontend and software engineer, and flipped sign compared with the previous run. It is high-variance.
- **Weighted-fusion fix:** 0.600 macro. Rejected.
- **data_scientist:** the root cause is the query built from the first five skills (`Python R SQL Tableau Power BI`). The label is only slightly too narrow.
- **Significance:** no difference is significant with 6 profiles (paired sign test p ≥ 0.375).

**Faithfulness of real tailoring** (56 bullets):

| Run | Tailor setting | Supported |
|---|---|---|
| 1 | 20b | 80.4% |
| 2 | 20b + strict prompt | 83.9% |
| 3 (deployed) | 120b + strict prompt | **96.4%** (54/56; the 2 removed bullets are real fabrications) |

**Adversarial verifier test:** 24/24 planted fabrications caught (skill, metric, employer, certification; 6 each); 24/24 verbatim controls supported. The fabrications are blatant, so this measures recall on obvious inventions, not on subtle exaggeration.

## 8. Demo safety

- **Limits:** 8,000 tokens per minute per model (both models, read from Groq's headers).
- **One cold `/pipeline`:** 6 calls, 11,968 tokens (20b: 6,381, 120b: 5,587), 23.7 s, 0 × 429.
- **Demo:** `scripts/warm_demo_cache.py` pre-runs the demo CV through the API wiring. Afterwards all five reasoning endpoints for that CV made 0 Groq calls (12 cache hits).

## 9. Tests (130)

| File | Tests | Covers |
|---|---|---|
| test_architecture.py | 5 | dependency rule for every layer, plus a self-test of the checker |
| test_graph.py | 11 | agents run per request type (`gap` ≠ tailor/verifier), pipeline stop, pure routers, errors propagate |
| test_api_endpoints.py | 17 | all endpoints, removed bullets, 503/502/404/400 through the real graph, `/ingest` token 401/403/200 |
| test_verification.py | 12 | strict verdict parsing, "unsupported" regression, removal of unsupported bullets |
| test_infrastructure_llm.py | 28 | CV parser, Groq client (cache, JSON, 429 → retry-after, connection errors, reasoning_effort), expander, reranker ordering, Groq ports |
| test_use_cases.py | 6 | use cases on fakes, tailor → verify removes fabrication, weighted expansion |
| test_search_index.py | 16 | FTS5 index, scopes, filters, MAX aggregation, ingest stores jobs + chunks, cross-thread use |
| test_chunkers.py | 18 | section/paragraph/hierarchical chunking, caps and merges |
| test_entities.py | 16 | entity invariants, model aliases |
| test_fts5.py | 1 | FTS5 available |

## 10. Deviations from the specification

- **Data path:** data lives in `data/` (not `data/raw/`); `Settings.data_raw_dir` points there.
- **Subset size:** 13,975 postings rather than about 20,000, a precision-first trade-off.
- **Experience level:** missing experience levels are filled by title/description rules (no LLM).

## 11. Known limitations

- **Evaluation:** 6 synthetic CVs, a weak label, no human judgments.
- **Query:** it depends on the order of extracted skills, and LLM output is not fully deterministic, so cold-cache results can differ between runs.
- **Verifier:** checks bullets but not the tailoring summary line. Its false-alarm rate on real tailoring is unmeasured.
- **Data:** duplicate reposts appear in the dataset.
