# CareerPilot — Handoff to Claude Code

This project was built in a previous tool (Antigravity) and is now handed to you to finish.
Most of the system exists and 71 tests pass. Your job: **audit what exists, then finish the remaining work below.**

Ahmed (a CS student) will present and defend this project, so he must understand every decision.
Code, comments and docs stay in English. Your summaries to Ahmed are in simple **Egyptian Arabic**.

---

## 1. The project
CareerPilot is a multi-agent RAG assistant for **job seekers**.

**Story:** A fresh graduate applies to dozens of jobs and hears nothing back, without knowing why.
Three unanswered questions: *Which jobs actually fit me? What am I missing? How do I present myself for this specific job?*
Recruiters have AI tools that screen thousands of CVs in seconds; candidates have nothing. CareerPilot gives the candidate that power.

**Flow:** upload CV → structured profile → top-10 real matching jobs with grounded reasons → gap report
(matched requirements with CV evidence + missing ones) → tailored CV bullets using only facts from the
original CV → claim-by-claim verification.

## 2. Graded requirements
Clean Code, Clean Architecture, FastAPI backend, multiple agents, real data (Kaggle), data-driven chunking, OOP, SOLID.

## 3. Hard constraints (never violate)
1. **Every model call goes to the Groq API.** No local models (no torch, transformers, sentence-transformers, Ollama, spaCy models).
2. **No embeddings, no vector DB** (Groq offers no embeddings). Do not add Gemini/OpenAI/Cohere/Jina or any other provider.
   Retrieval = **SQLite FTS5 BM25** + Groq LLM query expansion + Groq LLM reranking.
3. No Streamlit.
4. Never commit `data/`, `index/`, `.env`, `.llm_cache/`.
5. **Never fabricate data, labels or results.** Report numbers exactly as measured, including bad ones.

## 4. Environment
- OS: **Windows**. Project path: `D:\My Projects\My projects\careerpilot`.
- Conda env `careerpilot`, Python 3.11. Always run with: `C:\Anaconda\envs\careerpilot\python.exe`
  (a global Python 3.14 also exists on this machine; do not use it).
- Data: `data/` (Kaggle `arshkon/linkedin-job-postings`; `data/postings.csv`, `data/jobs/`, `data/companies/`, `data/mappings/`).
- Index: `index/careerpilot.db`. `.env`: `GROQ_API_KEY`, `GROQ_FAST_MODEL=openai/gpt-oss-20b`, `GROQ_AGENT_MODEL=openai/gpt-oss-120b`.

## 5. Current state (reported by the previous tool — verify, do not trust blindly)
- Layers: `src/domain` (entities, interfaces, exceptions), `src/application` (use cases), `src/infrastructure`
  (config, data loader, chunkers, SQLite FTS5 index, Groq client, expander, reranker, CV parser), `src/agents`
  (BaseAgent, 6 agents, prompts, LangGraph `graph.py`), `src/api` (`main.py`, `dependencies.py`).
- Tech subset: 13,975 postings, 94% precision on a 50-title audit.
- Chunking: SectionChunker (headers) + ParagraphChunker fallback, hierarchical split (`\n\n` → `\n` → sentence → word → hard cap),
  max 800 chars (0% above), tiny-chunk merge at 100 chars, section label preserved. 91,190 chunks.
- Search excludes only `benefits` and `about`; unlabeled `full` chunks stay searchable. Job score = MAX over chunks (FTS5 bm25 sign negated).
- FTS5 external-content table, DB 156 MB, build 47.6 s, zero LLM calls.
- Groq client: tenacity retries, disk cache, JSON repair. Measured TPM limit on gpt-oss-120b: 8,000.
- 71 tests passing. `README.md`, `REVIEW_REPORT.md`, `scripts/evaluate.py`, `outputs/evaluation/` exist.

---

## 6. STEP 1 — AUDIT FIRST (no code changes yet)
Read the codebase and report in Egyptian Arabic, with file/line evidence:
1. Run all tests with the conda interpreter.
2. **Dependency rule:** does anything in `src/domain` import from other layers or frameworks? Does anything in
   `src/application` import from `src/agents`, `src/infrastructure` or `src/api`? (Agents may use use cases; not the reverse.)
3. **Is the LangGraph graph actually used?** Which API endpoints execute `graph.py`, if any, or is it only used in tests?
4. **Hard constraints:** any local model, embeddings, or non-Groq provider anywhere (code, requirements.txt)?
5. Does `api/dependencies.py` really hold all concrete wiring?
6. Any god classes, dead code, duplicated logic, or bare `print` in `src/`.
7. Anything in the README/REVIEW_REPORT that the code does not actually do.

**STOP after the audit and wait for Ahmed's confirmation.**

## 7. STEP 2 — REMAINING WORK (after confirmation)

### 7.1 Architecture fixes
- Fix any dependency-rule violation found in the audit.
- If no endpoint runs the LangGraph graph, route `/tailor` (tailor → verifier) and a new `/pipeline` endpoint
  (profile → match → gap → tailor → verifier) through the graph, so the multi-agent design is real, not decorative.
- Protect `/ingest` with a simple admin token from `.env`.
- Fix the Mermaid diagram so arrows reflect the real dependencies.

### 7.2 Honest evaluation (`scripts/evaluate.py`)
Current results (Precision@10 with a title-family weak label, 5 profiles):
BM25 only 0.64, + expansion 0.62, + rerank 0.68, whole posting 0.58; data_scientist scored 0.0 / 0.0 / 0.1; rerank dropped devops 1.0 → 0.7.
- Include the missing **frontend** fixture (6 profiles total).
- **Fair chunking comparison:** BM25-only on sections vs BM25-only on whole postings (same pipeline stage).
- **Investigate data_scientist:** print the expanded query and the top-10 titles; check whether the family label is too
  narrow (ML Engineer, Machine Learning, AI Engineer...). Fix and document the label definition if needed.
- Investigate why expansion did not help (print expanded queries; check for query drift or too many OR terms diluting BM25).
  Try one principled fix (e.g. weight original terms higher than expansion terms, or cap expansion terms) and report before/after.
- Rewrite "Key Findings" to state exactly what the numbers show, including negative results and possible reasons.
  State that with 6 profiles the differences are not statistically significant.

### 7.3 Verifier test (the 100% faithfulness is circular: an LLM judging an LLM)
Add an adversarial test: plant known fabrications (fake skill, fake metric, fake employer, fake certification) in tailored
output and measure how many the VerifierAgent catches. Report: faithfulness on real tailoring AND recall on planted fabrications.

### 7.4 Demo safety (rate limits)
gpt-oss-120b has 8,000 TPM, but tailor+verify used ~22.5K tokens and gap ~15K. A live demo will likely hit 429.
- Move agents to the fast model where quality allows; trim prompt sizes (send relevant sections, not full postings, where possible).
- Add `scripts/warm_demo_cache.py` that pre-runs the demo CV through the full flow.
- Report tokens and latency per step after the change, and confirm a full demo runs without 429.

### 7.5 README honesty
- Restore the job-seeker story (section 1 above).
- Rewrite "Why No Vector DB?": remove claims that vector DBs hallucinate relevance, confuse Java/JavaScript, or require
  local models. The honest reason: the Groq-only constraint and Groq has no embeddings; lexical retrieval + LLM
  expansion/reranking compensate for semantic matching. Mention the trade-off honestly.
- Remove "Production-Grade", "exemplary codebase", and the "Supervision & Review" line.
- Update evaluation sections and defense talking points to the new honest numbers.
- Update `REVIEW_REPORT.md` header and all sections to the final state.

## 8. Working rules
- Run tests after every change; keep all tests passing and add tests for new behavior (tests never call Groq; use fakes).
- Keep Groq usage low during development (use the cache).
- At the end: summarize in Egyptian Arabic what changed, the final evaluation numbers, and the questions Ahmed should be
  ready to answer in the defense.
