"use client";

import { motion, useReducedMotion } from "framer-motion";

const WAYPOINTS = [
  { x: 40, y: 250, label: "CV" },
  { x: 170, y: 170, label: "Profile" },
  { x: 300, y: 205, label: "Matches" },
  { x: 420, y: 110, label: "Gaps" },
  { x: 540, y: 60, label: "Verified CV" },
];

const PATH = "M40 250 C 100 250, 120 170, 170 170 S 260 215, 300 205 S 380 110, 420 110 S 500 60, 540 60";

/** The job search as a flight route: from a CV to a verified, tailored CV. */
export function RouteIllustration() {
  const reduce = useReducedMotion();
  return (
    <svg viewBox="0 0 580 300" className="h-auto w-full" role="img" aria-label="Route from your CV through profile, matches and gaps to a verified CV">
      {[60, 120, 180, 240].map((y) => (
        <line key={y} x1="0" x2="580" y1={y} y2={y} className="stroke-line" strokeWidth="1" />
      ))}
      <path d={PATH} fill="none" className="stroke-line" strokeWidth="2" />
      <motion.path
        d={PATH}
        fill="none"
        className="stroke-beacon-strong"
        strokeWidth="2.5"
        strokeDasharray="6 6"
        initial={{ pathLength: reduce ? 1 : 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 2.2, ease: "easeInOut" }}
      />
      {WAYPOINTS.map((wp, i) => {
        const last = i === WAYPOINTS.length - 1;
        return (
          <motion.g
            key={wp.label}
            initial={{ opacity: reduce ? 1 : 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: reduce ? 0 : 0.3 + i * 0.4 }}
          >
            <rect
              x={wp.x - 6}
              y={wp.y - 6}
              width="12"
              height="12"
              transform={`rotate(45 ${wp.x} ${wp.y})`}
              className={last ? "fill-beacon-strong" : "fill-surface stroke-ink"}
              strokeWidth="2"
            />
            <text x={wp.x} y={wp.y + 28} textAnchor="middle" className="fill-ink font-mono text-[12px]">
              {wp.label}
            </text>
            <text x={wp.x} y={wp.y - 16} textAnchor="middle" className="fill-muted font-mono text-[10px]">
              WPT {String(i + 1).padStart(2, "0")}
            </text>
          </motion.g>
        );
      })}
    </svg>
  );
}
