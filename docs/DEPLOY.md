# Deploying CareerPilot

The public deployment is for a few demo sessions, so it has no rate limiting or token budget.

| Part | Host | What it holds |
|---|---|---|
| API (FastAPI) | Hugging Face Space, Docker SDK, free CPU tier | code only; port 7860 |
| Index + demo cache | **private** Hugging Face dataset | `careerpilot.db` (174 MB), `llm_cache/` (12 files) |
| Web UI (Next.js) | Vercel | static pages; calls the API from the browser |

At start-up the Space runs `scripts/start_space.py`. It downloads the index and the demo
cache entries from the private dataset with the `HF_TOKEN` secret, then starts uvicorn.
Data, the index, `.env` and the local LLM cache are never pushed to the Space.

## Data license

The job postings come from [LinkedIn Job Postings (2023-2024)](https://www.kaggle.com/datasets/arshkon/linkedin-job-postings)
by Arsh Koneru, licensed **CC BY-SA 4.0** (as Kaggle's dataset API reports it). CC BY-SA 4.0 allows sharing
and adapting the data, including derived files, as long as you give attribution and share the
derived files under the same license. The dataset card that `upload_index_to_hf.py` writes
does both. The dataset is private in any case.

## Environment

**Space secrets** (Settings → Variables and secrets → *New secret*):

| Name | Value |
|---|---|
| `GROQ_API_KEY` | your Groq key (`deploy_space.py --groq-secret` copies it from `.env`) |
| `HF_TOKEN` | a **fine-grained, read-only** HF token that can read the private dataset |

**Space variables** (*New variable*):

| Name | Value |
|---|---|
| `HF_DATASET_REPO` | `<hf-user>/careerpilot-index` |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` (comma-separated; add more origins if needed) |
| `GROQ_FALLBACK_MODELS` | optional. Default `openai/gpt-oss-120b,openai/gpt-oss-20b,qwen/qwen3.8-27b` |

The Dockerfile already sets `APP_ENV=production`, so `POST /ingest` is not served.

**Vercel environment variable:** `NEXT_PUBLIC_API_URL = https://<hf-user>-careerpilot-api.hf.space`.
Next.js writes it into the bundle at build time, so redeploy after you change it.

## Steps

All commands run from the project root with the conda interpreter
(`C:\Anaconda\envs\careerpilot\python.exe`, shown as `python`).

1. **Log in to Hugging Face.** Create a token with *write* access at
   https://huggingface.co/settings/tokens, then run `hf auth login` and paste the token.
   (With `huggingface_hub` 1.0 and later, `huggingface-cli login` became `hf auth login`.)
   Check the login with `hf auth whoami`.

2. **Upload the index and the demo cache** to a private dataset:
   ```bash
   python scripts/warm_demo_cache.py                 # skip if the demos are already cached
   python scripts/upload_index_to_hf.py --repo <hf-user>/careerpilot-index --dry-run
   python scripts/upload_index_to_hf.py --repo <hf-user>/careerpilot-index
   ```
   The script replays both demos with a Groq stub that refuses every live call. It uploads
   only the cache files those demos read, and it refuses to upload to a public repo.

3. **Create a read-only token for the Space.** At https://huggingface.co/settings/tokens, choose
   *Fine-grained*, then *Repositories → Read access to contents of selected repos →
   `<hf-user>/careerpilot-index`*. Copy the token.

4. **Create the Space, set its configuration and push the code:**
   ```bash
   python scripts/deploy_space.py --space <hf-user>/careerpilot-api \
       --dataset <hf-user>/careerpilot-index --origins http://localhost:3000 --groq-secret
   ```
   Then open the Space's *Settings → Variables and secrets*, add the secret `HF_TOKEN`
   (the token from step 3) and restart the Space. The first build takes a few minutes. Watch
   the *Logs* tab until you see `Uvicorn running on http://0.0.0.0:7860`.

5. **Check the API:** open `https://<hf-user>-careerpilot-api.hf.space/health`. It should
   return `{"status":"ok"}`. Then open `/health/index`: it should report 13975 jobs and 91190 chunks.

6. **Deploy the UI to Vercel:**
   ```bash
   cd frontend
   npx vercel login
   npx vercel link                                     # create the project; root = this folder
   npx vercel env add NEXT_PUBLIC_API_URL production   # paste https://<hf-user>-careerpilot-api.hf.space
   npx vercel --prod
   ```

7. **Allow the Vercel domain** (the Space restarts):
   ```bash
   python scripts/deploy_space.py --space <hf-user>/careerpilot-api --no-upload \
       --origins https://<your-app>.vercel.app
   ```

8. **Test end to end:**
   ```bash
   python scripts/smoke_test_api.py --base-url https://<hf-user>-careerpilot-api.hf.space \
       --origin https://<your-app>.vercel.app --scenario demo1 demo2 fresh
   ```
   Then open the Vercel URL and run Demo 1, Demo 2 and one pasted CV.

To redeploy code later, repeat step 4 without the configuration flags.

## Behaviour to expect

- **Cold start:** a free Space sleeps when nobody uses it. The first request wakes it up,
  which includes downloading the index again. The UI polls `GET /health` and shows
  "Waking up the server…" until the Space answers. Open the site a few minutes before the
  discussion so the Space is already awake.
- **Rate limits:** if a Groq model still answers 429 after the normal retries, or asks for a
  wait longer than 60 s (a daily limit), the client sends the same request to the next model in
  `GROQ_FALLBACK_MODELS`. Every response lists `model_calls`, and the UI labels an agent
  "answered by fallback model" when this happens. Only when every model is rate-limited
  does the API return 503.
- **Demo cache:** the two demos are served from the downloaded cache with zero Groq calls.
  Cache entries written while the Space runs are lost when it restarts.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Space log: `No index on disk and HF_DATASET_REPO / HF_TOKEN are not set` | add the variable and the secret, then restart |
| Space log: 401/404 from `snapshot_download` | `HF_TOKEN` cannot read the dataset; check the token's repo permission |
| UI: "API unreachable / Network or CORS failure" | `ALLOWED_ORIGINS` does not contain the exact Vercel origin (scheme, no trailing slash) |
| UI calls `localhost` in production | `NEXT_PUBLIC_API_URL` was not set before the Vercel build; set it and redeploy |
