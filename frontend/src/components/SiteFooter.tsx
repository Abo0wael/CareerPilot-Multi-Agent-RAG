export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-5 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>
          CareerPilot · built by <span className="text-ink">Ahmed Wael Abdelmoaty</span>
        </p>
        <p className="font-mono text-xs">FastAPI · LangGraph · SQLite FTS5 · Groq · Next.js</p>
      </div>
    </footer>
  );
}
