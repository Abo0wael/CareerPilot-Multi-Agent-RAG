// Demo scenarios. They mirror SCENARIOS in scripts/warm_demo_cache.py, which pre-caches
// every LLM call for them, so running a demo with empty preferences makes no Groq calls.

export interface DemoScenario {
  id: "1" | "2";
  label: string;
  description: string;
  cvPath: string;
  /** Job to analyse after matching; null = the top match. */
  jobId: number | null;
}

export const DEMOS: Record<DemoScenario["id"], DemoScenario> = {
  "1": {
    id: "1",
    label: "Try the demo CV",
    description: "Synthetic backend engineer; analyses the top match.",
    cvPath: "/demo/sample_cv_backend_engineer.txt",
    jobId: null,
  },
  "2": {
    id: "2",
    label: "Demo 2: watch the Verifier catch a claim",
    description:
      "Synthetic entry-level frontend developer and a React job where, in the recorded evaluation run, the tailor rewrote a Vue.js project as React and the Verifier removed it.",
    cvPath: "/demo/sample_cv_frontend_entry_level.txt",
    jobId: 3900943289,
  },
};

export const isDemoId = (value: unknown): value is DemoScenario["id"] => value === "1" || value === "2";
