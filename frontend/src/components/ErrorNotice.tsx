"use client";

import { AlertTriangle, RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { describeError } from "@/lib/api";
import { Button } from "./ui";

/** Shows an API error; for 503 it counts down Groq's Retry-After before allowing a retry. */
export function ErrorNotice({ error, failedAt, onRetry }: { error: unknown; failedAt: number; onRetry: () => void }) {
  const { title, message, retryAfterSeconds } = describeError(error);
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (retryAfterSeconds === null) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [retryAfterSeconds]);

  const remaining =
    retryAfterSeconds === null
      ? 0
      : now === null
        ? retryAfterSeconds
        : Math.max(0, Math.ceil((failedAt + retryAfterSeconds * 1000 - now) / 1000));

  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-removed/40 bg-removed-soft p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex gap-3">
        <AlertTriangle size={18} className="mt-0.5 shrink-0 text-removed" aria-hidden />
        <div>
          <p className="font-medium text-ink">{title}</p>
          <p className="text-sm text-muted">{message}</p>
        </div>
      </div>
      <Button variant="secondary" onClick={onRetry} disabled={remaining > 0} className="shrink-0">
        <RotateCw size={14} aria-hidden />
        {remaining > 0 ? `Retry in ${remaining} s` : "Retry"}
      </Button>
    </div>
  );
}
