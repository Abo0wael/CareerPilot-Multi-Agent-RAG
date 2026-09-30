import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-paper hover:bg-beacon disabled:hover:bg-ink",
  secondary: "border border-ink text-ink hover:bg-ink hover:text-paper",
  ghost: "text-muted hover:text-ink",
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";

export function Button({ variant = "primary", className = "", ...props }: ComponentProps<"button"> & { variant?: Variant }) {
  return <button type="button" className={`${BASE} ${VARIANTS[variant]} ${className}`} {...props} />;
}

export function ButtonLink({ variant = "primary", className = "", ...props }: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={`${BASE} ${VARIANTS[variant]} ${className}`} {...props} />;
}

/** "WPT 02 · MATCHES": the flight-plan label used above each section. */
export function Waypoint({ index, children }: { index: number; children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.18em] text-muted">
      <span className="inline-block h-2 w-2 rotate-45 bg-beacon-strong" aria-hidden />
      <span>WPT {String(index).padStart(2, "0")}</span>
      <span aria-hidden>·</span>
      <span className="text-ink">{children}</span>
    </p>
  );
}

export function Card({ className = "", ...props }: ComponentProps<"div">) {
  return <div className={`rounded-lg border border-line bg-surface ${className}`} {...props} />;
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded border border-line px-2 py-0.5 font-mono text-xs text-ink">{children}</span>;
}
