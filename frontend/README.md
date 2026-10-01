# CareerPilot web UI

Next.js (App Router) + TypeScript + Tailwind CSS front end for the CareerPilot API.
It talks **only** to the FastAPI backend (`NEXT_PUBLIC_API_URL`). It never calls Groq and holds no secrets.

## Run locally

```bash
# the backend must be running (see the root README): uvicorn src.api.main:app --host 127.0.0.1 --port 8000
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

## Deployment

See [`../docs/DEPLOY.md`](../docs/DEPLOY.md). In short: the UI runs on Vercel with
`NEXT_PUBLIC_API_URL` set to the Hugging Face Space URL. That variable always wins over
the local fallback, which uses port 8000 on the page's host. Set it before you build.

The backend does not fit Vercel's serverless functions: it needs the 174 MB SQLite index on disk, its requests can take 20–30 s, and it is a long-running uvicorn process. That is why it runs in a Docker Space.
