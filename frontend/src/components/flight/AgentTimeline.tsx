"use client";

import { motion } from "framer-motion";
import { Check, Loader2, X } from "lucide-react";
import { AGENTS, type AgentId } from "@/lib/agents";
import type { AgentRun } from "@/lib/useFlightPlan";

function StatusIcon({ status }: { status: AgentRun["status"] }) {
  if (status === "running") return <Loader2 size={13} className="animate-spin" aria-hidden />;
  if (status === "done") return <Check size={13} aria-hidden />;
  if (status === "error" || status === "cancelled") return <X size={13} aria-hidden />;
  return null;
}

const DOT: Record<AgentRun["status"], string> = {
  idle: "border-line bg-surface text-muted",
  running: "border-beacon-strong bg-beacon-soft text-beacon",
  done: "border-ink bg-ink text-paper",
  error: "border-removed bg-removed-soft text-removed",
  cancelled: "border-line bg-surface text-muted",
};

const STATUS_TEXT: Record<AgentRun["status"], string> = {
  idle: "waiting",
  running: "working…",
  done: "done",
  error: "failed",
  cancelled: "cancelled",
};

/**
 * The flight plan: one waypoint per agent. A waypoint changes only when its API
 * request actually starts or returns; durations are the measured request times.
 */
export function AgentTimeline({ agents }: { agents: Record<AgentId, AgentRun> }) {
  const running = AGENTS.filter((a) => agents[a.id].status === "running").map((a) => a.name);
  return (
    <section aria-label="Agent progress" className="rounded-lg border border-line bg-surface px-3 pb-3 pt-2.5 sm:px-5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted">Agent route</h2>
        <p className="text-xs text-beacon" aria-live="polite">
          {running.length > 0 ? `${running.join(" + ")} agent working…` : ""}
        </p>
      </div>
      <ol className="relative grid grid-cols-5 gap-1">
        <div className="absolute left-[10%] right-[10%] top-[11px] border-t-2 border-dashed border-line" aria-hidden />
        {AGENTS.map((agent) => {
          const run = agents[agent.id];
          return (
            <li key={agent.id} className="relative flex flex-col items-center text-center">
              <motion.span
                className={`relative z-10 flex h-6 w-6 items-center justify-center rounded-full border-2 ${DOT[run.status]}`}
                animate={run.status === "running" ? { scale: [1, 1.15, 1] } : { scale: 1 }}
                transition={run.status === "running" ? { repeat: Infinity, duration: 1.2 } : { duration: 0.2 }}
              >
                <StatusIcon status={run.status} />
              </motion.span>
              <span className="mt-1 text-xs font-medium sm:text-sm">{agent.name}</span>
              <span className="font-mono text-[10px] text-muted sm:text-[11px]">
                <span className="sr-only">{agent.name} agent: </span>
                {STATUS_TEXT[run.status]}
                {run.ms !== null && ` · ${(run.ms / 1000).toFixed(1)} s`}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="mt-1 grid grid-cols-5 gap-1" aria-hidden>
        <div className="col-span-2 col-start-4 flex flex-col items-center">
          <span className="h-1.5 w-3/5 border-x border-b border-line" />
          <span className="mt-0.5 font-mono text-[10px] text-muted">one request · /tailor</span>
        </div>
      </div>
      <p className="sr-only">Tailor and Verifier run in one request; the graph always verifies after tailoring, so they finish together.</p>
    </section>
  );
}
