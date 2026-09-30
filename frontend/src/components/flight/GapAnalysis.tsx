import { CircleCheck, CircleDashed } from "lucide-react";
import type { GapReport } from "@/lib/api";

/** Matched requirements with the CV evidence quote, next to the missing ones. */
export function GapAnalysis({ report }: { report: GapReport }) {
  return (
    <div className="flex flex-col gap-4">
      {report.summary && <p className="max-w-3xl text-sm">{report.summary}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-labelledby="gap-matched" className="rounded-lg border border-line bg-surface p-5">
          <h3 id="gap-matched" className="mb-3 flex items-center gap-2 font-medium">
            <CircleCheck size={18} className="text-verified" aria-hidden /> You meet ({report.matched_items.length})
          </h3>
          <ul className="space-y-4">
            {report.matched_items.map((item) => (
              <li key={item.requirement}>
                <p className="text-sm font-medium">{item.requirement}</p>
                {item.evidence && (
                  <blockquote className="mt-1 border-l-2 border-verified pl-3 text-sm text-muted">
                    <span className="sr-only">Evidence from your CV: </span>“{item.evidence}”
                  </blockquote>
                )}
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="gap-missing" className="rounded-lg border border-line bg-surface p-5">
          <h3 id="gap-missing" className="mb-3 flex items-center gap-2 font-medium">
            <CircleDashed size={18} className="text-beacon" aria-hidden /> Missing ({report.missing_items.length})
          </h3>
          <ul className="space-y-4">
            {report.missing_items.map((item) => (
              <li key={item.requirement}>
                <p className="text-sm font-medium">{item.requirement}</p>
                {item.evidence && <p className="mt-1 text-sm text-muted">{item.evidence}</p>}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
