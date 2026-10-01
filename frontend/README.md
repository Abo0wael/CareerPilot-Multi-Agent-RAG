# CareerPilot web UI

Next.js (App Router) + TypeScript + Tailwind CSS front end for the CareerPilot API.
It talks **only** to the FastAPI backend (`NEXT_PUBLIC_API_URL`). It never calls Groq and holds no secrets.

## Run locally

```bash
# the backend must be running (see the root README): uvicorn src.api.main:app --host 127.0.0.1 --port 8000
cd frontend
npm install
copy .env.example .env.local        # macOS/Linux: cp .env.example .env.local
npm run dev                         # http://localhost:3000 (development)
# or, as on the demo day:
npm run build && npm start          # production build, http://localhost:3000
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
- **Model fallback:** each response lists `model_calls`. If a rate-limited model was replaced by a fallback model, the agent's waypoint shows "answered by fallback model" (hover for the model name).
- **Rate limits:** a `503` (every fallback model rate-limited) shows Groq's `Retry-After` as a countdown before retry is allowed.
- **API URL:** `NEXT_PUBLIC_API_URL` (read at build time) wins; without it the UI calls port 8000 on the host that serves the page.
