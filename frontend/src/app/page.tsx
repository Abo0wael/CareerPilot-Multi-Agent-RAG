import { ArrowRight, FileSearch, Plane, Route, ShieldCheck } from "lucide-react";
import { RouteIllustration } from "@/components/RouteIllustration";
import { ButtonLink, Waypoint } from "@/components/ui";
import { adversarial, deployedFaithfulness, techAudit } from "@/lib/evaluation";

const STEPS = [
  { Icon: FileSearch, title: "Which jobs fit me?", text: "Ten real postings from 13,975 tech jobs, each with a reason grounded in your CV." },
  { Icon: Route, title: "What am I missing?", text: "Requirements you meet, quoted from your CV, next to the ones you do not." },
  { Icon: ShieldCheck, title: "How do I present myself?", text: "Bullets rewritten for the job, and every claim checked against your original CV." },
];

export default function Home() {
  const planted = adversarial.planted_overall;
  return (
    <>
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-5 pb-16 pt-14 lg:grid-cols-[1.05fr_1fr] lg:pt-20">
        <div className="flex flex-col gap-6">
          <Waypoint index={0}>For job seekers</Waypoint>
          <h1 className="font-display text-4xl font-semibold leading-[1.05] tracking-tight sm:text-6xl" style={{ fontStretch: "112%" }}>
            Dozens of applications.
            <br />
            <span className="text-beacon">No replies.</span>
            <br />
            No idea why.
          </h1>
          <p className="max-w-xl text-lg text-muted">
            Recruiters screen thousands of CVs in seconds with AI. Candidates get nothing. CareerPilot gives you the same
            kind of tool, and it never invents anything about you.
          </p>
          <div className="flex flex-wrap gap-3">
            <ButtonLink href="/flight">
              Start with your CV <ArrowRight size={16} aria-hidden />
            </ButtonLink>
            <ButtonLink href="/flight?demo=1" variant="secondary">
              <Plane size={16} aria-hidden /> Try the demo CV
            </ButtonLink>
          </div>
          <ButtonLink href="/flight?demo=2" variant="ghost" className="self-start px-0">
            <ShieldCheck size={16} aria-hidden /> Demo 2: watch the Verifier catch a claim
          </ButtonLink>
        </div>
        <div className="rounded-lg border border-line bg-surface p-4 sm:p-6">
          <RouteIllustration />
        </div>
      </section>

      <section className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-14 md:grid-cols-3">
          {STEPS.map(({ Icon, title, text }) => (
            <div key={title} className="flex flex-col gap-3">
              <Icon size={22} className="text-beacon" aria-hidden />
              <h2 className="font-display text-xl font-semibold">{title}</h2>
              <p className="text-muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-8 px-5 py-16 lg:grid-cols-[1fr_1.2fr] lg:items-center">
        <div className="flex flex-col gap-4">
          <Waypoint index={5}>The trust feature</Waypoint>
          <h2 className="font-display text-3xl font-semibold tracking-tight">A Verifier checks every tailored claim.</h2>
          <p className="text-muted">
            Tailoring with an LLM can quietly add a tool you never used or a number you never reached. A separate Verifier
            agent reads each rewritten bullet against your original CV. Anything it cannot find there is removed and shown
            to you with the reason.
          </p>
          <ButtonLink href="/how-it-works" variant="ghost" className="self-start px-0">
            How it works and how it was measured <ArrowRight size={14} aria-hidden />
          </ButtonLink>
        </div>
        <dl className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
          <div className="bg-surface p-5">
            <dt className="text-sm text-muted">Planted fabrications caught</dt>
            <dd className="mt-1 font-display text-4xl font-semibold">
              {planted.caught}/{planted.total}
            </dd>
            <dd className="mt-1 text-xs text-muted">fake skills, metrics, employers and certifications</dd>
          </div>
          <div className="bg-surface p-5">
            <dt className="text-sm text-muted">Real tailored claims supported</dt>
            <dd className="mt-1 font-display text-4xl font-semibold">
              {deployedFaithfulness.supported}/{deployedFaithfulness.claims}
            </dd>
            <dd className="mt-1 text-xs text-muted">the rest were removed by the Verifier</dd>
          </div>
          <div className="bg-surface p-5">
            <dt className="text-sm text-muted">Tech postings, audited</dt>
            <dd className="mt-1 font-display text-4xl font-semibold">
              {techAudit.tech}/{techAudit.sampled}
            </dd>
            <dd className="mt-1 text-xs text-muted">random sample of the job index truly tech</dd>
          </div>
        </dl>
      </section>
    </>
  );
}
