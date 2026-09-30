# CareerPilot web UI

Next.js (App Router) + TypeScript + Tailwind CSS front end for the CareerPilot API.
It talks **only** to the FastAPI backend (`NEXT_PUBLIC_API_URL`). It never calls Groq and holds no secrets.

## Run locally

```bash
# the backend must be running (see the root README): uvicorn src.api.main:app --port 8000
cd frontend
npm install
copy .env.example .env.local        # macOS/Linux: cp .env.example .env.local
npm run dev                         # http://localhost:3000
```

`predev` and `prebuild` run `scripts/sync-data.mjs`. It copies the measured evaluation results from `../outputs/evaluation/` and the demo CV from `../tests/fixtures/` into `src/data/` and `public/demo/`. The copies are committed, so the UI still builds if the Python project is not next to it.

| Script | Purpose |
|---|---|
| `npm run dev` | Development server |
| `npm run build` / `npm start` | Production build and server |
| `npm run lint` | ESLint (flat config) |

## Structure

```
src/app/            page.tsx (landing), flight/ (the flow), how-it-works/ (architecture + evaluation)
src/components/     ui.tsx primitives, header/footer/theme, flight/* step components
src/lib/api.ts      typed API client (the only module that calls the backend) + error messages
src/lib/useFlightPlan.ts  runs the agents one request at a time; cancel-safe
src/lib/evaluation.ts     measured results read from src/data/*.json
```

- **Real progress:** each agent's waypoint changes only when its request actually starts or returns.
- **Tailor and Verifier:** they share `POST /tailor`, because the LangGraph graph always verifies after tailoring, so they finish together.
- **Rate limits:** a `503` shows Groq's `Retry-After` as a countdown before retry is allowed.

## Deploying later (not deployed yet)

**Frontend on Vercel:**
1. Import the repo and set the **Root Directory** to `frontend`.
2. Set `NEXT_PUBLIC_API_URL` to the public backend URL.
3. Deploy.

**The backend must be hosted elsewhere** (for example Render, Railway or Fly.io). It does not fit Vercel's serverless functions:
- it needs a writable 174 MB SQLite index and a persistent LLM cache on disk;
- requests can run 20–30 s;
- it is a long-running FastAPI/uvicorn process.

**On the backend host:**
- set `GROQ_API_KEY`;
- build the index (`python scripts/build_index.py`) or attach it on a disk;
- set `ALLOWED_ORIGINS` to the Vercel domain (e.g. `https://careerpilot.vercel.app`) so the browser may call the API.
