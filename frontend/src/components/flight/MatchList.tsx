"use client";

import { MapPin } from "lucide-react";
import type { JobMatch } from "@/lib/api";

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex flex-col items-end gap-1">
      <span className="font-mono text-2xl font-medium leading-none">{Math.round(score)}</span>
      <span className="h-1 w-14 overflow-hidden rounded-full bg-line" aria-hidden>
        <span className="block h-full bg-beacon-strong" style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
      </span>
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted">LLM score</span>
    </div>
  );
}

/** Ranked matches; choosing one runs the Gap, Tailor and Verifier agents for that job. */
export function MatchList({
  matches,
  selectedJobId,
  disabled,
  onSelect,
}: {
  matches: JobMatch[];
  selectedJobId: number | null;
  disabled: boolean;
  onSelect: (jobId: number) => void;
}) {
  if (matches.length === 0) {
    return <p className="rounded-lg border border-line bg-surface p-5 text-sm text-muted">No job matched this query. Try fewer filters.</p>;
  }
  return (
    <ol className="grid gap-3 md:grid-cols-2" aria-label="Job matches">
      {matches.map((match, index) => {
        const selected = match.job_id === selectedJobId;
        return (
          <li key={match.job_id}>
            <button
              type="button"
              onClick={() => onSelect(match.job_id)}
              disabled={disabled}
              aria-pressed={selected}
              className={`flex h-full w-full flex-col gap-3 rounded-lg border bg-surface p-4 text-left transition-colors disabled:cursor-not-allowed ${
                selected ? "border-beacon-strong ring-1 ring-beacon-strong" : "border-line hover:border-ink"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-[11px] text-muted">#{index + 1}</p>
                  <p className="font-display text-base font-semibold leading-snug">{match.title}</p>
                  <p className="text-sm text-muted">{match.company_name}</p>
                </div>
                <ScoreBar score={match.score} />
              </div>
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <span className="inline-flex items-center gap-1">
                  <MapPin size={12} aria-hidden /> {match.location || "Location n/a"}
                </span>
                {match.remote_allowed && <span>Remote</span>}
                {match.formatted_experience_level && <span>{match.formatted_experience_level}</span>}
              </p>
              <p className="border-l-2 border-beacon-strong pl-3 text-sm">{match.reason}</p>
              <span className="text-xs font-medium text-beacon">{selected ? "Selected for analysis" : "Analyze this job →"}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
