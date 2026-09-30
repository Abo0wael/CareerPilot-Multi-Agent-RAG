import random
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
db_path = PROJECT_ROOT / "index" / "careerpilot.db"

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT job_id, title, company_name FROM jobs").fetchall()
conn.close()

print(f"Total jobs in final index: {len(rows)}")

random.seed(2026)
sample = random.sample(rows, 50)

print("\n--- 50 RANDOM JOBS FROM FINAL INDEX (Seed 2026) ---")
for i, r in enumerate(sample, 1):
    print(f"{i:2d}. {r['title']} ({r['company_name']})")
