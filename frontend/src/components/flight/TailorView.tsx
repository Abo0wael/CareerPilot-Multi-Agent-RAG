import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import type { TailoredBullet, TailoredCV, Verdict } from "@/lib/api";

const BADGE: Record<Verdict, { label: string; className: string; Icon: typeof ShieldCheck }> = {
  supported: { label: "Verified", className: "bg-verified-soft text-verified", Icon: ShieldCheck },
  unverified: { label: "Unverified", className: "border border-dashed border-muted text-muted", Icon: ShieldQuestion },
  unsupported: { label: "Removed", className: "bg-removed-soft text-removed", Icon: ShieldAlert },
};

function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  const { label, className, Icon } = BADGE[verdict ?? "unverified"];
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-xs font-medium ${className}`}>
      <Icon size={12} aria-hidden /> {label}
    </span>
  );
}

function BulletRow({ bullet }: { bullet: TailoredBullet }) {
  return (
    <li className="grid gap-3 border-t border-line py-4 first:border-t-0 md:grid-cols-2 md:gap-6">
      <div>
        <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted">Original</p>
        <p className="text-sm text-muted">{bullet.original || "—"}</p>
      </div>
      <div>
        <div className="mb-1 flex items-center justify-between gap-2">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted">Tailored</p>
          <VerdictBadge verdict={bullet.verdict} />
        </div>
        <p className="text-sm">{bullet.tailored}</p>
        {bullet.evidence && (
          <p className="mt-1 text-xs text-muted">
            <span className="font-medium">Evidence:</span> {bullet.evidence}
          </p>
        )}
      </div>
    </li>
  );
}

/** Original vs tailored bullets with a verdict each, and the claims the Verifier removed. */
export function TailorView({ cv }: { cv: TailoredCV }) {
  const v = cv.verification;
  return (
    <div className="flex flex-col gap-5">
      {v && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
          {[
            ["Claims checked", v.total_claims, "text-ink"],
            ["Verified", v.supported_claims, "text-verified"],
            ["Unverified", v.unverified_claims, "text-muted"],
            ["Removed", v.unsupported_claims, "text-removed"],
          ].map(([label, value, color]) => (
            <div key={label} className="bg-surface p-4">
              <dt className="font-mono text-[11px] uppercase tracking-wider text-muted">{label}</dt>
              <dd className={`font-display text-3xl font-semibold ${color}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <section
        aria-labelledby="removed-title"
        className={`rounded-lg border-2 p-5 ${
          cv.removed_bullets.length > 0 ? "border-removed bg-removed-soft" : "border-verified/50 bg-verified-soft"
        }`}
      >
        <h3 id="removed-title" className="flex items-center gap-2 font-display text-lg font-semibold">
          <ShieldAlert size={20} className={cv.removed_bullets.length > 0 ? "text-removed" : "text-verified"} aria-hidden />
          Removed by Verifier ({cv.removed_bullets.length})
        </h3>
        {cv.removed_bullets.length === 0 ? (
          <p className="mt-1 text-sm">
            Every tailored claim was found in your original CV, so nothing was removed. Claims the Verifier cannot find in
            the CV are removed here and never shown as usable bullets.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {cv.removed_bullets.map((bullet) => (
              <li key={bullet.tailored} className="rounded-md bg-surface p-3">
                <p className="text-sm text-muted line-through decoration-removed">{bullet.tailored}</p>
                <p className="mt-1 text-sm">
                  <span className="font-medium text-removed">Why:</span> {bullet.evidence || "Not supported by the original CV."}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {cv.summary && <p className="text-sm text-muted">{cv.summary}</p>}
      <ul className="rounded-lg border border-line bg-surface px-5">
        {cv.bullets.map((bullet) => (
          <BulletRow key={`${bullet.original}-${bullet.tailored}`} bullet={bullet} />
        ))}
      </ul>
    </div>
  );
}
