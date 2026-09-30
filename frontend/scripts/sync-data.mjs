// Copies measured evaluation results and the demo CV from the Python project into the
// frontend (runs before `dev` and `build`). The copies are committed too, so a build
// still works when the parent folder is not available (e.g. a frontend-only deploy).
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(frontend, "..");
const evaluation = join(root, "outputs", "evaluation");
const dataDir = join(frontend, "src", "data");

const copies = [
  [join(evaluation, "evaluation_results.json"), join(dataDir, "evaluation_results.json")],
  [join(evaluation, "chunking_token_savings.json"), join(dataDir, "chunking_token_savings.json")],
  [join(evaluation, "runs", "demo_cold_cache.json"), join(dataDir, "demo_cold_cache.json")],
  [join(evaluation, "runs", "run1_tailor20b_original_prompt.json"), join(dataDir, "runs", "run1.json")],
  [join(evaluation, "runs", "run2_tailor20b_strict_prompt.json"), join(dataDir, "runs", "run2.json")],
  [join(evaluation, "runs", "run3_tailor120b_strict_prompt.json"), join(dataDir, "runs", "run3.json")],
  // Same bytes as the file scripts/warm_demo_cache.py uploads, so the demo hits the LLM cache.
  [join(root, "tests", "fixtures", "sample_cv_backend_engineer.txt"), join(frontend, "public", "demo", "sample_cv_backend_engineer.txt")],
];

let copied = 0;
for (const [from, to] of copies) {
  if (!existsSync(from)) continue;
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
  copied += 1;
}

// Tech-subset audit: count the classified rows of the audit table (no numbers typed by hand).
const auditPath = join(evaluation, "tech_subset_audit.md");
if (existsSync(auditPath)) {
  const rows = readFileSync(auditPath, "utf8")
    .split("\n")
    .filter((line) => /^\|\s*\d+\s*\|/.test(line))
    .map((line) => line.split("|").map((cell) => cell.trim()));
  const classes = rows.map((cells) => cells[5]);
  const audit = {
    sampled: rows.length,
    tech: classes.filter((c) => c === "Tech").length,
    borderlineNonTech: classes.filter((c) => c.startsWith("Non-tech (borderline)")).length,
    nonTech: classes.filter((c) => c === "Non-tech").length,
    seed: 42,
  };
  writeFileSync(join(dataDir, "tech_subset_audit.json"), JSON.stringify(audit, null, 2) + "\n");
  copied += 1;
}

console.log(`sync-data: ${copied} file(s) updated from the Python project.`);
