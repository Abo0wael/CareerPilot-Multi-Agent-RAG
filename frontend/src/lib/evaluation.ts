// Measured evaluation results, copied from outputs/evaluation/ by scripts/sync-data.mjs.
// Everything shown on the site is read or derived from these files; nothing is typed by hand.
import chunkingJson from "@/data/chunking_token_savings.json";
import demoJson from "@/data/demo_cold_cache.json";
import resultsJson from "@/data/evaluation_results.json";
import run1Json from "@/data/runs/run1.json";
import run2Json from "@/data/runs/run2.json";
import run3Json from "@/data/runs/run3.json";
import auditJson from "@/data/tech_subset_audit.json";

export const STAGES = [
  { key: "sections_bm25", label: "BM25 · sections" },
  { key: "whole_bm25", label: "BM25 · whole posting" },
  { key: "sections_exp_or", label: "+ LLM expansion (OR)" },
  { key: "sections_exp_weighted", label: "+ expansion (weighted 0.5)" },
  { key: "full_pipeline", label: "Full pipeline (+ rerank)" },
] as const;

export type StageKey = (typeof STAGES)[number]["key"];

interface StageResult {
  precision_at_10: number;
}

interface ProfileRow extends Record<StageKey, StageResult> {
  family: string;
  raw_query?: string;
  expanded_terms?: string[];
}

interface Faithfulness {
  claims: number;
  supported: number;
  unsupported: number;
  unverified: number;
  supported_rate: number;
}

interface RunFile {
  config: { tailor_model: string };
  faithfulness: Faithfulness;
}

interface Results extends RunFile {
  fixtures_evaluated: number;
  config: RunFile["config"] & Record<string, string | number | null>;
  retrieval: {
    macro_precision_at_10: Record<StageKey, number>;
    macro_precision_at_10_original_label: Record<StageKey, number>;
    per_profile: ProfileRow[];
  };
  adversarial: {
    summary: {
      planted_overall: { caught: number; total: number; recall: number };
      control_specificity: { supported: number; total: number; rate: number; false_alarms_unsupported: number };
    } & Record<string, { caught: number; total: number; recall: number }>;
  };
}

interface StepCost {
  total_tokens: number;
  avg_live_latency_s: number | null;
  rate_limit_429s: number;
}

const results = resultsJson as unknown as Results;
const demo = demoJson as unknown as {
  pass_1_fill_cache: { wall_time_s: number; groq_calls: number; total_tokens: number; rate_limit_429s: number; steps: Record<string, StepCost> };
};
const chunking = chunkingJson as unknown as {
  average_job_text_tokens_per_rerank_call: { full: number; sections: number; deployed: number };
  average_saved_vs_full_pct: { sections: number; deployed: number };
  saved_on_postings_with_headers_pct: number;
  share_of_candidates_with_headers: number;
};

export const fixturesEvaluated = results.fixtures_evaluated;
export const macro = results.retrieval.macro_precision_at_10;
export const macroOriginalLabel = results.retrieval.macro_precision_at_10_original_label;
export const perProfile = results.retrieval.per_profile;
export const adversarial = results.adversarial.summary;
export const techAudit = auditJson;
export const tokenSavings = chunking;

/** Two-sided sign test on per-profile differences (ties dropped). */
export function signTest(from: StageKey, to: StageKey) {
  const diffs = perProfile.map((row) => Math.round((row[to].precision_at_10 - row[from].precision_at_10) * 100) / 100);
  const up = diffs.filter((d) => d > 0).length;
  const down = diffs.filter((d) => d < 0).length;
  const n = up + down;
  const choose = (a: number, b: number) => {
    let c = 1;
    for (let i = 0; i < b; i += 1) c = (c * (a - i)) / (i + 1);
    return c;
  };
  let tail = 0;
  for (let i = 0; i <= Math.min(up, down); i += 1) tail += choose(n, i);
  const p = n === 0 ? 1 : Math.min(1, (2 * tail) / 2 ** n);
  return { diffs, up, down, p };
}

export const faithfulnessRuns = [
  { run: 1, model: (run1Json as unknown as RunFile).config.tailor_model, prompt: "original", ...(run1Json as unknown as RunFile).faithfulness },
  { run: 2, model: (run2Json as unknown as RunFile).config.tailor_model, prompt: "strict", ...(run2Json as unknown as RunFile).faithfulness },
  { run: 3, model: (run3Json as unknown as RunFile).config.tailor_model, prompt: "strict (deployed)", ...(run3Json as unknown as RunFile).faithfulness },
];

export const deployedFaithfulness = results.faithfulness;

const STEP_ORDER = ["profile_extraction", "query_expansion", "rerank", "gap_analysis", "tailoring", "verification"] as const;
const STEP_MODEL: Record<(typeof STEP_ORDER)[number], string> = {
  profile_extraction: String(results.config.profile_model),
  query_expansion: String(results.config.fast_model),
  rerank: String(results.config.fast_model),
  gap_analysis: String(results.config.gap_model),
  tailoring: String(results.config.tailor_model),
  verification: String(results.config.verifier_model),
};

export const coldRun = {
  wallTimeS: demo.pass_1_fill_cache.wall_time_s,
  groqCalls: demo.pass_1_fill_cache.groq_calls,
  totalTokens: demo.pass_1_fill_cache.total_tokens,
  rateLimit429s: demo.pass_1_fill_cache.rate_limit_429s,
  steps: STEP_ORDER.map((step) => ({
    step: step.replace("_", " "),
    model: STEP_MODEL[step].replace("openai/", ""),
    tokens: demo.pass_1_fill_cache.steps[step].total_tokens,
    latencyS: demo.pass_1_fill_cache.steps[step].avg_live_latency_s,
  })),
};

export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;

/** Groq model per agent, as recorded in the evaluation run's configuration. */
export const agentModels: Record<"profile" | "matcher" | "gap" | "tailor" | "verifier", string> = {
  profile: String(results.config.profile_model),
  matcher: String(results.config.fast_model),
  gap: String(results.config.gap_model),
  tailor: String(results.config.tailor_model),
  verifier: String(results.config.verifier_model),
};

export const reasoningEffort = String(results.config.reasoning_effort);
