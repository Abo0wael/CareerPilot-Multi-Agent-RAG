/** A route between two waypoints: the CareerPilot mark. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden className="shrink-0">
      <rect x="0.5" y="0.5" width="27" height="27" rx="6" className="fill-ink" />
      <path d="M7 20 C 11 20, 12 8, 21 8" fill="none" strokeWidth="1.8" strokeDasharray="2.2 2.2" className="stroke-paper" />
      <circle cx="7" cy="20" r="2.4" className="fill-paper" />
      <circle cx="21" cy="8" r="3" className="fill-beacon-strong" />
    </svg>
  );
}
