"""Free hiring signal #2: candidates that appear as employers in the jobs
job-fit-screener already collected (~3,500 per run from 18 boards).
Matched by normalized company name (and the Clay-directory aliases).

Usage: python engine/sources/jobboard_matches.py
Output: data/raw/jobboard_matches.json  {candidate name: [ {title, location, source, link}, ... ]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from consolidate import name_key  # noqa: E402

JFS = ROOT.parent / "job-fit-screener" / "output"
OUT = ROOT / "data" / "raw" / "jobboard_matches.json"


def main() -> None:
    cands = json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))
    keys: dict[str, str] = {}
    for c in cands:
        for n in [c["name"], *c.get("aliases", [])]:
            k = name_key(n)
            if len(k) >= 4:
                keys.setdefault(k, c["name"])
    hits: dict[str, list[dict]] = {}
    seen = set()
    for f in ("vagas_coletadas_intl.json", "vagas_coletadas.json"):
        path = JFS / f
        if not path.exists():
            continue
        for j in json.loads(path.read_text(encoding="utf-8")):
            name = keys.get(name_key(j.get("empresa", "")))
            if not name or j.get("link") in seen:
                continue
            seen.add(j.get("link"))
            hits.setdefault(name, []).append({"title": j.get("titulo", ""), "location": j.get("cidade", ""),
                                              "source": j.get("fonte", ""), "link": j.get("link", ""),
                                              "posted": j.get("publicado_em", "")})
    OUT.write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(len(v) for v in hits.values())} jobs at {len(hits)} candidates")


if __name__ == "__main__":
    main()
