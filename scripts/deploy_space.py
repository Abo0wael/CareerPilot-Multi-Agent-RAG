"""Push the API server to a Hugging Face Space (Docker SDK).

Uploads only what the Dockerfile needs, plus the Space README (front matter
``sdk: docker``, ``app_port: 7860``) from deploy/hf_space/README.md. Data, the
index, ``.env`` and the LLM cache are never uploaded: the Space downloads the
index from the private dataset at start-up.

With ``--dataset`` / ``--origins`` it also sets the Space variables HF_DATASET_REPO
and ALLOWED_ORIGINS; with ``--groq-secret`` it copies GROQ_API_KEY from the local
.env into a Space secret. HF_TOKEN is added by hand in the Space settings.

Usage (after `hf auth login`):
    python scripts/deploy_space.py --space <user>/careerpilot-api [--dry-run]
        [--dataset <user>/careerpilot-index] [--origins https://<app>.vercel.app] [--groq-secret]
        [--no-upload]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from huggingface_hub import HfApi

_ROOT = Path(__file__).resolve().parent.parent

# (source relative to the repo root, destination in the Space)
FILES = [
    ("Dockerfile", "Dockerfile"),
    (".dockerignore", ".dockerignore"),
    ("requirements-server.txt", "requirements-server.txt"),
    ("scripts/start_space.py", "scripts/start_space.py"),
    ("deploy/hf_space/README.md", "README.md"),
]


def stage(target: Path) -> list[str]:
    """Copy the Space files into *target*; return their Space paths."""
    staged = []
    for source, dest in FILES:
        (target / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_ROOT / source, target / dest)
        staged.append(dest)
    for path in sorted((_ROOT / "src").rglob("*.py")):
        dest = path.relative_to(_ROOT).as_posix()
        (target / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / dest)
        staged.append(dest)
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", required=True, help="Space repo id, e.g. <user>/careerpilot-api")
    parser.add_argument("--dry-run", action="store_true", help="List the files; upload nothing.")
    parser.add_argument("--dataset", help="Set the HF_DATASET_REPO variable (the private index dataset).")
    parser.add_argument("--origins", help="Set the ALLOWED_ORIGINS variable (comma-separated, e.g. the Vercel URL).")
    parser.add_argument("--groq-secret", action="store_true", help="Copy GROQ_API_KEY from .env into a Space secret.")
    parser.add_argument("--no-upload", action="store_true", help="Only update variables/secrets (restarts the Space).")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        staged = stage(Path(tmp))
        if args.dry_run:
            print("\n".join(staged))
            print(f"{len(staged)} files")
            return

        from huggingface_hub import HfApi  # deployment-only dependency

        api = HfApi()
        api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
        configure(api, args)
        if not args.no_upload:
            api.upload_folder(
                repo_id=args.space,
                repo_type="space",
                folder_path=tmp,
                delete_patterns=["src/**"],  # remove modules deleted locally
                commit_message="Deploy CareerPilot API",
            )
            print(f"Pushed {len(staged)} files.")
    print(f"Logs: https://huggingface.co/spaces/{args.space}?logs=container")


def configure(api: HfApi, args: argparse.Namespace) -> None:
    """Set Space variables and secrets (secret values are never printed)."""
    if args.dataset:
        api.add_space_variable(args.space, "HF_DATASET_REPO", args.dataset)
        print(f"Variable HF_DATASET_REPO = {args.dataset}")
    if args.origins:
        api.add_space_variable(args.space, "ALLOWED_ORIGINS", args.origins)
        print(f"Variable ALLOWED_ORIGINS = {args.origins}")
    if args.groq_secret:
        sys.path.insert(0, str(_ROOT))
        from src.infrastructure.config import get_settings

        api.add_space_secret(args.space, "GROQ_API_KEY", get_settings().groq_api_key)
        print("Secret GROQ_API_KEY set from .env")


if __name__ == "__main__":
    sys.exit(main())
