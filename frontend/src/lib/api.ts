// Typed client for the CareerPilot FastAPI backend. This is the only module that talks to the API.
// Types mirror src/api/schemas.py.

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

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

export interface MatchResponse {
  total_matches: number;
  matches: JobMatch[];
}

export interface GapItem {
  requirement: string;
  matched: boolean;
  evidence: string;
}

export interface GapReport {
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

export interface TailoredCV {
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

export interface Health {
  status: string;
  fts5_available: boolean;
  total_jobs: number;
  total_chunks: number;
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
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, `Cannot reach the CareerPilot API at ${API_URL}. Is the backend running?`, null);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = typeof body?.detail === "string" ? body.detail : response.statusText;
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
    return request<CandidateProfile>("/profile", { method: "POST", body: form, signal });
  },

  match: (profile: CandidateProfile, preferences: string, topK: number, signal?: AbortSignal) =>
    postJson<MatchResponse>("/match", { profile, preferences, top_k: topK }, signal),

  gap: (profile: CandidateProfile, jobId: number, signal?: AbortSignal) =>
    postJson<GapReport>("/gap", { profile, job_id: jobId }, signal),

  /** Runs TailorAgent then VerifierAgent in one graph invocation. */
  tailor: (profile: CandidateProfile, jobId: number, signal?: AbortSignal) =>
    postJson<TailoredCV>("/tailor", { profile, job_id: jobId }, signal),
};

/** A short, user-facing explanation for an API error. */
export function describeError(error: unknown): { title: string; message: string; retryAfterSeconds: number | null } {
  if (!(error instanceof ApiError)) {
    return { title: "Something went wrong", message: String(error), retryAfterSeconds: null };
  }
  switch (error.status) {
    case 503:
      return {
        title: "Groq rate limit reached",
        message: "The free Groq tier allows 8,000 tokens per minute per model. Wait for the countdown, then retry.",
        retryAfterSeconds: error.retryAfterSeconds ?? 30,
      };
    case 502:
      return { title: "The language model returned an error", message: error.detail, retryAfterSeconds: null };
    case 404:
      return { title: "Job not found", message: error.detail, retryAfterSeconds: null };
    case 400:
      return { title: "The CV could not be read", message: error.detail, retryAfterSeconds: null };
    case 0:
      return { title: "API unreachable", message: error.detail, retryAfterSeconds: null };
    default:
      return { title: `Request failed (${error.status})`, message: error.detail, retryAfterSeconds: null };
  }
}
