# Defense notes (for Ahmed)

Short, honest answers to the questions most likely to come up. Every number is in `outputs/evaluation/`.

## Design

**Why no vector database or embeddings?**
- **The constraint:** every model call must go to Groq, and Groq has no embedding models. Adding another provider or a local model was ruled out by the project constraints.
- **What that costs:** dense retrieval matches meaning without shared words; BM25 needs word overlap.
- **How we compensate:** LLM query expansion before search and LLM reranking after it. This covers part of the gap, not all of it.
- **What I would do without the constraint:** a hybrid retriever (BM25 + embeddings).

**Why MAX over the chunks of a job, not SUM or AVG?**
- **SUM** rewards long postings with many chunks (length bias).
- **AVG** dilutes one strong requirements match with weak "about us" chunks.
- **MAX** scores a job by its single best chunk.
- **The trade-off:** matching two sections scores the same as matching one; the LLM reranker then looks at the job as a whole.

**Why chunk at all if Precision@10 was the same (0.633 vs 0.650)?**
- **Precision:** chunking did not improve it with our label. That is the honest answer.
- **Tokens:** sending requirement sections instead of full postings saves 17.1% of reranker job-text tokens overall, and 31.2% on postings that have headers (measured with Groq's own token counts).
- **Prompt content:** the gap and tailoring prompts use the sections, so benefits and about text stay out of them.
- **Scope:** benefits and about chunks are excluded from search.
- **The bigger saving:** most of the reranker's saving comes from truncating to 600 characters, not from chunking.

**Explain the dependency rule and how it is enforced.**
- **The rule:** `api -> agents -> application -> domain <- infrastructure`. Use cases know only the ports (interfaces); SQLite and Groq live in infrastructure and are wired in `api/dependencies.py`.
- **How it is enforced:** `tests/test_architecture.py` parses every import and fails if a layer breaks the rule. It also includes a self-test proving it catches violations.

**Is the multi-agent design real or decorative?**
- **Real.** Every reasoning endpoint runs the LangGraph graph, and routing depends on `request_type`.
- **Tests prove it:** `gap` runs only the gap agent, while `tailor` always runs the verifier (a fixed edge).
- **The UI shows it:** the timeline advances when each real request returns.

## Evaluation

**Did query expansion help?**
- **Not reliably.** The macro average went 0.633 → 0.717, but it helped 3 profiles and hurt 3.
- **Most of the gain is one CV:** data scientist, 0.10 → 0.80.
- **It is unstable:** with the previous run's expansions the effect was negative (0.64 → 0.62).
- **A fix was tried:** weighting the CV's own terms higher gave 0.600, so it was rejected.

**Are the differences significant?**
- **No.** 6 profiles, and the paired sign tests give p ≥ 0.375.
- **Treat them as directions, not proof.**
- **What would make it stronger:** more CVs and human relevance judgments.

**Why was data_scientist at 0.0–0.1 for BM25?**
- **The query:** it is built from the first five skills, and here they were `Python R SQL Tableau Power BI`, which reads like a BI analyst.
- **The label:** only slightly too narrow.
- **The CV:** it also asks for "data analytics and machine learning" roles, which a single-family label cannot express.

**Isn't "LLM judging an LLM" circular?**
- **Partly, yes.** That is why there is an adversarial test: 24 planted fabrications (fake skill, metric, employer, certification), and 24/24 were caught.
- **Controls:** 24/24 real CV bullets were kept.
- **Limit:** the fabrications are blatant; subtle exaggeration is not tested.

**Why is the tailor on the 120b model?**
- **Measured:** on 20b, 80.4% of claims were supported (83.9% with a stricter prompt), because it copied job keywords into bullets (e.g. Tableau → Power BI).
- **On 120b:** 96.4% (54/56), and the 2 removed claims were real fabrications.

**The old report said 100% faithfulness. What happened?**
- **A parsing bug:** `"supp" in verdict` also matches "unsupported", so every rejected claim was counted as supported.
- **The real figure:** the raw verdicts showed 34/38 = 89.5%.
- **Fixed with:** strict enum parsing, an `unverified` state, and unsupported bullets removed.

**How precise is the tech subset?**
- **Measured:** an independent audit of 50 random postings found 82% truly tech (88% if industrial PLC-controls jobs count).
- **The previous tool reported 94%.**
- **Where the errors come from:** the "engineer + ENG skill tag" rule lets in plant/process engineering jobs.

## Operations

**What if Groq rate-limits during the demo?**
- **The limit:** 8,000 tokens per minute per model. One cold full run uses about 6.4K tokens on 20b and 5.6K on 120b, so it fits.
- **The demo CV is pre-cached** (`scripts/warm_demo_cache.py`): it makes 0 Groq calls.
- **If a 429 happens anyway:** the client waits for Groq's `retry-after`; if that still fails, the API returns 503 and the UI shows a countdown.

**Why did the top match change between runs?**
- **Nondeterminism:** LLM outputs are not fully deterministic even at temperature 0, and the query depends on the order of extracted skills.
- **The cache** makes a demo reproducible.

**What would you do next?**
- **Tech subset:** tighten the rule.
- **Reranker:** feed it the requirement sections instead of the first 600 characters.
- **Evaluation:** more profiles plus human labels.
- **Query:** build it from the role and all skills, not just the first five.
- **Deployment:** host the backend (Render) and the UI (Vercel).
