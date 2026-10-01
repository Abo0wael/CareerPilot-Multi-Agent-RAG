import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Card, Waypoint } from "@/components/ui";
import { AGENTS } from "@/lib/agents";
import {
  STAGES,
  adversarial,
  agentModels,
  coldRun,
  faithfulnessRuns,
  fixturesEvaluated,
  macro,
  macroOriginalLabel,
  pct,
  perProfile,
  reasoningEffort,
  signTest,
  techAudit,
  tokenSavings,
} from "@/lib/evaluation";

export const metadata: Metadata = {
  title: "How it works",
  description: "Architecture, retrieval without embeddings, and the measured evaluation, including negative results.",
};

const LAYERS = [
  { name: "api", detail: "FastAPI endpoints, schemas, error handlers, dependency wiring" },
  { name: "agents", detail: "LangGraph graph + 5 thin agent nodes" },
  { name: "application", detail: "One use case per step; depends only on domain ports" },
  { name: "domain", detail: "Entities, ports (interfaces), pure scoring. No frameworks." },
];

const PIPELINE = [
  { step: "Query", text: "Your preferences plus the first five skills from your profile." },
  { step: "LLM expansion", text: "Groq adds 3–6 related terms (frameworks, synonyms, acronyms)." },
  { step: "BM25 over sections", text: "SQLite FTS5 searches 91,190 section chunks; benefits and about text are excluded." },
  { step: "MAX per job", text: "A job scores as its best chunk, so long postings do not win by length." },
  { step: "LLM rerank", text: "Groq scores the top 20 from 0–100 with a reason; BM25 only breaks ties." },
];

const model = (id: string) => id.replace("openai/", "");

function Section({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-5 border-t border-line pt-10" aria-labelledby={`s-${index}`}>
      <Waypoint index={index}>{title}</Waypoint>
      <div id={`s-${index}`} className="sr-only">
        {title}
      </div>
      {children}
    </section>
  );
}

function Table({ head, rows, caption }: { head: ReactNode[]; rows: ReactNode[][]; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-surface">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line">
            {head.map((h, i) => (
              <th key={i} scope="col" className="px-4 py-3 font-mono text-[11px] font-medium uppercase tracking-wider text-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-line last:border-b-0">
              {row.map((cell, c) => (
                <td key={c} className={`px-4 py-2.5 ${c === 0 ? "font-medium" : "font-mono"}`}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Finding({ tone, children }: { tone: "neutral" | "negative" | "positive"; children: ReactNode }) {
  const border = { neutral: "border-line", negative: "border-removed", positive: "border-verified" }[tone];
  return <li className={`border-l-2 ${border} pl-4 text-sm leading-relaxed`}>{children}</li>;
}

const f2 = (x: number) => x.toFixed(2);
const f3 = (x: number) => x.toFixed(3);

export default function HowItWorks() {
  const chunkVsWhole = signTest("sections_bm25", "whole_bm25");
  const expansion = signTest("sections_bm25", "sections_exp_or");
  const weighted = signTest("sections_exp_or", "sections_exp_weighted");
  const full = signTest("sections_bm25", "full_pipeline");
  const maxP = Math.max(chunkVsWhole.p, expansion.p, full.p);
  const minP = Math.min(chunkVsWhole.p, expansion.p, weighted.p, full.p);
  const ds = perProfile.find((r) => r.family === "data_scientist");
  const control = adversarial.control_specificity;
  const fakeTypes = Object.entries(adversarial).filter(([key]) => key.startsWith("fake_")) as [
    string,
    { caught: number; total: number; recall: number },
  ][];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-12 px-5 py-12">
      <header className="flex max-w-3xl flex-col gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl" style={{ fontStretch: "108%" }}>
          How it works
        </h1>
        <p className="text-muted">
          The real architecture, how jobs are found without embeddings, and what was measured. Every number on this page
          is read from the evaluation files in <code className="font-mono text-sm">outputs/evaluation/</code>, including the
          results that did not go our way.
        </p>
      </header>

      <Section index={1} title="Architecture">
        <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
          <div className="flex flex-col gap-2" role="list" aria-label="Layers, outermost first">
            {LAYERS.map((layer, i) => (
              <div key={layer.name} role="listitem" className="flex flex-col items-stretch">
                <Card className="flex items-baseline justify-between gap-4 px-4 py-3">
                  <span className="font-mono text-sm font-medium">{layer.name}</span>
                  <span className="text-right text-xs text-muted">{layer.detail}</span>
                </Card>
                {i < LAYERS.length - 1 && (
                  <span className="py-0.5 text-center font-mono text-xs text-beacon" aria-hidden>
                    ↓ depends on
                  </span>
                )}
              </div>
            ))}
            <span className="py-0.5 text-center font-mono text-xs text-beacon" aria-hidden>
              ↑ implements the ports
            </span>
            <Card role="listitem" className="flex items-baseline justify-between gap-4 border-dashed px-4 py-3">
              <span className="font-mono text-sm font-medium">infrastructure</span>
              <span className="text-right text-xs text-muted">SQLite FTS5, Groq client and Groq implementations, chunkers, CV parser</span>
            </Card>
            <p className="mt-2 text-sm text-muted">
              Direction: <code className="font-mono">api → agents → application → domain ← infrastructure</code>. A test
              parses every import and fails the build if a layer breaks this rule.
            </p>
          </div>
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted">
              Every reasoning endpoint runs the LangGraph graph. Each agent is a thin node that calls one use case. Groq
              models run with <code className="font-mono">reasoning_effort={reasoningEffort}</code>.
            </p>
            <ol className="flex flex-col gap-2">
              {AGENTS.map((agent, i) => (
                <li key={agent.id} className="flex items-start gap-3 rounded-lg border border-line bg-surface px-4 py-3">
                  <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
                  <div className="flex-1">
                    <p className="text-sm font-medium">
                      {agent.name} <span className="font-mono text-xs font-normal text-muted">· {model(agentModels[agent.id])}</span>
                    </p>
                    <p className="text-sm text-muted">{agent.does}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted">Tailor → Verifier is a fixed edge: a tailored CV is never returned unverified.</p>
          </div>
        </div>
      </Section>

      <Section index={2} title="Retrieval without embeddings">
        <p className="max-w-3xl text-sm">
          Every model call goes to Groq, and Groq offers no embedding models, so there is no vector database. Lexical BM25
          needs word overlap; the LLM is used before search (to add related vocabulary) and after it (to judge fit). This
          compensates for part of what dense retrieval would give, not all of it.
        </p>
        <ol className="grid gap-3 md:grid-cols-5">
          {PIPELINE.map((p, i) => (
            <li key={p.step} className="relative rounded-lg border border-line bg-surface p-4">
              <p className="font-mono text-[11px] text-beacon">STEP {i + 1}</p>
              <p className="mt-1 font-medium">{p.step}</p>
              <p className="mt-1 text-sm text-muted">{p.text}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section index={3} title={`Retrieval quality · Precision@10 on ${fixturesEvaluated} synthetic CVs`}>
        <p className="max-w-3xl text-sm text-muted">
          Weak label: a job counts as relevant if its title contains a keyword of the CV&apos;s job family, matched as a whole
          word. Four keywords were added after inspecting titles, so both label versions are shown.
        </p>
        <Table
          caption="Precision at 10 per profile and retrieval stage"
          head={["Profile", ...STAGES.map((s) => s.label)]}
          rows={[
            ...perProfile.map((row) => [row.family.replace("_", " "), ...STAGES.map((s) => f2(row[s.key].precision_at_10))]),
            ["Macro average", ...STAGES.map((s) => <strong key={s.key}>{f3(macro[s.key])}</strong>)],
            ["Macro, original label", ...STAGES.map((s) => f3(macroOriginalLabel[s.key]))],
          ]}
        />
        <ul className="flex flex-col gap-3">
          <Finding tone="negative">
            <strong>Chunking did not improve precision here.</strong> Sections {f3(macro.sections_bm25)} vs whole postings{" "}
            {f3(macro.whole_bm25)}: {chunkVsWhole.up} profiles better with whole postings, {chunkVsWhole.down} worse (sign test
            p = {f2(chunkVsWhole.p)}). Its measured value is in token cost (below).
          </Finding>
          <Finding tone="neutral">
            <strong>LLM expansion is high-variance.</strong> Macro {f3(macro.sections_bm25)} → {f3(macro.sections_exp_or)}, but it
            helped {expansion.up} profiles and hurt {expansion.down}
            {ds && (
              <>
                ; most of the gain is the data-scientist CV ({f2(ds.sections_bm25.precision_at_10)} →{" "}
                {f2(ds.sections_exp_or.precision_at_10)}), whose base query was <code className="font-mono">{ds.raw_query}</code>
              </>
            )}
            .
          </Finding>
          <Finding tone="negative">
            <strong>A fix was tried and rejected.</strong> Weighting the CV&apos;s own terms above expansion terms gave{" "}
            {f3(macro.sections_exp_weighted)} (it removed the data-scientist gain), so the current system keeps OR expansion.
          </Finding>
          <Finding tone="neutral">
            <strong>Not statistically significant.</strong> With {fixturesEvaluated} profiles, every comparison has sign-test p
            between {f2(minP)} and {f2(maxP)}. Treat these as directions, not proof.
          </Finding>
        </ul>
      </Section>

      <Section index={4} title="Faithfulness and the Verifier">
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="flex flex-col gap-3">
            <h3 className="font-medium">Real tailoring: share of claims the Verifier supported</h3>
            <Table
              caption="Faithfulness per tailoring configuration"
              head={["Run", "Tailor", "Prompt", "Supported", "Rate"]}
              rows={faithfulnessRuns.map((r) => [
                `#${r.run}`,
                model(r.model),
                <span key="p" className="font-sans text-xs">
                  {r.prompt}
                </span>,
                `${r.supported}/${r.claims}`,
                pct(r.supported_rate, 1),
              ])}
            />
            <p className="text-sm text-muted">
              The fast model stuffed job keywords into bullets (e.g. Tableau became Power BI); the Verifier removed them.
              Tailoring therefore runs on the larger model. This is an LLM judging an LLM, which is why the planted test on
              the right exists.
            </p>
          </div>
          <div className="flex flex-col gap-3">
            <h3 className="font-medium">Planted fabrications: did the Verifier catch them?</h3>
            <Table
              caption="Adversarial verifier recall per fabrication type"
              head={["Fabrication", "Caught", "Recall"]}
              rows={[
                ...fakeTypes.map(([key, v]) => [key.replace("fake_", "fake "), `${v.caught}/${v.total}`, pct(v.recall)]),
                ["Real CV bullets kept", `${control.supported}/${control.total}`, pct(control.rate)],
              ]}
            />
            <p className="text-sm text-muted">
              Each fabrication is one blatant phrase appended to a real bullet. Subtle exaggeration is not tested, and{" "}
              {adversarial.planted_overall.total} planted claims still leave real uncertainty.
            </p>
          </div>
        </div>
      </Section>

      <Section index={5} title="Cost, rate limits and data">
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="flex flex-col gap-3">
            <h3 className="font-medium">One full run without cache</h3>
            <Table
              caption="Tokens and latency per step for one cold run"
              head={["Step", "Model", "Tokens", "Latency"]}
              rows={[
                ...coldRun.steps.map((s) => [s.step, s.model, s.tokens.toLocaleString("en-US"), s.latencyS === null ? "—" : `${s.latencyS} s`]),
                ["Total", "", coldRun.totalTokens.toLocaleString("en-US"), `${coldRun.wallTimeS} s`],
              ]}
            />
            <p className="text-sm text-muted">
              {coldRun.groqCalls} Groq calls, {coldRun.rateLimit429s} rate-limit errors. Groq allows 8,000 tokens per minute per
              model, so the steps are split across two models. The demo CV is pre-cached and makes no Groq calls.
            </p>
          </div>
          <div className="flex flex-col gap-3">
            <h3 className="font-medium">Why chunk? Reranker input for the same 20 jobs</h3>
            <Table
              caption="Average job-text tokens per rerank call"
              head={["Job text sent", "Tokens", "Saved"]}
              rows={[
                ["Full postings", tokenSavings.average_job_text_tokens_per_rerank_call.full.toLocaleString("en-US"), "—"],
                [
                  "Requirement sections",
                  tokenSavings.average_job_text_tokens_per_rerank_call.sections.toLocaleString("en-US"),
                  `${tokenSavings.average_saved_vs_full_pct.sections}%`,
                ],
                [
                  "First 600 chars (current reranker)",
                  tokenSavings.average_job_text_tokens_per_rerank_call.deployed.toLocaleString("en-US"),
                  `${tokenSavings.average_saved_vs_full_pct.deployed}%`,
                ],
              ]}
            />
            <p className="text-sm text-muted">
              Sections save {tokenSavings.saved_on_postings_with_headers_pct}% on postings that have headers (
              {pct(tokenSavings.share_of_candidates_with_headers)} of candidates). Most of the reranker&apos;s saving comes from
              truncation, not chunking.
            </p>
            <h3 className="mt-2 font-medium">Is the job index really tech?</h3>
            <p className="text-sm text-muted">
              A random audit of {techAudit.sampled} postings found {techAudit.tech} truly tech (
              {pct(techAudit.tech / techAudit.sampled)}); {techAudit.nonTech} were other engineering or non-tech roles and{" "}
              {techAudit.borderlineNonTech} were borderline industrial-controls jobs.
            </p>
          </div>
        </div>
      </Section>
    </div>
  );
}
