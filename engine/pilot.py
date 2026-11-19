"""Pick a stratified pilot of 20 candidates for calibration.

The pilot must cover the cases the rubric has to get right, not just the
best-looking agencies: every Clay tier, GTM Daily-only agencies (incl. a
guessed domain and a large one), Europe, solo-looking partners, and the
agencies that showed up in the GTM job board.

Output: data/out/pilot.json (list of candidate records, same shape as candidates.json)
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"
SEED = 20261107

QUOTAS = [  # (label, predicate, how many)
    ("hiring on GTM Daily", lambda c: bool(c["gtm_jobs"]), 2),
    ("Elite Studio", lambda c: c["clay_tier"] == "Elite Studio", 2),
    ("Studio", lambda c: c["clay_tier"] == "Studio", 2),
    ("Advanced Artisan", lambda c: c["clay_tier"] == "Advanced Artisan", 3),
    ("Artisan, Europe", lambda c: c["clay_tier"] == "Artisan" and c["country"] not in {"US", "CANADA"}, 2),
    ("Artisan, person-named", lambda c: c["clay_tier"] == "Artisan" and is_person_name(c["name"]), 2),
    ("Artisan, other", lambda c: c["clay_tier"] == "Artisan", 3),
    ("GTM Daily only, guessed domain", lambda c: not c["clay_tier"] and c["domain_source"] == "guessed", 2),
    ("GTM Daily only", lambda c: not c["clay_tier"] and c["domain"], 2),
]


def is_person_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z\-]+", name.strip()))


def main() -> None:
    cands = json.loads((OUT / "candidates.json").read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    chosen: list[dict] = []
    seen: set[str] = set()
    for label, pred, n in QUOTAS:
        pool = [c for c in cands if pred(c) and c["name"] not in seen and (c["domain"] or c["linkedin"])]
        rng.shuffle(pool)
        for c in pool[:n]:
            chosen.append({**c, "pilot_stratum": label})
            seen.add(c["name"])
    (OUT / "pilot.json").write_text(json.dumps(chosen, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in chosen:
        print(f"{c['pilot_stratum']:<32} {c['name']:<40} {c['domain'] or c['linkedin']:<35} {c['country']}")
    print(len(chosen), "picked")


if __name__ == "__main__":
    main()
