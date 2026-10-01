"""Run the web UI's request sequence against a running API (local, Docker or the public Space).

For each scenario: POST /profile -> /match -> /gap -> /tailor, exactly like the UI
(same demo CV files, empty preferences, top_k=10). Prints time per step and which
model answered each agent (cached / fallback). Exits non-zero on any HTTP error.

Usage:
    python scripts/smoke_test_api.py --base-url http://127.0.0.1:7860 [--origin https://x.vercel.app]
        [--scenario demo1 demo2 fresh] [--fresh-cv path/to/cv.txt]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = _ROOT / "tests" / "fixtures"
DEMOS = {
    "demo1": (FIXTURES / "sample_cv_backend_engineer.txt", None),
    "demo2": (FIXTURES / "sample_cv_frontend_entry_level.txt", 3900943289),
}


class Api:
    def __init__(self, base_url: str, origin: Optional[str], timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = origin
        self.timeout = timeout

    def _send(self, path: str, body: Optional[bytes], content_type: Optional[str]) -> tuple[Any, dict[str, str]]:
        headers = {"Content-Type": content_type} if content_type else {}
        if self.origin:
            headers["Origin"] = self.origin
        req = urllib.request.Request(f"{self.base_url}{path}", data=body, headers=headers,
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read()), dict(resp.headers)
        except urllib.error.HTTPError as err:
            raise SystemExit(f"{path} -> HTTP {err.code}: {err.read()[:500]!r}") from err

    def get(self, path: str) -> tuple[Any, dict[str, str]]:
        return self._send(path, None, None)

    def post_json(self, path: str, payload: dict) -> Any:
        return self._send(path, json.dumps(payload).encode(), "application/json")[0]

    def post_file(self, path: str, filename: str, content: bytes) -> Any:
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/plain\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self._send(path, body, f"multipart/form-data; boundary={boundary}")[0]


def _models(response: dict) -> str:
    calls = response.get("model_calls", [])
    return ", ".join(
        f"{c['agent']}={c['answered_model']}{' (cached)' if c['cached'] else ''}"
        f"{' FALLBACK from ' + c['requested_model'] if c['used_fallback'] else ''}"
        for c in calls
    ) or "no model calls"


def run(api: Api, name: str, cv: Path, job_id: Optional[int]) -> dict:
    timings: dict[str, float] = {}

    def timed(step: str, call: Any) -> Any:
        t0 = time.perf_counter()
        result = call()
        timings[step] = round(time.perf_counter() - t0, 2)
        print(f"  [{name}] {step:<8} {timings[step]:>6.2f}s  {_models(result)}")
        return result

    profile = timed("profile", lambda: api.post_file("/profile", cv.name, cv.read_bytes()))
    profile.pop("model_calls", None)
    matches = timed("match", lambda: api.post_json("/match", {"profile": profile, "preferences": "", "top_k": 10}))
    ids = [m["job_id"] for m in matches["matches"]]
    if not ids:
        raise SystemExit(f"[{name}] no matches")
    target = job_id if job_id in ids else ids[0]
    gap = timed("gap", lambda: api.post_json("/gap", {"profile": profile, "job_id": target}))
    tailored = timed("tailor", lambda: api.post_json("/tailor", {"profile": profile, "job_id": target}))
    v = tailored["verification"] or {}
    print(f"  [{name}] job {target} '{gap['job_title']}': {len(gap['matched_items'])} matched, "
          f"{len(gap['missing_items'])} missing | {v.get('supported_claims')}/{v.get('total_claims')} claims "
          f"supported, {len(tailored['removed_bullets'])} removed")
    calls = [c for r in (matches, gap, tailored) for c in r.get("model_calls", [])]
    return {"timings_s": timings, "total_s": round(sum(timings.values()), 2),
            "fallbacks": sum(c["used_fallback"] for c in calls), "live_calls": sum(not c["cached"] for c in calls)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", help="Send this Origin header and check the CORS answer (e.g. the Vercel URL).")
    parser.add_argument("--scenario", nargs="+", default=["demo1", "demo2"], choices=[*DEMOS, "fresh"])
    parser.add_argument("--fresh-cv", type=Path, default=FIXTURES / "sample_cv_data_scientist.txt")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    api = Api(args.base_url, args.origin, args.timeout)
    health, headers = api.get("/health")
    print(f"/health -> {health}")
    if args.origin:
        allowed = {k.lower(): v for k, v in headers.items()}.get("access-control-allow-origin")
        print(f"CORS for {args.origin}: {'allowed' if allowed == args.origin else f'NOT allowed ({allowed})'}")
        if allowed != args.origin:
            sys.exit(1)
    print(f"/health/index -> {api.get('/health/index')[0]}")

    results = {}
    for name in args.scenario:
        cv, job_id = DEMOS.get(name, (args.fresh_cv, None))
        results[name] = run(api, name, cv, job_id)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
