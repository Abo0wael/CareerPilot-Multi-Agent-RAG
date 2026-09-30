"""Query Groq API for full model details (key read from .env, never hard-coded)."""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.infrastructure.config import get_settings  # noqa: E402

url = "https://api.groq.com/openai/v1/models"
key = get_settings().groq_api_key

resp = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
data = resp.json()

for m in sorted(data["data"], key=lambda x: x["id"]):
    print(json.dumps(m, indent=2))
    print("---")
