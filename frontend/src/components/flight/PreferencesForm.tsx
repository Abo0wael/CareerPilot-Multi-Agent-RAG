"use client";

import { Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { DEFAULT_PREFERENCES, type Preferences } from "@/lib/useFlightPlan";
import { Button } from "../ui";

// Exactly the level names the API's filter recognises (src/application/match_jobs.py).
const LEVELS = ["Internship", "Entry level", "Mid-Senior level", "Director", "Executive"];

const FIELD = "rounded-md border border-line bg-paper px-3 py-2 text-sm outline-none focus:border-ink";

export function PreferencesForm({ disabled, onSubmit }: { disabled: boolean; onSubmit: (prefs: Preferences) => void }) {
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFERENCES);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!disabled) onSubmit(prefs);
  }

  return (
    <form onSubmit={submit} className="grid gap-3 rounded-lg border border-line bg-surface p-4 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end sm:p-5">
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">Role or keywords</span>
        <input
          className={FIELD}
          value={prefs.keywords}
          placeholder="e.g. backend Kafka"
          onChange={(e) => setPrefs({ ...prefs, keywords: e.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="font-medium">Experience level</span>
        <select className={FIELD} value={prefs.level} onChange={(e) => setPrefs({ ...prefs, level: e.target.value })}>
          <option value="">Any level</option>
          {LEVELS.map((level) => (
            <option key={level}>{level}</option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-2 text-sm sm:pb-2.5">
        <input
          type="checkbox"
          checked={prefs.remote}
          onChange={(e) => setPrefs({ ...prefs, remote: e.target.checked })}
          className="h-4 w-4 accent-[var(--beacon-strong)]"
        />
        Remote only
      </label>
      <Button type="submit" disabled={disabled}>
        <Search size={14} aria-hidden /> Find matches
      </Button>
      <p className="text-xs text-muted sm:col-span-4">
        Leave everything empty for the demo CV to use its cached run. New keywords or filters make live Groq calls.
      </p>
    </form>
  );
}
