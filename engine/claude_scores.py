"""Write Claude's blind scores (made in a Claude Code session that read only
the dossiers and config/rubric.yaml) to data/scores/claude/<key>.json.

Usage: python engine/claude_scores.py <batch.json>
batch.json: {key: {"gates": [operating, service_business, has_team, recent_activity],
                   "levels": [clay_depth, structure, team_geography, fronts_overlap, reachability, hiring_growth],
                   "notes": "..."}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATES = ("operating", "service_business", "has_team", "recent_activity", "remote_possible")
LEVELS = ("clay_depth", "structure", "team_geography", "fronts_overlap", "reachability", "hiring_growth")


def main() -> None:
    batch = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = ROOT / "data" / "scores" / "claude"
    out.mkdir(parents=True, exist_ok=True)
    for key, r in batch.items():
        assert (ROOT / "data" / "dossiers" / f"{key}.md").exists(), key
        rec = {"gates": dict(zip(GATES, r["gates"])), "levels": dict(zip(LEVELS, r["levels"])), "evidence": {},
               "notes": r["notes"], "rubric": "v2.1",
               "model": "claude-opus-5-5 (Claude Code session, blind to Jev; scored from dossiers only)"}
        (out / f"{key}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(batch)} written")


if __name__ == "__main__":
    main()
