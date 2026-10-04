"""Stage (and optionally upload) the CareerPilot API as a Hugging Face Docker Space.

The index database and the LLM cache are git-ignored, so they never go through GitHub;
this script copies them into a staging folder next to the Dockerfile, and only with
``--upload`` pushes that folder to the Space.

Steps:
  1. Checkpoint the SQLite WAL into index/careerpilot.db (so the main file holds all data)
     and check that it has jobs; check that .llm_cache/ has entries.
  2. Stage Dockerfile, .dockerignore, requirements-server.txt, src/, index/careerpilot.db,
     .llm_cache/ and a Space README.md into --stage-dir.
  3. Print the staged files and sizes, and which Space Variables must match your local
     configuration for the demo cache to hit.
  4. With --upload only: create the Space if needed and upload the staged folder, using
     the token saved by ``hf auth login`` (huggingface_hub is a deploy-time tool, not a
     runtime dependency: ``pip install huggingface_hub``).

Usage:
    python scripts/deploy_space.py --space-id user/careerpilot-api            # dry run
    python scripts/deploy_space.py --space-id user/careerpilot-api --upload
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import dotenv_values  # noqa: E402

from src.infrastructure.config import Settings  # noqa: E402

INDEX_DB = _ROOT / "index" / "careerpilot.db"
LLM_CACHE = _ROOT / ".llm_cache"
ENV_FILE = _ROOT / ".env"
STAGE_MARKER = ".careerpilot_stage"  # only folders carrying this marker are ever wiped
FALLBACK_GITHUB_URL = "https://github.com/Abo0wael/CareerPilot-Multi-Agent-RAG"

# Settings that change LLM prompts or the cache key (model, reasoning effort, prompt text,
# retrieval candidates). If the Space differs from the config used by warm_demo_cache.py,
# the demos miss the cache and call Groq live.
CACHE_RELEVANT_SETTINGS = [
    "groq_fast_model", "groq_agent_model",
    "profile_model", "gap_model", "tailor_model", "verifier_model",
    "groq_reasoning_effort",
    "prompt_max_cv_chars", "prompt_max_job_chars_gap", "prompt_max_job_chars_tailor", "tailor_max_bullets",
    "bm25_top_n", "expansion_weight", "rerank_top_k",
]
# Set separately in the Space (secret / deployment-specific) or fixed by the Dockerfile.
DEPLOYMENT_SPECIFIC = {
    "groq_api_key", "allowed_origins", "admin_token", "rate_limit", "max_upload_mb",
    "index_path", "llm_cache_dir", "data_raw_dir",
}


class DeployError(Exception):
    """A precondition for staging is not met (the message says how to fix it)."""


# ── Checks ───────────────────────────────────────────────────────────

def checkpoint_index(db_path: Path) -> int:
    """Move every WAL page into the main database file; return the number of jobs."""
    if not db_path.is_file():
        raise DeployError(f"Index not found at {db_path}. Run: python scripts/build_index.py")
    conn = sqlite3.connect(str(db_path))
    try:
        busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if busy:
            raise DeployError("The index is in use (checkpoint was blocked). Stop the API server and retry.")
        try:
            jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        except sqlite3.OperationalError as err:
            raise DeployError(f"{db_path} is not a CareerPilot index ({err}). Run: python scripts/build_index.py") from err
    finally:
        conn.close()
    if jobs == 0:
        raise DeployError(f"{db_path} has 0 jobs. Run: python scripts/build_index.py")
    return jobs


def check_cache(cache_dir: Path) -> int:
    """Return the number of cached LLM responses; the demos need them."""
    entries = list(cache_dir.glob("*.txt")) if cache_dir.is_dir() else []
    if not entries:
        raise DeployError(
            f"LLM cache {cache_dir} is missing or empty, so the demos would call Groq live. "
            "Run: python scripts/warm_demo_cache.py"
        )
    return len(entries)


# ── Staging ──────────────────────────────────────────────────────────

def prepare_stage_dir(stage_dir: Path) -> None:
    """Create an empty staging folder; refuse to wipe a folder this script did not create."""
    if stage_dir in (_ROOT, *_ROOT.parents):
        raise DeployError(f"Refusing to use {stage_dir} as the staging folder.")
    if stage_dir.exists():
        if any(stage_dir.iterdir()) and not (stage_dir / STAGE_MARKER).exists():
            raise DeployError(f"{stage_dir} is not empty and was not created by this script; choose another --stage-dir.")
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    (stage_dir / STAGE_MARKER).write_text("Staging folder created by scripts/deploy_space.py\n", encoding="utf-8")


def github_url() -> str:
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return FALLBACK_GITHUB_URL
    return url.removesuffix(".git") if url.startswith("https://") else FALLBACK_GITHUB_URL


def space_readme(repo_url: str) -> str:
    return f"""---
title: CareerPilot API
emoji: 🧭
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-agent RAG API for job seekers (Groq + FTS5)
---

# CareerPilot API

FastAPI backend of CareerPilot, a multi-agent assistant for job seekers: CV profile,
matching against 13,975 real LinkedIn tech postings (SQLite FTS5 BM25 + Groq query
expansion and reranking), gap analysis, and tailored CV bullets checked claim by claim.

- Interactive API docs: `/docs`
- Readiness: `/health` (503 while the index has no jobs)
- Source code and documentation: {repo_url}

This Space contains the prebuilt search index (built from the public Kaggle dataset
`arshkon/linkedin-job-postings`) and a cache of LLM responses for the two demo scenarios.
"""


def stage(stage_dir: Path, repo_url: str) -> None:
    prepare_stage_dir(stage_dir)
    for name in ("Dockerfile", ".dockerignore", "requirements-server.txt"):
        shutil.copy2(_ROOT / name, stage_dir / name)
    shutil.copytree(_ROOT / "src", stage_dir / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    (stage_dir / "index").mkdir()
    shutil.copy2(INDEX_DB, stage_dir / "index" / INDEX_DB.name)  # main file only, never -wal/-shm
    shutil.copytree(LLM_CACHE, stage_dir / ".llm_cache")
    (stage_dir / "README.md").write_text(space_readme(repo_url), encoding="utf-8")


# ── Reporting ────────────────────────────────────────────────────────

def _size(path: Path) -> tuple[int, int]:
    """(bytes, file count) of a file or folder."""
    if path.is_file():
        return path.stat().st_size, 1
    files = [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def _human(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:,.0f} {unit}" if unit == "B" else f"{num_bytes:,.1f} {unit}"
        num_bytes /= 1024
    raise AssertionError("unreachable")


def print_summary(stage_dir: Path, jobs: int, cache_entries: int) -> None:
    print(f"\nStaged folder: {stage_dir}")
    total_bytes = total_files = 0
    for entry in sorted(stage_dir.iterdir(), key=lambda p: p.name):
        if entry.name == STAGE_MARKER:
            continue
        size, count = _size(entry)
        total_bytes += size
        total_files += count
        label = f"{entry.name}/" if entry.is_dir() else entry.name
        print(f"  {label:<26} {_human(size):>10}  ({count} file{'s' if count != 1 else ''})")
    print(f"  {'TOTAL':<26} {_human(total_bytes):>10}  ({total_files} files)")
    print(f"  index: {jobs:,} jobs (WAL checkpointed) | LLM cache: {cache_entries} entries")


def print_space_variables_reminder() -> None:
    """Say which Space Variables must equal the local configuration (names only, never values)."""
    env_names = {name.lower() for name in dotenv_values(ENV_FILE)} if ENV_FILE.is_file() else set()
    set_locally = env_names | {name.lower() for name in os.environ}
    fields = Settings.model_fields
    try:
        local = Settings()
    except Exception:  # e.g. no GROQ_API_KEY locally: compare raw presence only
        local = None

    must, optional = [], []
    for name in CACHE_RELEVANT_SETTINGS:
        if name not in set_locally:
            continue
        differs = local is None or getattr(local, name) != fields[name].default
        (must if differs else optional).append(name.upper())
    others = sorted(
        n.upper() for n in env_names
        if n in fields and n not in CACHE_RELEVANT_SETTINGS and n not in DEPLOYMENT_SPECIFIC
    )

    print("\nSpace settings (Settings > Variables and secrets):")
    print("  Secret   GROQ_API_KEY = your Groq key")
    print("  Variable ALLOWED_ORIGINS = your Vercel URL, e.g. https://<project>.vercel.app (no trailing slash)")
    print("  Variable RATE_LIMIT = e.g. 10/minute (empty disables the limit)")
    if must:
        print("  Demo cache: set these Variables to EXACTLY the values in your local .env")
        print("  (they differ from the code defaults, so the cache was warmed with them):")
        for name in must:
            print(f"    - {name}")
    else:
        print("  Demo cache: no cache-relevant setting differs from the code defaults; the Space")
        print("  must simply NOT set any of them (or set them to the code defaults).")
    if optional:
        print(f"  Set locally but equal to the code default (optional on the Space): {', '.join(optional)}")
    if others:
        print(f"  Other names in your .env (do not affect the cache; copy if you rely on them): {', '.join(others)}")


# ── Upload ───────────────────────────────────────────────────────────

def upload(stage_dir: Path, space_id: str) -> None:
    try:
        from huggingface_hub import HfApi
    except ImportError as err:
        raise DeployError("huggingface_hub is not installed. Run: pip install huggingface_hub") from err
    api = HfApi()  # uses the token saved by `hf auth login`
    url = api.create_repo(repo_id=space_id, repo_type="space", space_sdk="docker", exist_ok=True)
    print(f"\nUploading {stage_dir} to {url} ...")
    api.upload_folder(
        folder_path=str(stage_dir),
        repo_id=space_id,
        repo_type="space",
        commit_message="Deploy CareerPilot API",
        ignore_patterns=[STAGE_MARKER],
        delete_patterns=["src/**", ".llm_cache/**"],  # drop files that no longer exist locally
    )
    print(f"Uploaded. The Space builds now; then check {space_url(space_id)}/health")


def space_url(space_id: str) -> str:
    """Public URL of a Space: https://<owner>-<name>.hf.space (lower case, '_' and '.' become '-')."""
    host = space_id.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    return f"https://{host}.hf.space"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space-id", required=True, help="Hugging Face Space id, e.g. user/careerpilot-api")
    parser.add_argument("--stage-dir", type=Path, default=_ROOT / "build" / "hf_space", help="Staging folder (default: build/hf_space)")
    parser.add_argument("--upload", action="store_true", help="Upload the staged folder to the Space (off by default)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.space_id.count("/") != 1:
        parser.error("--space-id must look like <user>/<space-name>")
    stage_dir = args.stage_dir.resolve()
    try:
        jobs = checkpoint_index(INDEX_DB)
        cache_entries = check_cache(LLM_CACHE)
        stage(stage_dir, github_url())
        print_summary(stage_dir, jobs, cache_entries)
        print_space_variables_reminder()
        if args.upload:
            upload(stage_dir, args.space_id)
        else:
            print(f"\nDry run: nothing uploaded. To deploy: python scripts/deploy_space.py --space-id {args.space_id} --upload")
            print(f"Space URL after deployment: {space_url(args.space_id)}")
    except DeployError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
