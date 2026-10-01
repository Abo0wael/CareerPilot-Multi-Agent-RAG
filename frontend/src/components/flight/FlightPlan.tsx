"use client";

import { Loader2, Square } from "lucide-react";
import { useEffect, useEffectEvent, useRef, type ReactNode } from "react";
import { DEMOS, type DemoScenario } from "@/lib/demos";
import { DEFAULT_PREFERENCES, useFlightPlan } from "@/lib/useFlightPlan";
import { ErrorNotice } from "../ErrorNotice";
import { Button, Waypoint } from "../ui";
import { AgentTimeline } from "./AgentTimeline";
import { GapAnalysis } from "./GapAnalysis";
import { MatchList } from "./MatchList";
import { PreferencesForm } from "./PreferencesForm";
import { ProfileSummary } from "./ProfileSummary";
import { TailorView } from "./TailorView";
import { UploadPanel } from "./UploadPanel";

function Step({ index, title, intro, children }: { index: number; title: string; intro?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4" aria-label={title}>
      <div className="flex flex-col gap-1">
        <Waypoint index={index}>{title}</Waypoint>
        {intro && <p className="max-w-3xl text-sm text-muted">{intro}</p>}
      </div>
      {children}
    </section>
  );
}

function Working({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-lg border border-dashed border-line p-5 text-sm text-muted">
      <Loader2 size={16} className="animate-spin text-beacon" aria-hidden /> {children}
    </p>
  );
}

export function FlightPlan({ autoDemo }: { autoDemo: DemoScenario["id"] | null }) {
  const flight = useFlightPlan();
  const { agents, models, profile, matches, selectedJobId, gap, tailored, error, busy } = flight;
  const selectedJob = matches?.find((m) => m.job_id === selectedJobId);
  const demoStarted = useRef(false);
  const revealRemoved = useRef(false);

  async function runDemo(demo: DemoScenario) {
    let file: File;
    try {
      const response = await fetch(demo.cvPath);
      if (!response.ok) throw new Error(`Could not load the demo CV (${response.status}).`);
      file = new File([await response.blob()], demo.cvPath.split("/").pop() ?? "demo.txt", { type: "text/plain" });
    } catch (err) {
      flight.reportError(err, () => void runDemo(demo));
      return;
    }
    revealRemoved.current = demo.jobId !== null;
    // Same file, empty preferences and job as scripts/warm_demo_cache.py, so every step hits the cache.
    await flight.start({ file }, DEFAULT_PREFERENCES, demo.jobId);
  }

  const startDemoOnce = useEffectEvent((id: DemoScenario["id"]) => {
    if (demoStarted.current) return;
    demoStarted.current = true;
    void runDemo(DEMOS[id]);
  });

  // The landing page links here with ?demo=1 or ?demo=2.
  useEffect(() => {
    if (autoDemo) startDemoOnce(autoDemo);
  }, [autoDemo]);

  // Demo 2 exists to show the Verifier at work: bring its result into view once it arrives.
  useEffect(() => {
    if (!tailored || !revealRemoved.current) return;
    revealRemoved.current = false;
    document.getElementById("verifier-removals")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [tailored]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-10 px-5 py-10">
      <header className="flex flex-col gap-3">
        <h1 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl" style={{ fontStretch: "108%" }}>
          Flight plan
        </h1>
        <p className="max-w-2xl text-muted">
          Five agents, one route: read your CV, find real jobs that fit, show what you meet and what you miss, then tailor
          your bullets and verify every claim against your original CV.
        </p>
      </header>

      {/* Sticky on wide screens so progress and errors stay visible while you scroll the results. */}
      <div className="z-30 -mx-1 flex flex-col gap-2 bg-paper/95 px-1 py-2 backdrop-blur-sm md:sticky md:top-16">
        <AgentTimeline agents={agents} models={models} />
        {busy && (
          <Button variant="ghost" onClick={flight.cancel} className="self-end py-1">
            <Square size={12} aria-hidden /> Cancel
          </Button>
        )}
        {error && <ErrorNotice error={error.error} failedAt={error.failedAt} onRetry={error.retry} />}
      </div>

      <Step index={1} title="Your CV" intro="PDF or plain text. The file is sent only to the CareerPilot API.">
        <UploadPanel
          disabled={busy}
          uploading={busy && agents.profile.status === "running"}
          error={!profile ? error : null}
          onSubmit={(input) => void flight.start(input, null)}
          onDemo={(id) => void runDemo(DEMOS[id])}
          onRetry={error ? error.retry : undefined}
        />
      </Step>

      {(profile || agents.profile.status === "running") && (
        <Step index={2} title="Profile" intro="Extracted by the Profile agent. Nothing here is added: missing fields stay empty.">
          {profile ? <ProfileSummary profile={profile} /> : <Working>Profile agent is reading your CV…</Working>}
        </Step>
      )}

      {profile && (
        <Step
          index={3}
          title="Matches"
          intro="BM25 over job-posting sections, widened by LLM query expansion, then reranked by an LLM with a reason for each job."
        >
          <PreferencesForm disabled={busy} onSubmit={(prefs) => void flight.findMatches(prefs)} />
          {agents.matcher.status === "running" && <Working>Matcher agent is searching and reranking…</Working>}
          {matches && (
            <MatchList matches={matches} selectedJobId={selectedJobId} disabled={busy} onSelect={(id) => void flight.analyzeJob(id)} />
          )}
        </Step>
      )}

      {selectedJob && (
        <Step
          index={4}
          title={`Gap analysis · ${selectedJob.title}`}
          intro="Each matched requirement quotes the evidence from your CV. Missing ones are what to work on, or to address honestly."
        >
          {gap ? <GapAnalysis report={gap} /> : agents.gap.status === "running" && <Working>Gap agent is comparing requirements…</Working>}
        </Step>
      )}

      {selectedJob && (gap || tailored) && (
        <Step
          index={5}
          title="Tailored CV"
          intro="Your bullets rewritten for this job, then checked one by one against your original CV. Anything the Verifier cannot find there is removed."
        >
          {tailored ? (
            <TailorView cv={tailored} />
          ) : (
            agents.tailor.status === "running" && <Working>Tailor agent is rewriting, then the Verifier checks every claim…</Working>
          )}
        </Step>
      )}
    </div>
  );
}
