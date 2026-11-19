"""Ranked list for outreach: A, B, disputes, C, Out; points within each band.

Usage: python engine/rank.py
Input : data/out/scored_candidates.json (score.py compare candidates)
Output: data/out/ranked.csv
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = {"A": 0, "B": 1, "Dispute: Michel decides": 2, "C": 3, "Out": 4}
COLS = ["rank", "final_band", "avg_points", "name", "domain", "country", "clay_tier", "evaluators", "jev_points",
        "claude_points", "disputes", "jev_failed_gates", "claude_failed_gates", "jev_hiring_growth",
        "jev_team_geography", "company_record", "claude_notes", "clay_profile", "gtm_daily_profile"]


def main() -> None:
    rows = json.loads((ROOT / "data" / "out" / "scored_candidates.json").read_text(encoding="utf-8"))
    cands = {c["name"]: c for c in json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))}
    rows.sort(key=lambda r: (ORDER[r["final_band"]], -float(r["avg_points"])))
    with (ROOT / "data" / "out" / "ranked.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(rows, 1):
            c = cands.get(r["name"], {})
            w.writerow({**r, "rank": i, "clay_profile": c.get("clay_profile", ""), "gtm_daily_profile": c.get("gtm_daily_profile", "")})
    counts = {}
    for r in rows:
        counts[r["final_band"]] = counts.get(r["final_band"], 0) + 1
    print(f"ranked {len(rows)} -> data/out/ranked.csv | {counts}")


if __name__ == "__main__":
    main()
