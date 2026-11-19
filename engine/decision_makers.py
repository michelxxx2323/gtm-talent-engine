"""Phase 3: decision makers for the companies Michel will contact.

Sources (Clay first):
  - Clay Search (people at the company, current role, seniority Founder/Owner/
    C-suite/Partner), saved by hand from `clay searches query-mode run` into
    data/private/people_*.json (search results quota, not credits)
  - names already in the Clay Solutions Partner Directory (partners listed by
    their founder's name, e.g. "Jane Doe" instead of the agency name)

Picks per company: a PRIMARY contact (CEO / founder: owns the hiring decision
in a small agency) and a BACKUP (COO / CRO / Head of Ops / CTO: usually the
hiring manager for delivery roles). Other people found are kept as "other"
(e.g. a Brazilian on the team, useful for a referral).

People data stays in data/private/ (gitignored): names and LinkedIn URLs are
public professional data, but they never go to the public repo or case page.
No emails or phone numbers are collected.

Usage: python engine/decision_makers.py [A|AB]
Output: data/private/decision_makers.csv
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from consolidate import name_key  # noqa: E402

PRIVATE = ROOT / "data" / "private"
TOP = re.compile(r"\b(ceo|chief executive|founder|co-?founder|owner|president|managing (director|partner))\b", re.I)
OPS = re.compile(r"\b(coo|chief operating|cro|chief revenue|cto|chief technology|chief [a-z& ]+ officer|"
                 r"head of [a-z ]*(operations|delivery|gtm|growth|revops|execution|customer success)|"
                 r"vp (of )?(operations|delivery)|partner)\b", re.I)


NOT_LEADERSHIP = re.compile(r"\b(account|product|process|project|content|task|data|campaign) owner\b", re.I)


def role_type(title: str) -> str:
    t = title or ""
    if NOT_LEADERSHIP.search(t) and not re.search(r"\b(ceo|founder|chief)\b", t, re.I):
        return "other"
    if re.search(r"\b(ceo|chief executive)\b", t, re.I) or (TOP.search(t) and not OPS.search(t)):
        return "top"
    if OPS.search(t):
        return "ops"
    if TOP.search(t):
        return "top"
    return "other"


def company_match(person_company: str, row: dict, aliases: list[str]) -> bool:
    pk = name_key(person_company or "")
    names = [row["name"], *aliases, row["domain"].split(".")[0]]
    return bool(pk) and any(pk == name_key(n) or pk in name_key(n) or name_key(n) in pk for n in names if name_key(n))


def main() -> None:
    bands = {"A": ("A",), "AB": ("A", "B")}[sys.argv[1] if len(sys.argv) > 1 else "A"]
    ranked = [r for r in csv.DictReader((ROOT / "data" / "out" / "ranked.csv").open(encoding="utf-8-sig"))
              if r["final_band"] in bands]
    cands = {c["name"]: c for c in json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))}
    people = []
    for f in glob.glob(str(PRIVATE / "people_*.json")):
        people += json.loads(Path(f).read_text(encoding="utf-8")).get("data", [])

    manual_path = PRIVATE / "manual_contacts.json"
    manual = json.loads(manual_path.read_text(encoding="utf-8")) if manual_path.exists() else {}
    manual = {k: v for k, v in manual.items() if not k.startswith("_")}
    out = []
    for r in ranked:
        aliases = cands.get(r["name"], {}).get("aliases", [])
        found, seen = [], set()
        for p in people:
            for e in p.get("matched_experiences") or []:
                if company_match(e.get("company"), r, aliases) and p.get("linkedin_url") not in seen:
                    seen.add(p.get("linkedin_url"))
                    found.append({"name": p.get("name"), "title": e.get("title") or "", "location": (p.get("location") or {}).get("name") or "",
                                  "linkedin": p.get("linkedin_url") or "", "source": "clay_search"})
        # a partner listed under a person's name is usually the founder
        for a in aliases:  # the company's own name is not used: a name like "Red Fox" looks like a person's name too
            if re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z\-]+", a) and not any(name_key(a) == name_key(x["name"]) for x in found):
                found.append({"name": a, "title": "listed as the Clay partner (likely founder)", "location": "", "linkedin": "",
                              "source": "clay_directory"})
        for x in found:
            x["role_type"] = role_type(x["title"])
        tops = [x for x in found if x["role_type"] == "top"]
        tops.sort(key=lambda x: (not re.search(r"\b(ceo|chief executive)\b", x["title"], re.I), x["source"] != "clay_search"))
        ops = [x for x in found if x["role_type"] == "ops"]
        primary = tops[0] if tops else (ops[0] if ops else None)
        backup = next((x for x in ops + tops if x is not primary), None)
        # manual picks (data/private/manual_contacts.json) win: e.g. the person who posted the job
        old_primary = primary
        picks = manual.get(r["domain"], [])
        for m in picks:
            x = next((f for f in found if name_key(f["name"]) == name_key(m["name"])), None)
            if not x:
                x = {k: m.get(k, "") for k in ("name", "title", "location", "linkedin")}
                x["source"] = m.get("source", "manual")
                x["role_type"] = role_type(x["title"])
                found.append(x)
            if m["contact"] == "primary":
                primary, backup = x, (backup if backup is not x else None)
            elif m["contact"] == "backup":
                backup = x
        if any(m["contact"] == "primary" for m in picks) and not any(m["contact"] == "backup" for m in picks) \
                and old_primary is not None and old_primary is not primary:
            backup = old_primary  # the Clay pick steps down to backup
        if primary is backup:
            backup = None
        for kind, x in [("primary", primary), ("backup", backup)] + [("other", x) for x in found if x not in (primary, backup)]:
            if x:
                out.append({"band": r["final_band"], "points": r["avg_points"], "company": r["name"], "domain": r["domain"],
                            "contact": kind, **{k: x[k] for k in ("name", "title", "location", "linkedin", "role_type", "source")}})
        if not primary:
            out.append({"band": r["final_band"], "points": r["avg_points"], "company": r["name"], "domain": r["domain"],
                        "contact": "MISSING", "name": "", "title": "", "location": "", "linkedin": "", "role_type": "", "source": ""})
    PRIVATE.mkdir(parents=True, exist_ok=True)
    cols = ["band", "points", "company", "domain", "contact", "name", "title", "location", "linkedin", "role_type", "source"]
    with (PRIVATE / "decision_makers.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    missing = [o["company"] for o in out if o["contact"] == "MISSING"]
    no_backup = [r["name"] for r in ranked if not any(o["company"] == r["name"] and o["contact"] == "backup" for o in out)]
    print(f"{len(ranked)} companies | {sum(o['contact'] == 'primary' for o in out)} primary | "
          f"{sum(o['contact'] == 'backup' for o in out)} backup | missing primary: {missing} | no backup: {no_backup}")


if __name__ == "__main__":
    main()
