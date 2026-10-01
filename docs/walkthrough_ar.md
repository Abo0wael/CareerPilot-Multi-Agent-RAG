# إيه اللي بيحصل لما حد ينادي `POST /pipeline`؟

شرح خطوة بخطوة: ملف ملف وفنكشن فنكشن، من أول ما الـ request يوصل لحد ما الـ JSON يرجع.
(أسماء الكود بالإنجليزي زي ما هي في المشروع.)

---

## الصورة الكبيرة في سطرين

```
HTTP  ->  api/main.py  ->  agents/workflow.py  ->  LangGraph (agents/graph.py)
      ->  5 agents بالترتيب: Profile -> Matcher -> Gap -> Tailor -> Verifier
      ->  كل agent بينادي use case واحد (application/)
      ->  الـ use case بيكلّم ports (domain/interfaces.py) بس
      ->  التنفيذ الفعلي (SQLite, Groq) في infrastructure/ واتحقن من api/dependencies.py
      ->  النتيجة ترجع لنفس الطريق وتتحول JSON في api/schemas.py
```

القاعدة المهمة: **الاعتماد بيمشي لجوه بس**:

`api -> agents -> application -> domain <- infrastructure`

الـ use case عمره ما بيعرف إن فيه SQLite أو Groq أصلاً. هو عارف بس الـ interface (الـ port). وفيه test اسمه `tests/test_architecture.py` بيوقّع البيلد لو حد كسر القاعدة دي.

---

## 0) قبل أي request: التجميع (Composition Root)

**الملف:** `src/api/dependencies.py`

أول مرة endpoint يطلب `get_workflow`، الفنكشن `build_workflow(settings, llm)` بتتنادى مرة واحدة بس (عن طريق `_singleton`) وبتعمل الآتي:

- تعمل الحاجات الحقيقية (concrete):
  - `SQLiteFTSIndex` (البحث) و`SQLiteJobRepository` (الوظايف كاملة)
  - `GroqClient` (الكلام مع Groq، ومعاه cache و retry)
  - `GroqQueryExpander` و`GroqReranker` (بيستخدموا الموديل السريع 20b)
  - `GroqProfileExtractor` (20b)، و`GroqGapAnalyzer` و`GroqCVTailor` و`GroqClaimVerifier` (120b)
  - `UniversalCVParser`
- تحطهم جوه الـ use cases: `BuildProfileUseCase` و`MatchJobsUseCase` و`AnalyzeGapUseCase` و`TailorCVUseCase` و`VerifyTailoredCVUseCase`.
- تحط كل use case جوه الـ agent بتاعه، وتبني الـ graph بـ `create_careerpilot_graph(...)`.
- تلفّ الـ graph في `CareerPilotWorkflow`.

يعني **ده المكان الوحيد اللي فيه `new` لكلاسات حقيقية** (غير السكريبتات). ده بالظبط الـ Dependency Inversion.

---

## 1) الـ endpoint

**الملف:** `src/api/main.py`، **الفنكشن:** `run_pipeline(file, raw_text, preferences, top_k, workflow)`

1. FastAPI بيستلم multipart: إما ملف CV (`.pdf` أو `.txt`) أو `raw_text`، ومعاهم `preferences` و`top_k`.
2. `_read_cv(file, raw_text)`:
   - لو فيه ملف، بترجع `{"file_bytes": ..., "filename": ...}`.
   - لو فيه نص، بترجع `{"raw_text": ...}`.
   - لو مفيش ولا ده ولا ده، بترمي `HTTPException 400`.
3. بينادي `workflow.run_pipeline(**cv_input, preferences=..., top_k=...)`.

---

## 2) الـ facade اللي بيشغّل الـ graph

**الملف:** `src/agents/workflow.py`، **الكلاس:** `CareerPilotWorkflow`

- `run_pipeline(...)` بتبني الـ state الأولاني:
  ```python
  {"request_type": "pipeline", "preferences": ..., "top_k": ...,
   "cv_file_bytes": ..., "cv_filename": ...}     # أو "raw_cv_text"
  ```
  الجزء الخاص بالـ CV بيتعمل في `_cv_input(...)`.
- `_run(state)` بتنادي `self._graph.invoke(state)`، ودي اللي بتشغّل LangGraph.
- في الآخر بتحوّل الـ state النهائي لـ `PipelineResult(profile, matches, target_job_id, gap_report, tailored_cv)`.

---

## 3) الـ graph: مين يشتغل وإمتى؟

**الملف:** `src/agents/graph.py`

- `AgentWorkflowState` (TypedDict): شكل الـ state اللي بيتنقل بين الـ nodes.
- `RequestType`: الأنواع `profile / match / gap / tailor / pipeline`.
- الـ routers **pure functions**، بتقرا الـ state وماتعدّلش فيه:
  - `route_request`: أول node حسب `request_type`. للـ pipeline تبقى `profile_agent`.
  - `route_after_profile`: في الـ pipeline تروح لـ `matcher_agent`، غير كده `END`.
  - `route_after_matcher`: في الـ pipeline **ولو فيه matches** تروح لـ `gap_agent`، غير كده `END`. لو مفيش ولا وظيفة مناسبة، نقف هنا.
  - `route_after_gap`: في الـ pipeline تروح لـ `tailor_agent`.
  - `tailor_agent -> verifier_agent`: edge ثابت، عشان التعديل **عمره ما يرجع من غير تحقق**.
- `create_careerpilot_graph(...)`: بتسجّل الـ 5 nodes والـ edges وتعمل `compile()`.

كل agent بيرث من `BaseAgent` (`src/agents/base.py`):

- LangGraph بينادي `agent(state)`، و`__call__` بتسجّل log وتنادي `run(state)`. دي الـ polymorphism.
- `run` بترجع **بس المفاتيح اللي عملتها**، وLangGraph بيدمجها في الـ state.
- `_require(state, key)`: لو حاجة ناقصة بترمي `WorkflowStateError`.

---

## 4) Node 1: `ProfileAgent`

**الملف:** `src/agents/profile_agent.py`، **الفنكشن:** `run(state)`

- لو فيه `cv_file_bytes` بتنادي `BuildProfileUseCase.execute(bytes, filename)`، ولو فيه نص بتنادي `execute_from_text(text)`.
- بترجع `{"profile": CandidateProfile}`.

**الـ use case:** `src/application/build_profile.py`، `BuildProfileUseCase`

1. `self._cv_parser.parse(file_bytes, filename)`، والـ port هو `CVParser`.
   - التنفيذ: `src/infrastructure/parsing/cv_parser.py`، `UniversalCVParser.parse`.
   - الـ PDF بيروح لـ `_parse_pdf` (pypdf)، والنص بيروح لـ `_parse_text`.
   - أي مشكلة بترمي `CVParsingError`، ودي بتوصل الـ API كـ 400.
2. `self._extractor.extract(raw_text)`، والـ port هو `ProfileExtractor`.
   - التنفيذ: `src/infrastructure/llm/profile_extractor.py`، `GroqProfileExtractor.extract`.
   - بتملى `PROFILE_USER_PROMPT_TEMPLATE` (من `llm/prompts/profile_prompts.py`) بنص الـ CV، وبحد أقصى 12,000 حرف.
   - بتنادي `llm.generate_json(...)` على الموديل 20b (شوف الجزء 9 عن `GroqClient`).
   - بتحوّل الـ JSON لـ `CandidateProfile` بمساعدة `_text` و`str_list` و`dict_list`، اللي بيشيلوا الحاجات الفاضية والـ "Not specified".

---

## 5) Node 2: `MatcherAgent`

**الملف:** `src/agents/matcher_agent.py`، **الفنكشن:** `run(state)`

- بتنادي `MatchJobsUseCase.execute(profile, preferences, top_k)`.
- بترجع `{"matches": [...], "job_id": <أول وظيفة>}`. أول وظيفة دي هي اللي هنعمل عليها gap و tailor.

**الـ use case:** `src/application/match_jobs.py`، `MatchJobsUseCase.execute`

1. `_extract_query_terms`: بتبني الـ query من الـ preferences وأول 5 skills.
   مثال: `Java Go Python Spring Boot gRPC`.
2. `_extract_filters`: لو كتبت "remote" أو مستوى خبرة، بتعمل filter.
3. `self._query_expander.expand(query)`، والـ port هو `QueryExpander`.
   - التنفيذ: `src/infrastructure/retrieval/expander.py`، `GroqQueryExpander.expand` (Groq 20b).
   - بتضيف من 3 لـ 6 كلمات قريبة (زي Kubernetes و Docker).
   - لو رد الـ LLM مش مقروء، بترجع الـ query الأصلي. لكن الـ 429 **مابيتبلعش**.
4. `self._retrieve(query)`، ودي بتنادي `self._retriever.search(query, top_n=50)`، والـ port هو `Retriever`.
   - التنفيذ: `src/infrastructure/search/sqlite_index.py`، `SQLiteFTSIndex.search`.
   - `_clean_fts_query` بتنضّف الكلمات، وبعدين بتوصلهم بـ `OR`.
   - SQL: `chunks_fts MATCH ?` والـ score هو `-bm25(chunks_fts)`. السالب عشان الأعلى يبقى الأحسن.
   - الـ chunks بتاعة `benefits` و`about` مستبعدة.
   - الناتج أحسن 50 chunk، وكل واحد `ScoredChunk`.
5. `aggregate_chunk_scores_by_job(chunks, "max")` في `src/domain/scoring.py`:
   - score الوظيفة = **أعلى** chunk فيها (MAX).
   - ده logic صافي، عشان كده مكانه في الـ domain.
6. `self._job_repo.get_by_ids(ids)`، والـ port هو `JobRepository`، والتنفيذ `SQLiteJobRepository.get_by_ids`: بيجيب الوظايف كاملة (parent documents).
7. `self._reranker.rerank(profile, matches, top_k)`، والـ port هو `Reranker`.
   - التنفيذ: `src/infrastructure/retrieval/reranker.py`، `GroqReranker.rerank`.
   - `_build_prompt`: أول 20 وظيفة، من كل وظيفة أول 600 حرف، ومعاهم ملخص الـ profile.
   - Groq 20b بيدّي score من 0 لـ 100 وسبب لكل وظيفة.
   - `_as_job_id` بتقبل الـ id رقم أو نص.
   - الترتيب: **بدرجة الـ LLM**، والـ BM25 بيكسر التعادل بس. الوظايف اللي الـ LLM ماقيّمهاش بتيجي بعدهم. **عمرنا ما بنخلط مقياسين.**

---

## 6) Node 3: `GapAnalyzerAgent`

**الملف:** `src/agents/gap_agent.py`

- `run` بتاخد `profile` و`job_id` (من الـ Matcher) وتنادي `AnalyzeGapUseCase.execute`.
- بترجع `{"gap_report": GapReport}`.

**الـ use case:** `src/application/analyze_gap.py`

1. `job_repository.get_by_id(job_id)`. لو مش موجودة بترمي `JobNotFoundError`، ودي بتوصل الـ API كـ 404.
2. `gap_analyzer.analyze(profile, job)`، والـ port هو `GapAnalyzer`.
   - التنفيذ: `src/infrastructure/llm/gap_analyzer.py`، `GroqGapAnalyzer.analyze` (Groq 120b).
   - `relevant_job_text(job, 4000)` من `llm/formatting.py` بتبعت **أقسام المتطلبات بس** (requirements و responsibilities و nice_to_have)، عن طريق نفس `SectionChunker` بتاع الـ indexing. ده توفير tokens.
   - `experience_lines` و`project_lines` بيلخّصوا الـ CV.
   - `_gap_items` بيحوّل الـ JSON لـ `GapItem` (فيه matched ومعاه evidence من الـ CV، أو missing).

---

## 7) Node 4: `TailorAgent`

**الملف:** `src/agents/tailor_agent.py`، وبترجع `{"tailored_cv": TailoredCV}` **لسه من غير تحقق**.

**الـ use case:** `src/application/tailor_cv.py`، `TailorCVUseCase.execute`

- بيجيب الـ job، وبعدين `cv_tailor.tailor(profile, job)`، والـ port هو `CVTailor`.
- التنفيذ: `src/infrastructure/llm/cv_tailor.py`، `GroqCVTailor.tailor` (Groq 120b).
  - `_source_bullets`: bullets الخبرة والمشاريع من الـ CV، بحد أقصى 10.
  - `relevant_job_text(job, 2500)`.
  - الـ prompt (`tailor_prompts.py`) بيمنع صراحةً إن الموديل ينقل أداة من الوظيفة للـ bullet، زي إنه يغيّر Tableau لـ Power BI.

---

## 8) Node 5: `VerifierAgent`: الحارس

**الملف:** `src/agents/verifier_agent.py`، وبترجع `{"tailored_cv": ...}` بعد التحقق.

**الـ use case:** `src/application/verify_tailored_cv.py`، `VerifyTailoredCVUseCase.execute(original_cv_text, tailored_cv)`

1. `claim_verifier.verify(cv_text, bullets)`، والـ port هو `ClaimVerifier`.
   - التنفيذ: `src/infrastructure/llm/claim_verifier.py`، `GroqClaimVerifier.verify` (Groq 120b).
   - بيرقّم الـ bullets: `[1] ...` و`[2] ...`.
   - الموديل بيرجّع `{"bullet_id": n, "verdict": ..., "evidence": ...}`.
   - الربط **بالرقم** مش بالنص.
   - `ClaimVerdict.from_llm` (في `domain/entities.py`) بتقبل `"supported"` أو `"unsupported"` **بالظبط** وبس. أي حاجة تانية تبقى `unverified`، **عمرها ما تبقى supported**. ده اللي صلّح الـ bug القديم بتاع `"supp" in verdict`.
2. `tailored_cv.apply_verification(report)` في `domain/entities.py`:
   - بيحط الـ verdict والـ evidence على كل bullet.
   - أي bullet **unsupported بيتشال** من `bullets` ويتحط في `removed_bullets`.

بعد الـ Verifier، الـ graph بيوصل لـ `END`.

---

## 9) إزاي أي كلام مع Groq بيحصل؟

**الملف:** `src/infrastructure/llm/client.py`، `GroqClient.generate_json`

1. `_cache_key`: بتعمل SHA-256 للـ (model, prompt, system prompt, temperature, max_tokens, mode, reasoning_effort).
2. `_get_from_cache`: لو الرد موجود في `.llm_cache/` بترجّعه على طول، **من غير أي call**. عشان كده الـ demo بعد `warm_demo_cache.py` بيعمل صفر calls.
3. لو مش موجود، بتنادي `_complete_with_fallback(...)`، ودي بتجرب `_complete(...)` على كل موديل في `fallback_chain` بالترتيب:
   - بتطلب JSON mode، و`reasoning_effort="low"` لموديلات gpt-oss، عشان تقلل الـ tokens المخفية.
   - `@retry` (tenacity) على 429 و connection errors. `_wait_before_retry` بتستنى **قد ما Groq قال في `retry-after`**. ولو Groq طلب يستنى أكتر من 60 ثانية (زي الـ limit اليومي)، `_stop_retrying` بتوقف على طول.
   - لو الموديل لسه عامل 429 بعد المحاولات، نفس الطلب بيروح للموديل اللي بعده: `gpt-oss-120b` ← `gpt-oss-20b` ← `qwen/qwen3.8-27b` (من `GROQ_FALLBACK_MODELS`).
   - لو كل الموديلات عاملة 429 تبقى `LLMRateLimitError`، والـ connection أو API error تبقى `LLMError`.
   - `_record_usage` بتعدّ الـ tokens، و`_record_model` بتسجل مين اللي رد فعلاً (للـ `model_calls`).
4. `_parse_json_object` بتقرا الـ JSON. لو فشلت، فيه محاولة إصلاح واحدة على نفس الموديل اللي رد، ولو فشلت كمان بترمي `LLMResponseParseError`.
5. `_write_to_cache` بتحفظ الرد **باسم الموديل اللي رد**. يعني رد الـ fallback عمره ما بيترجع على إنه رد الموديل الأساسي، والـ cache بتاع الديمو زي ما هو.

**مين رد على كل agent؟** `ContextModelUsageTracker` (في `llm/model_usage.py`) بيستخدم context variables، فكل request ليه list لوحده. الـ graph بيشغّل كل agent جوه `tracker.step(agent.name)`، والـ endpoint بيجمع الـ calls في `tracker.collect()` ويرجّعها في `model_calls`.

---

## 10) الرجوع

1. `graph.invoke` بيرجّع الـ state النهائي لـ `CareerPilotWorkflow.run_pipeline`، ودي بتعمل `PipelineResult`.
2. في `run_pipeline` في `main.py`، كل حاجة بتتحول لـ Pydantic في `src/api/schemas.py`:
   - `CandidateProfileSchema.from_domain`
   - `MatchResponse.from_domain`، وفيها `MatchedJobItem` لكل وظيفة.
   - `GapResponse.from_domain`
   - `TailorResponse.from_domain`: `bullets` (فيها verdict لكل واحدة)، و`removed_bullets`، و`verification` (الأعداد: supported و unsupported و unverified).
   - `model_calls`: لكل LLM request، الـ agent والموديل المطلوب والموديل اللي رد، وهل جه من الـ cache.
3. FastAPI بيرجّع الـ JSON بـ 200.

## 11) ولو حصل خطأ في أي نقطة؟

محدش بيبلع الأخطاء: الـ exception بيطلع من الـ node، ويعدّي من `graph.invoke`، ويوصل لـ FastAPI. الـ handlers في `src/api/error_handlers.py`:

| الخطأ | الرد |
|---|---|
| `LLMRateLimitError` (كل موديلات الـ fallback عاملة 429) | **503** + `Retry-After: 30` |
| `LLMError` / `LLMResponseParseError` | **502** |
| `JobNotFoundError` | **404** |
| `CVParsingError`، أخطاء الـ validation، `WorkflowStateError` | **400** |

---

## 12) ملخص الأرقام في run واحد من غير cache

| الخطوة | الموديل | tokens | زمن |
|---|---|---|---|
| Profile | 20b | 1,595 | 1.3s |
| Expansion | 20b | 489 | 0.6s |
| Rerank | 20b | 4,297 | 1.3s |
| Gap | 120b | 1,886 | 1.7s |
| Tailor | 120b | 1,886 | 6.0s |
| Verify | 120b | 1,815 | 12.8s |
| **الإجمالي** | | **11,968** | **23.7s** |

كل موديل ليه حد 8,000 token في الدقيقة، وكل موديل هنا تحت الحد (6,381 و5,587). ومع الـ cache الـ demo بياخد صفر calls.
