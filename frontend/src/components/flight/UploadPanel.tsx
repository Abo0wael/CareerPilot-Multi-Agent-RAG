"use client";

import { FileText, Plane, Upload } from "lucide-react";
import { useState, type DragEvent } from "react";
import type { CvInput } from "@/lib/useFlightPlan";
import { Button, Card } from "../ui";

export const DEMO_CV_PATH = "/demo/sample_cv_backend_engineer.txt";
const ACCEPTED = [".pdf", ".txt"];

/** Drag-and-drop or pick a CV, paste text, or load the synthetic demo CV. */
export function UploadPanel({
  disabled,
  onSubmit,
  onDemo,
}: {
  disabled: boolean;
  onSubmit: (input: CvInput) => void;
  onDemo: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState("");
  const [rejected, setRejected] = useState<string | null>(null);

  function accept(file: File | undefined) {
    if (!file) return;
    if (!ACCEPTED.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      setRejected(`"${file.name}" is not a PDF or TXT file.`);
      return;
    }
    setRejected(null);
    onSubmit({ file });
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) accept(event.dataTransfer.files[0]);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
      <label
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`group flex min-h-56 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-8 text-center transition-colors focus-within:border-beacon-strong ${
          dragging ? "border-beacon-strong bg-beacon-soft" : "border-line bg-surface hover:border-ink"
        } ${disabled ? "pointer-events-none opacity-60" : ""}`}
      >
        <Upload size={28} className="text-beacon" aria-hidden />
        <span className="font-display text-lg font-semibold">Drop your CV here</span>
        <span className="text-sm text-muted">or click to choose a PDF or TXT file</span>
        <input
          type="file"
          accept=".pdf,.txt,application/pdf,text/plain"
          className="sr-only"
          disabled={disabled}
          onChange={(e) => {
            accept(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        {rejected && (
          <span role="alert" className="text-sm text-removed">
            {rejected}
          </span>
        )}
      </label>

      <Card className="flex flex-col gap-3 p-5">
        <label htmlFor="cv-text" className="flex items-center gap-2 text-sm font-medium">
          <FileText size={16} aria-hidden /> Or paste your CV text
        </label>
        <textarea
          id="cv-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          placeholder="Name, experience, skills, projects…"
          className="min-h-32 flex-1 resize-y rounded-md border border-line bg-paper p-3 text-sm outline-none focus:border-ink"
        />
        <div className="flex flex-wrap gap-2">
          <Button disabled={disabled || text.trim().length < 10} onClick={() => onSubmit({ text: text.trim() })}>
            Read this CV
          </Button>
          <Button variant="secondary" disabled={disabled} onClick={onDemo}>
            <Plane size={14} aria-hidden /> Try the demo CV
          </Button>
        </div>
        <p className="text-xs text-muted">
          The demo CV is synthetic (a backend engineer) and its answers are pre-cached, so it runs without Groq calls.
        </p>
      </Card>
    </div>
  );
}
