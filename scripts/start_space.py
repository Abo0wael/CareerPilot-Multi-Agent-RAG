"""Container entry point (Hugging Face Space): fetch the index, then start the API.

1. If the index is not already on disk, download ``careerpilot.db`` and the demo
   ``llm_cache/`` entries from the private dataset ``HF_DATASET_REPO`` with the
   ``HF_TOKEN`` secret (see scripts/upload_index_to_hf.py).
2. Run uvicorn on 0.0.0.0:``PORT`` (7860 on Spaces).

An index that is already present (e.g. mounted into a local ``docker run``) is used
as is, so no token is needed then.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.infrastructure.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("start_space")


def fetch_index(repo_id: str, token: str, index_path: Path, cache_dir: Path) -> None:
    """Download the index and the demo cache entries from the private dataset."""
    from huggingface_hub import snapshot_download

    with tempfile.TemporaryDirectory(dir=index_path.parent) as tmp:
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            token=token,
            local_dir=tmp,
            allow_patterns=["careerpilot.db", "llm_cache/*.txt"],
        )
        downloaded = Path(tmp)
        shutil.move(downloaded / "careerpilot.db", index_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        entries = list((downloaded / "llm_cache").glob("*.txt"))
        for entry in entries:
            shutil.move(entry, cache_dir / entry.name)
    logger.info("Downloaded %s (%.1f MB) and %d demo cache entries",
                index_path.name, index_path.stat().st_size / 1e6, len(entries))


def main() -> None:
    settings = get_settings()
    index_path = settings.index_path
    index_path.parent.mkdir(parents=True, exist_ok=True)

    if index_path.exists():
        logger.info("Using the index already at %s", index_path)
    else:
        repo_id = os.environ.get("HF_DATASET_REPO", "").strip()
        token = os.environ.get("HF_TOKEN", "").strip()
        if not repo_id or not token:
            sys.exit("No index on disk and HF_DATASET_REPO / HF_TOKEN are not set.")
        fetch_index(repo_id, token, index_path, settings.llm_cache_dir)

    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "7860")), proxy_headers=True)


if __name__ == "__main__":
    main()
