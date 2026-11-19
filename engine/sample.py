"""Pick the blind Claude review sample for the full run (Michel, 2026-11-08:
"Jev on everything + Claude on a sample", the Creator Supply Engine pattern).

Sample = the cases where Jev is most likely to be wrong, plus a control:
  - borderline: Jev points within BORDER of a band cut (A or B)
  - doubtful: any gate or cap with probability in DOUBT
  - only the SIZE closest to a cut are kept (Jev scores cluster near the cuts)
  - control: CONTROL_N more at random
Pilot companies are excluded (already double-scored and labeled by Michel).

Outputs:
  data/out/claude_sample.json      keys only, shuffled: what Claude reviews (no Jev info)
  data/out/claude_sample_key.json  why each key was picked; read only after Claude is done
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research import key_of  # noqa: E402
from score import RUBRIC, total  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BORDER, DOUBT, SEED = 6, (0.4, 0.6), 20261108
SIZE, CONTROL_N = 20, 5  # Jev scores cluster near the cuts, so rank by closeness and keep the closest


def main() -> None:
    cands = json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))
    pilot = {key_of(c) for c in json.loads((ROOT / "data" / "out" / "pilot.json").read_text(encoding="utf-8"))}
    cuts = [RUBRIC["bands"]["A"], RUBRIC["bands"]["B"]]
    picked, clear, candidates_close = {}, [], []
    for c in cands:
        k = key_of(c)
        if k in pilot:
            continue
        path = ROOT / "data" / "scores" / "jev" / f"{k}.json"
        if not path.exists():
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        pts, _, _, _ = total(rec, c["region"])
        why, closeness = [], 1.0
        dist = min(abs(pts - cut) for cut in cuts)
        if dist <= BORDER:
            why.append(f"borderline ({pts} pts)")
            closeness = min(closeness, dist / BORDER)
        doubtful = {g: p for g, p in rec["gates"].items() if p is not None and DOUBT[0] <= p <= DOUBT[1]}
        if doubtful:
            why.append("doubtful " + ", ".join(doubtful))
            closeness = min(closeness, min(abs(p - 0.5) for p in doubtful.values()) / (DOUBT[1] - 0.5))
        if why:
            candidates_close.append((closeness, k, "; ".join(why)))
        else:
            clear.append(k)
    candidates_close.sort()
    for _, k, why in candidates_close[:SIZE]:
        picked[k] = why
    rng = random.Random(SEED)
    rest = clear + [k for _, k, _ in candidates_close[SIZE:]]  # not-picked borderline cases can be controls too
    for k in rng.sample(sorted(rest), CONTROL_N):
        picked[k] = "control (random)"
    keys = list(picked)
    rng.shuffle(keys)
    out = ROOT / "data" / "out"
    (out / "claude_sample.json").write_text(json.dumps(keys, indent=1), encoding="utf-8")
    (out / "claude_sample_key.json").write_text(json.dumps(picked, indent=1, ensure_ascii=False), encoding="utf-8")
    kinds = {"borderline": 0, "doubtful": 0, "control": 0}
    for v in picked.values():
        for kind in kinds:
            kinds[kind] += kind in v
    print(f"sample: {len(keys)} of {len(cands) - len(pilot)} non-pilot ({kinds}); {len(candidates_close)} were near a cut")


if __name__ == "__main__":
    main()
