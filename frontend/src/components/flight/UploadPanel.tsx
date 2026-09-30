"use client";

import { AlertCircle, FileText, Loader2, Plane, RotateCw, ShieldAlert, Upload } from "lucide-react";
import { useState, type DragEvent } from "react";
import { describeError } from "@/lib/api";
import { DEMOS, type DemoScenario } from "@/lib/demos";
import type { CvInput, FlightError } from "@/lib/useFlightPlan";
import { Button, Card } from "../ui";

const ACCEPTED = [".pdf", ".txt"];

/** Drag-and-drop or pick a CV, paste text, or load one of the synthetic demo CVs. */
export function UploadPanel({
  disabled,
  uploading,
  error,
  onSubmit,
  onDemo,
  onRetry,
}: {
  disabled: boolean;
  uploading?: boolean;
  error?: FlightError | null;
  onSubmit: (input: CvInput) => void;
  onDemo: (id: DemoScenario["id"]) => void;
  onRetry?: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [rejected, setRejected] = useState<string | null>(null);

  function accept(file: File | undefined) {
    if (!file) {
      setRejected("No file detected. Please select a valid PDF or TXT file.");
      return;
    }
    if (!ACCEPTED.some((ext) => file.name.toLowerCase().endsWith(ext))) {
      setRejected(`"${file.name}" is not a PDF or TXT file. Supported formats: .pdf, .txt`);
      return;
    }
    if (file.size === 0) {
      setRejected(`"${file.name}" is empty (0 bytes). Please upload a valid CV file with text.`);
      return;
    }
    setRejected(null);
    setFileName(file.name);
    onSubmit({ file });
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = event.dataTransfer.files;
    if (!files || files.length === 0) {
      setRejected("No file detected in drop. Please try choosing a file manually.");
      return;
    }
    accept(files[0]);
  }

  const describedError = error ? describeError(error.error) : null;

  return (
    <div className="flex flex-col gap-3">
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
          } ${disabled && !uploading ? "pointer-events-none opacity-60" : ""}`}
        >
          {uploading ? (
            <>
              <Loader2 size={32} className="animate-spin text-beacon" aria-hidden />
              <span className="font-display text-lg font-semibold text-ink">
                Reading {fileName ? `"${fileName}"` : "your CV"}…
              </span>
              <span className="text-sm text-muted">Profile agent is extracting structured data</span>
            </>
          ) : (
            <>
              <Upload size={28} className="text-beacon transition-transform group-hover:-translate-y-0.5" aria-hidden />
              <span className="font-display text-lg font-semibold">Drop your CV here</span>
              <span className="text-sm text-muted">or click to choose a PDF or TXT file</span>
              {fileName && !error && !rejected && (
                <span className="text-xs font-medium text-beacon">Selected: {fileName}</span>
              )}
            </>
          )}

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
            <Button
              disabled={disabled || text.trim().length < 10}
              onClick={() => {
                setFileName(null);
                setRejected(null);
                onSubmit({ text: text.trim() });
              }}
            >
              Read this CV
            </Button>
            <Button variant="secondary" disabled={disabled} onClick={() => onDemo("1")}>
              <Plane size={14} aria-hidden /> {DEMOS["1"].label}
            </Button>
          </div>
          <Button variant="secondary" disabled={disabled} onClick={() => onDemo("2")} className="self-start">
            <ShieldAlert size={14} aria-hidden /> {DEMOS["2"].label}
          </Button>
          <p className="text-xs text-muted">
            Both demo CVs are synthetic and their answers are pre-cached, so they run without Groq calls. Demo 2:{" "}
            {DEMOS["2"].description}
          </p>
        </Card>
      </div>

      {/* Local rejection alert (format, empty file) */}
      {rejected && (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-removed/50 bg-removed-soft p-4">
          <AlertCircle size={18} className="mt-0.5 shrink-0 text-removed" aria-hidden />
          <div className="flex-1">
            <p className="text-sm font-semibold text-ink">Invalid file</p>
            <p className="mt-0.5 text-xs text-muted">{rejected}</p>
          </div>
          <Button variant="ghost" className="px-2.5 py-1 text-xs" onClick={() => setRejected(null)}>
            Dismiss
          </Button>
        </div>
      )}

      {/* Upload/CORS/Parse error alert */}
      {describedError && (
        <div role="alert" className="flex flex-col gap-2 rounded-lg border border-removed/50 bg-removed-soft p-4">
          <div className="flex items-start gap-3">
            <AlertCircle size={18} className="mt-0.5 shrink-0 text-removed" aria-hidden />
            <div className="flex-1">
              <p className="text-sm font-semibold text-ink">{describedError.title}</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">{describedError.message}</p>
              {fileName && <p className="mt-1 text-xs italic text-muted">Target file: {fileName}</p>}
            </div>
          </div>
          {onRetry && (
            <div className="mt-1 flex items-center gap-2 self-start pl-7">
              <Button variant="secondary" className="px-3 py-1.5 text-xs" onClick={onRetry}>
                <RotateCw size={13} aria-hidden /> Retry upload
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

