// Typed client for the CareerPilot FastAPI backend. This is the only module that talks to the API.
// Types mirror src/api/schemas.py.

/**
 * The API base URL. NEXT_PUBLIC_API_URL (inlined at build time) always wins, so a
 * deployed UI (e.g. on Vercel) calls the deployed API. Without it, local development
 * assumes the API on port 8000 of the host serving the page (localhost or a LAN IP).
 */
export function getApiUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (envUrl) return envUrl.replace(/\/+$/, "");
  if (typeof window !== "undefined" && window.location.hostname) {
    return `http://${window.location.hostname}:8000`;
  }
  return "http://127.0.0.1:8000";
}

/** Which Groq model answered one LLM request of an agent (mirrors ModelCallSchema). */
export interface ModelCall {
  agent: string;
  requested_model: string;
  answered_model: string;
  used_fallback: boolean;
  cached: boolean;
}

interface WithModelCalls {
  model_calls?: ModelCall[];
}

export interface Experience {
  role: string;
  company: string;
  duration: string;
  bullets: string[];
}

export interface Project {
  name: string;
  description: string;
  technologies: string[];
}

export interface Education {
  degree: string;
  institution: string;
  year: string;
  details: string;
}

export interface CandidateProfile {
  raw_text: string;
  name: string;
  email: string;
  phone: string;
  summary: string;
  skills: string[];
  experiences: Experience[];
  projects: Project[];
  education: Education[];
  certifications: string[];
}

export interface JobMatch {
  job_id: number;
  title: string;
  company_name: string;
  location: string;
  formatted_experience_level: string;
  formatted_work_type: string;
  remote_allowed: boolean;
  score: number;
  reason: string;
  skills: string[];
}

export interface MatchResponse extends WithModelCalls {
  total_matches: number;
  matches: JobMatch[];
}

export interface GapItem {
  requirement: string;
  matched: boolean;
  evidence: string;
}

export interface GapReport extends WithModelCalls {
  job_id: number;
  job_title: string;
  matched_items: GapItem[];
  missing_items: GapItem[];
  summary: string;
}

export type Verdict = "supported" | "unsupported" | "unverified";

export interface TailoredBullet {
  section: string;
  original: string;
  tailored: string;
  verdict: Verdict | null;
  evidence: string;
}

export interface TailoredCV extends WithModelCalls {
  summary: string;
  bullets: TailoredBullet[];
  removed_bullets: TailoredBullet[];
  verification: {
    total_claims: number;
    supported_claims: number;
    unsupported_claims: number;
    unverified_claims: number;
  } | null;
}

export type ProfileResponse = CandidateProfile & WithModelCalls;

export interface Health {
  status: string;
}

/** An HTTP error from the API, with the server's message and (for 503) the Retry-After wait. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly retryAfterSeconds: number | null,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  const baseUrl = getApiUrl();
  try {
    response = await fetch(`${baseUrl}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const isCrossHost = origin && !baseUrl.startsWith(origin);
    const corsHint = isCrossHost
      ? ` Check that the backend is running and that its ALLOWED_ORIGINS includes "${origin}".`
      : "";
    throw new ApiError(
      0,
      `Cannot reach the CareerPilot API at ${baseUrl}. Is the backend running?${corsHint}`,
      null,
    );
  }
  if (!response.ok) {
    let detail = "";
    try {
      const text = await response.text();
      try {
        const body = JSON.parse(text) as { detail?: unknown };
        detail = typeof body?.detail === "string" ? body.detail : text;
      } catch {
        detail = text || response.statusText;
      }
    } catch {
      detail = response.statusText;
    }
    const retryAfter = Number(response.headers.get("Retry-After"));
    throw new ApiError(response.status, detail, Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null);
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),

  /** Upload a CV file (.pdf / .txt), or send pasted text, and get the structured profile. */
  buildProfile: (input: { file: File } | { text: string }, signal?: AbortSignal) => {
    const form = new FormData();
    if ("file" in input) form.append("file", input.file, input.file.name);
    else form.append("raw_text", input.text);
    return request<ProfileResponse>("/profile", { method: "POST", body: form, signal });
  },

  match: (profile: CandidateProfile, preferences: string, topK: number, signal?: AbortSignal) =>
    postJson<MatchResponse>("/match", { profile, preferences, top_k: topK }, signal),

  gap: (profile: CandidateProfile, jobId: number, signal?: AbortSignal) =>
    postJson<GapReport>("/gap", { profile, job_id: jobId }, signal),

  /** Runs TailorAgent then VerifierAgent in one graph invocation. */
  tailor: (profile: CandidateProfile, jobId: number, signal?: AbortSignal) =>
    postJson<TailoredCV>("/tailor", { profile, job_id: jobId }, signal),
};

const WAKE_PROBE_TIMEOUT_MS = 8_000;
const WAKE_RETRY_EVERY_MS = 4_000;
const WAKE_GIVE_UP_AFTER_MS = 5 * 60_000;

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

/**
 * Resolves once GET /health answers. A free Hugging Face Space sleeps when idle; while it
 * starts, requests fail or return the proxy's own page, so `onWaking` is called once and the
 * probe is repeated instead of reporting an error.
 */
export async function waitUntilAwake(onWaking: () => void, signal?: AbortSignal): Promise<void> {
  const deadline = Date.now() + WAKE_GIVE_UP_AFTER_MS;
  let warned = false;
  for (;;) {
    const probe = AbortSignal.any([AbortSignal.timeout(WAKE_PROBE_TIMEOUT_MS), ...(signal ? [signal] : [])]);
    try {
      const health = await api.health(probe);
      if (health.status === "ok") return;
    } catch (error) {
      if (signal?.aborted) throw error;
    }
    if (Date.now() > deadline) {
      throw new ApiError(0, `The CareerPilot API at ${getApiUrl()} did not wake up within 5 minutes.`, null);
    }
    if (!warned) {
      warned = true;
      onWaking();
    }
    await sleep(WAKE_RETRY_EVERY_MS, signal);
  }
}

/** A short, user-facing explanation for an API error. */
export function describeError(error: unknown): { title: string; message: string; retryAfterSeconds: number | null } {
  if (!(error instanceof ApiError)) {
    const rawMsg = error instanceof Error ? error.message : String(error);
    return { title: "Upload failed", message: rawMsg, retryAfterSeconds: null };
  }
  switch (error.status) {
    case 503:
      return {
        title: "Groq rate limit reached",
        message:
          "Every Groq model in the fallback list is rate-limited right now (the free tier allows 8,000 tokens per minute per model). Wait for the countdown, then retry.",
        retryAfterSeconds: error.retryAfterSeconds ?? 30,
      };
    case 502:
      return { title: "The language model returned an error", message: error.detail, retryAfterSeconds: null };
    case 404:
      return { title: "Job not found", message: error.detail, retryAfterSeconds: null };
    case 400:
      if (error.detail.toLowerCase().includes("cors")) {
        const origin = typeof window !== "undefined" ? window.location.origin : "this origin";
        return {
          title: "CORS error: origin disallowed",
          message: `${error.detail}. Add ${origin} to ALLOWED_ORIGINS in the backend .env file.`,
          retryAfterSeconds: null,
        };
      }
      return { title: "The CV could not be read", message: error.detail, retryAfterSeconds: null };
    case 0:
      return { title: "API unreachable / Network or CORS failure", message: error.detail, retryAfterSeconds: null };
    default:
      return { title: `Request failed (${error.status})`, message: error.detail, retryAfterSeconds: null };
  }
}

