# Deploying CareerPilot for free

- **API:** a Hugging Face **Docker Space** (free CPU tier, public, port 7860, runs as UID 1000).
- **Web UI:** **Vercel**, with `frontend/` as the root directory.

The local quickstart in the README is unchanged. Everything here is opt-in: the deployment files are separate, and the new settings default to the local behaviour (`RATE_LIMIT` empty = off, `MAX_UPLOAD_MB=5`, CORS limited to localhost).

## How it fits together

```
Browser ──> Vercel (Next.js UI) ── fetch ──> https://<user>-<space>.hf.space (FastAPI, Docker)
                                                 ├─ /app/index/careerpilot.db  (prebuilt FTS5 index)
                                                 ├─ /app/.llm_cache/           (demo LLM responses)
                                                 └─ Groq API (GROQ_API_KEY secret)
```

The index (166 MB) and the LLM cache are **git-ignored**. They never go through GitHub. `scripts/deploy_space.py` copies them into a staging folder next to the `Dockerfile` and uploads that folder straight to the Space.

---

## a) Local preparation (once)

Run from the project root, in the `careerpilot` conda env:

```bash
python scripts/build_index.py          # builds index/careerpilot.db (needs data/ from Kaggle)
python scripts/warm_demo_cache.py      # fills .llm_cache/ for Demo 1 and Demo 2; pass 2 must make 0 Groq calls
pip install huggingface_hub            # deploy-time tool only (not in requirements-server.txt)
hf auth login                          # paste a Hugging Face token with write access; it is saved locally
```

The demo cache only hits when the Space uses the **same configuration** as the warming run: the same models, `GROQ_REASONING_EFFORT`, prompt caps and retrieval sizes, and the same index file. If you change `.env` or rebuild the index, run `warm_demo_cache.py` again before deploying.

## b) Stage and upload the Space

Do a dry run first. It stages the folder, prints sizes, and uploads nothing:

```bash
python scripts/deploy_space.py --space-id <hf-user>/careerpilot-api
```

The script:
1. Runs `PRAGMA wal_checkpoint(TRUNCATE)` on `index/careerpilot.db`, so all data is in the main file. It then copies only that file, never `-wal`/`-shm`.
2. Stops with a clear message if the index is missing or has 0 jobs, if `.llm_cache/` is missing or empty, or if the API server is holding the database. **Stop the local API server before deploying.**
3. Stages `Dockerfile`, `.dockerignore`, `requirements-server.txt`, `src/`, `index/careerpilot.db`, `.llm_cache/` and a Space `README.md` into `build/hf_space/` (git-ignored).
4. Prints which **Space Variables** must match your local `.env` for the demo cache to hit. It prints names only, never values.

Then upload:

```bash
python scripts/deploy_space.py --space-id <hf-user>/careerpilot-api --upload
```

This creates the Space if needed (`sdk: docker`) and uploads the staged folder with the token from `hf auth login`. The Space then builds the image, which takes a few minutes. You can follow it in the Space's **Logs** tab. Later deploys upload only changed files.

## c) Space settings

Go to the Space, then **Settings → Variables and secrets**:

| Name | Type | Value |
|---|---|---|
| `GROQ_API_KEY` | **Secret** | your Groq key |
| model/config names printed by the script | Variable | **exactly** the values in your local `.env` (only those the script lists as different from the code defaults) |
| `RATE_LIMIT` | Variable | e.g. `10/minute`: per client IP, counted separately on `/profile`, `/match`, `/gap`, `/tailor`, `/pipeline`. Empty = off |
| `ALLOWED_ORIGINS` | Variable | your Vercel URL, e.g. `https://careerpilot.vercel.app`, set in step f |
| `MAX_UPLOAD_MB` | Variable (optional) | default `5` |

Notes:
- `ALLOWED_ORIGINS` is a comma-separated list of **exact** origins. A trailing slash is stripped, but there is **no wildcard or regex support**. Each Vercel preview URL (`https://careerpilot-git-…vercel.app`) or custom domain must be added separately.
- Leave `ADMIN_TOKEN` unset. The Space has no `data/` folder, so `/ingest` cannot rebuild the index there. While the token is empty, it answers 403.
- Do not set `INDEX_PATH` or `LLM_CACHE_DIR`. The `Dockerfile` fixes them to `/app/index/careerpilot.db` and `/app/.llm_cache`.
- Changing a Variable or Secret restarts the Space.

## d) Check the API

```
https://<hf-user>-careerpilot-api.hf.space/health     -> 200, "total_jobs": 13975
https://<hf-user>-careerpilot-api.hf.space/docs       -> Swagger UI
```

The Space subdomain is `<owner>-<space-name>`, lower case, with `_` and `.` replaced by `-`. The deploy script prints it.
`/health` answers **503** with `"status": "unavailable"` while the index has no jobs. The other fields stay the same, so you can read `total_jobs`.

## e) Deploy the UI on Vercel

1. In Vercel, use **Add New → Project** and import the GitHub repository.
2. Set **Root Directory** to `frontend`. Vercel detects Next.js, and Node ≥ 20.9 comes from `engines` in `package.json`.
3. Before the first build, under **Environment Variables**, add `NEXT_PUBLIC_API_URL` = `https://<hf-user>-careerpilot-api.hf.space` (no trailing slash needed). Apply it to Production, and to Preview if you use previews.
   `NEXT_PUBLIC_*` values are inlined **at build time**. If the variable is missing, the UI falls back to `http://<vercel-host>:8000`, which cannot work. If you change it later, **redeploy**.
4. Deploy. The UI is client-side only: all API calls go from the browser to the Space. The evaluation numbers on the pages are bundled from `frontend/src/data/`.

## f) Allow the Vercel origin on the Space

Set the Space Variable `ALLOWED_ORIGINS` to the production URL Vercel shows, for example `https://careerpilot.vercel.app`. Changing the Variable restarts the Space. Then open `https://<vercel-url>/flight?demo=1` and `?demo=2`. Both should finish in about a second, from the cache.

Optional check from your machine. It sends the same requests as the UI and shows per step whether the answer came from the cache:

```bash
python scripts/smoke_test_api.py --base-url https://<hf-user>-careerpilot-api.hf.space --origin https://<vercel-url>
```

---

## g) Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/health` is 503 with `"total_jobs": 0` | The image has no index or an empty one. Opening a missing file creates an empty database | Re-run `deploy_space.py` (it refuses an index with 0 jobs) and check that `index/careerpilot.db` is in the staged folder and in the Space's **Files** tab |
| Browser console: *CORS … No 'Access-Control-Allow-Origin'*; UI says "Cannot reach the CareerPilot API" | The Vercel origin is not in `ALLOWED_ORIGINS`, or it is spelled differently (http vs https, preview URL, custom domain) | Add the exact origin to `ALLOWED_ORIGINS` on the Space. The Space restarts |
| UI calls `http://<something>:8000` | `NEXT_PUBLIC_API_URL` was missing when Vercel built the app | Set it in Vercel and **redeploy** (build-time value) |
| Space logs: `attempt to write a readonly database` / `unable to open database file` | `/app/index` is not writable by UID 1000 (SQLite WAL creates `-wal`/`-shm` next to the database) | Use the repo `Dockerfile` unchanged (it `chown`s `/app` to UID 1000 and copies with `--chown=user`) |
| Demos take 10–30 s or show the rate-limit notice | Cache miss: the Space config differs from the warming run (a model Variable, `GROQ_REASONING_EFFORT`, a prompt cap, `BM25_TOP_N`/`RERANK_TOP_K`/`EXPANSION_WEIGHT`), or the index was rebuilt after warming | Set the Variables the deploy script lists to your local values. Or re-run `warm_demo_cache.py` and then `deploy_space.py --upload` |
| `429 Too many requests` | `RATE_LIMIT` reached for this client IP on one endpoint | Wait for the `Retry-After` countdown, or raise `RATE_LIMIT` |
| `503 Groq rate limit reached` | Groq's free tier (8,000 tokens/min per model) is exhausted on every fallback model | Wait and retry. The demos avoid it only when they hit the cache |
| First request after a while is slow or fails, or `/health` shows a "sleeping" page | Free Spaces go to sleep after a period of inactivity and need time to wake up | Open the Space page or `/health`, wait until it is running, then retry from the UI |
| `413 The CV file is too large` | Upload above `MAX_UPLOAD_MB` (default 5) | Use a smaller file or raise `MAX_UPLOAD_MB` |

## h) What a public Space exposes

**Every file in a public Space can be viewed and downloaded by anyone.** That includes `index/careerpilot.db`, the full prebuilt index of the Kaggle postings, and `.llm_cache/` (LLM answers for the two synthetic demo CVs). Only deploy content you are allowed to redistribute, and check the Kaggle dataset's license. Secrets (`GROQ_API_KEY`) are not visible. Variables of a public Space are publicly visible, so never put a key in a Variable.

Runtime writes (new cache entries, SQLite `-wal`/`-shm`) live on the container's ephemeral disk and disappear on restart. The shipped index and cache come back with every restart because they are part of the image.
