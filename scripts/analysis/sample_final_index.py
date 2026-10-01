"""Draw the 50-posting sample of the tech-subset precision audit.

Reproduces the sample in outputs/evaluation/tech_subset_audit.md (seed 42); each
title there was then classified by hand as tech or non-tech (41/50 = 82%).

Usage: python scripts/analysis/sample_final_index.py
"""

import random
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
db_path = PROJECT_ROOT / "index" / "careerpilot.db"

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT job_id, title, company_name FROM jobs ORDER BY job_id").fetchall()
conn.close()

print(f"Total jobs in final index: {len(rows)}")

sample = random.Random(42).sample(rows, 50)

print("\n--- 50 RANDOM JOBS FROM FINAL INDEX (seed 42) ---")
for i, r in enumerate(sample, 1):
    print(f"{i:2d}. {r['job_id']} {r['title']} ({r['company_name']})")
