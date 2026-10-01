"""Upload the search index and the demo LLM-cache entries to a PRIVATE Hugging Face dataset.

The deployed API (Hugging Face Space) downloads them at start-up (scripts/start_space.py).

What is uploaded:
  careerpilot.db   the SQLite FTS5 index (derived from the Kaggle dataset, CC BY-SA 4.0)
  llm_cache/*.txt  ONLY the cache entries the two demo scenarios read. They are found by
                   replaying the demos (same calls as scripts/warm_demo_cache.py) with a Groq
                   stub that refuses every live call, and recording which cache files were hit.
                   Both demo CVs are synthetic (tests/fixtures). No other cache entry is sent.
  README.md        dataset card with the license and attribution

Run scripts/warm_demo_cache.py first if the demos are not fully cached yet.

Usage (after `hf auth login`):
    python scripts/upload_index_to_hf.py --repo <user>/careerpilot-index [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from warm_demo_cache import SCENARIOS, TOP_K, Scenario  # noqa: E402

from src.api.dependencies import build_workflow, clear_app_state  # noqa: E402
from src.infrastructure.config import Settings, get_settings  # noqa: E402
from src.infrastructure.llm.client import GroqClient  # noqa: E402

DATASET_CARD = """---
license: cc-by-sa-4.0
pretty_name: CareerPilot search index (private)
---

# CareerPilot search index

Private support files for the CareerPilot API deployment:

- `careerpilot.db`: SQLite FTS5 index of the tech subset of job postings, split into sections.
- `llm_cache/`: cached Groq answers for the two demo scenarios, which use synthetic CVs.

Derived from **LinkedIn Job Postings (2023-2024)** by Arsh Koneru
(https://www.kaggle.com/datasets/arshkon/linkedin-job-postings), licensed under
CC BY-SA 4.0. Changes: filtered to tech roles, cleaned, chunked into sections and
indexed. This derived index is shared under the same license (CC BY-SA 4.0).
"""


class LiveCallRefused(RuntimeError):
    pass


class _NoLiveGroq:
    """Groq SDK stand-in: any live call means the demo is not fully cached."""

    class _Completions:
        def create(self, **kwargs: Any) -> Any:
            raise LiveCallRefused(f"live Groq call needed (model {kwargs.get('model')}); run warm_demo_cache.py first")

    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": self._Completions()})()


class _RecordingClient(GroqClient):
    """GroqClient that remembers every cache file it served."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings, client=_NoLiveGroq())  # type: ignore[arg-type]
        self.hit_files: set[Path] = set()

    def _get_from_cache(self, key: str) -> Optional[str]:
        content = super()._get_from_cache(key)
        if content is not None:
            self.hit_files.add(self._cache_dir / f"{key}.txt")
        return content


def demo_cache_files(settings: Settings) -> set[Path]:
    """Replay the demo flows the web UI runs and return the cache files they read."""
    files: set[Path] = set()
    for scenario in SCENARIOS.values():
        files |= _replay(scenario, settings)
    return files


def _replay(scenario: Scenario, settings: Settings) -> set[Path]:
    llm = _RecordingClient(settings)
    workflow = build_workflow(settings, llm)
    profile = workflow.build_profile(file_bytes=scenario.cv.read_bytes(), filename=scenario.cv.name)
    matches = workflow.match(profile, preferences="", top_k=TOP_K)
    job_id = scenario.job_id if scenario.job_id is not None else matches[0].job.job_id
    workflow.analyze_gap(profile, job_id)
    workflow.tailor(profile, job_id)
    print(f"[{scenario.name}] {len(llm.hit_files)} cache entries, 0 live calls")
    return llm.hit_files


def checkpoint(index_path: Path) -> None:
    """Fold any WAL contents into the main file so the single .db file is complete."""
    conn = sqlite3.connect(index_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True, help="Dataset repo id, e.g. <user>/careerpilot-index")
    parser.add_argument("--dry-run", action="store_true", help="List what would be uploaded; upload nothing.")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.index_path.exists():
        sys.exit(f"Index not found at {settings.index_path}; build it with scripts/build_index.py")

    try:
        cache_files = demo_cache_files(settings)
    except LiveCallRefused as err:
        sys.exit(f"Demo cache incomplete: {err}")
    finally:
        clear_app_state()  # close the index before checkpointing it
    checkpoint(settings.index_path)

    size_mb = settings.index_path.stat().st_size / 1e6
    print(f"Index: {settings.index_path.name} ({size_mb:.1f} MB); demo cache entries: {len(cache_files)}")
    if args.dry_run:
        for path in sorted(cache_files):
            print(f"  llm_cache/{path.name}")
        return

    from huggingface_hub import HfApi  # deployment-only dependency

    api = HfApi()
    api.create_repo(args.repo, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(args.repo, repo_type="dataset").private:
        sys.exit(f"{args.repo} exists and is PUBLIC; refusing to upload. Make it private on the Hub first.")

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        (staging / "llm_cache").mkdir()
        shutil.copy2(settings.index_path, staging / "careerpilot.db")
        for path in cache_files:
            shutil.copy2(path, staging / "llm_cache" / path.name)
        (staging / "README.md").write_text(DATASET_CARD, encoding="utf-8")
        api.upload_folder(
            repo_id=args.repo,
            repo_type="dataset",
            folder_path=staging,
            delete_patterns=["llm_cache/*"],  # drop entries no longer used by the demos
            commit_message="Upload CareerPilot index and demo cache",
        )
    print(f"Uploaded to https://huggingface.co/datasets/{args.repo} (private)")


if __name__ == "__main__":
    main()
