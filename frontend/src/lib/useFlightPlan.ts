"use client";

import { useEffect, useRef, useState } from "react";
import type { AgentId } from "./agents";
import { api, type CandidateProfile, type GapReport, type JobMatch, type TailoredCV } from "./api";

export type AgentStatus = "idle" | "running" | "done" | "error" | "cancelled";
export type AgentRun = { status: AgentStatus; ms: number | null };
export type CvInput = { file: File } | { text: string };

export interface Preferences {
  keywords: string;
  remote: boolean;
  level: string;
  topK: number;
}

export const DEFAULT_PREFERENCES: Preferences = { keywords: "", remote: false, level: "", topK: 10 };

/** Builds the free-text preferences the API parses ("remote" and level names become filters). */
export function preferencesText({ keywords, remote, level }: Preferences): string {
  return [keywords.trim(), remote ? "remote" : "", level].filter(Boolean).join(" ");
}

const IDLE: Record<AgentId, AgentRun> = {
  profile: { status: "idle", ms: null },
  matcher: { status: "idle", ms: null },
  gap: { status: "idle", ms: null },
  tailor: { status: "idle", ms: null },
  verifier: { status: "idle", ms: null },
};

const isAbort = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

export interface FlightError {
  error: unknown;
  failedAt: number;
  retry: () => void;
}

/**
 * Runs the agents one request at a time. Each agent's status changes only when its real
 * request starts or returns (no timers). A new run or leaving the page aborts the old one.
 */
export function useFlightPlan() {
  const [agents, setAgents] = useState(IDLE);
  const [profile, setProfile] = useState<CandidateProfile | null>(null);
  const [matches, setMatches] = useState<JobMatch[] | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [gap, setGap] = useState<GapReport | null>(null);
  const [tailored, setTailored] = useState<TailoredCV | null>(null);
  const [error, setError] = useState<FlightError | null>(null);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const mark = (ids: AgentId[], run: AgentRun) =>
    setAgents((prev) => ({ ...prev, ...Object.fromEntries(ids.map((id) => [id, run])) }));

  /** Starts a new run, cancelling any request still in flight. */
  const begin = () => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    setBusy(true);
    setError(null);
    return next.signal;
  };

  /** Runs one request for the given agent(s) and records its real duration. */
  const step = async <T,>(ids: AgentId[], call: () => Promise<T>): Promise<T> => {
    mark(ids, { status: "running", ms: null });
    const started = performance.now();
    try {
      const result = await call();
      mark(ids, { status: "done", ms: Math.round(performance.now() - started) });
      return result;
    } catch (err) {
      mark(ids, { status: isAbort(err) ? "cancelled" : "error", ms: null });
      throw err;
    }
  };

  const finish = (signal: AbortSignal, err: unknown, retry: () => void) => {
    if (err !== undefined && !isAbort(err) && !signal.aborted) setError({ error: err, failedAt: Date.now(), retry });
    // Only the current run may clear "busy"; a run superseded by a newer one leaves it alone.
    if (controller.current?.signal === signal) setBusy(false);
  };

  const analyzeWith = async (p: CandidateProfile, jobId: number, signal: AbortSignal) => {
    setSelectedJobId(jobId);
    setGap(null);
    setTailored(null);
    mark(["gap", "tailor", "verifier"], { status: "idle", ms: null });
    const report = await step(["gap"], () => api.gap(p, jobId, signal));
    if (signal.aborted) return;
    setGap(report);
    // One request: the LangGraph edge tailor -> verifier always runs both agents.
    const cv = await step(["tailor", "verifier"], () => api.tailor(p, jobId, signal));
    if (!signal.aborted) setTailored(cv);
  };

  const matchWith = async (p: CandidateProfile, prefs: Preferences, signal: AbortSignal, preferredJobId: number | null = null) => {
      setMatches(null);
      setGap(null);
      setTailored(null);
      setSelectedJobId(null);
      mark(["matcher", "gap", "tailor", "verifier"], { status: "idle", ms: null });
      const response = await step(["matcher"], () => api.match(p, preferencesText(prefs), prefs.topK, signal));
      if (signal.aborted) return;
      setMatches(response.matches);
      if (response.matches.length === 0) return;
      // A demo may ask for a specific job; if the ranking differs and it is not in the list, use the top match.
      const target = response.matches.find((m) => m.job_id === preferredJobId) ?? response.matches[0];
      await analyzeWith(p, target.job_id, signal);
  };

  /** Profile, then (if `thenMatch`) matches and analysis of `preferredJobId` (or the top job). */
  const start = async (input: CvInput, thenMatch: Preferences | null, preferredJobId: number | null = null) => {
      const signal = begin();
      setAgents(IDLE);
      setProfile(null);
      setMatches(null);
      setGap(null);
      setTailored(null);
      setSelectedJobId(null);
      let failure: unknown;
      try {
        const p = await step(["profile"], () => api.buildProfile(input, signal));
        if (signal.aborted) return;
        setProfile(p);
        if (thenMatch) await matchWith(p, thenMatch, signal, preferredJobId);
      } catch (err) {
        failure = err;
      } finally {
        finish(signal, failure, () => void start(input, thenMatch, preferredJobId));
      }
  };

  const findMatches = async (prefs: Preferences) => {
      if (!profile) return;
      const signal = begin();
      let failure: unknown;
      try {
        await matchWith(profile, prefs, signal);
      } catch (err) {
        failure = err;
      } finally {
        finish(signal, failure, () => void findMatches(prefs));
      }
  };

  const analyzeJob = async (jobId: number) => {
      if (!profile) return;
      const signal = begin();
      let failure: unknown;
      try {
        await analyzeWith(profile, jobId, signal);
      } catch (err) {
        failure = err;
      } finally {
        finish(signal, failure, () => void analyzeJob(jobId));
      }
  };

  const reportError = (err: unknown, retry: () => void) => setError({ error: err, failedAt: Date.now(), retry });

  const cancel = () => {
    controller.current?.abort();
    setBusy(false);
  };

  return { agents, profile, matches, selectedJobId, gap, tailored, error, busy, start, findMatches, analyzeJob, cancel, reportError };
}
