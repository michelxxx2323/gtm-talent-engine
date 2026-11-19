"""Team geography from Clay: current employees per country (Clay first).

Workflow "GTM Talent Engine — team geography (headcount by country)"
(CLAY_GEOGRAPHY_WORKFLOW in .env): CSV upload (name, domain, company_identifier)
  -> Employee headcount by country (cpj-get-counts-by-country-for-profiles-v2, 1 credit)

Rows start with `clay workflows triggers csv upload/run` (README). This
script only READS finished runs (no credits) and summarizes each company:
share of the team in North America/Europe, in LatAm and elsewhere, and how
many people are in Brazil. These map straight to the rubric's team_geography
levels (mostly elsewhere / mixed / mainly NA-EU / NA-EU and already employs
people in Brazil).

Usage: python engine/sources/clay_geography.py
Output: data/raw/clay_geography.json {domain: {people_count, by_country, share_west, share_latam,
                                                share_other, brazil, run_id}}
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "sources"))
sys.path.insert(0, str(ROOT / "engine"))
from clay_enrich import clay  # noqa: E402
from consolidate import root_domain  # noqa: E402
from research import env  # noqa: E402

WORKFLOW = env("CLAY_GEOGRAPHY_WORKFLOW")
OUT = ROOT / "data" / "raw" / "clay_geography.json"

WEST = {"united states", "us", "usa", "canada", "ca", "united kingdom", "uk", "gb", "ireland", "ie", "germany", "de",
        "france", "fr", "netherlands", "nl", "belgium", "be", "spain", "es", "portugal", "pt", "italy", "it",
        "switzerland", "ch", "austria", "at", "sweden", "se", "norway", "no", "denmark", "dk", "finland", "fi",
        "poland", "pl", "czech republic", "czechia", "cz", "estonia", "ee", "lithuania", "lt", "latvia", "lv",
        "romania", "ro", "greece", "gr", "hungary", "hu", "luxembourg", "lu", "bulgaria", "bg", "croatia", "hr",
        "slovenia", "si", "slovakia", "sk", "serbia", "rs", "ukraine", "ua", "republic of north macedonia",
        "north macedonia", "macedonia", "mk", "albania", "al", "bosnia and herzegovina", "ba", "montenegro", "me",
        "moldova", "md", "kosovo", "xk", "iceland", "is", "malta", "mt", "cyprus", "cy", "monaco", "liechtenstein",
        "andorra"}
LATAM = {"brazil", "br", "argentina", "ar", "mexico", "mx", "colombia", "co", "chile", "cl", "peru", "pe", "uruguay",
         "uy", "costa rica", "cr", "ecuador", "ec", "guatemala", "gt", "venezuela", "ve", "paraguay", "py", "bolivia", "bo",
         "dominican republic", "do", "panama", "pa", "el salvador", "sv", "honduras", "hn", "nicaragua", "ni"}


def summarize(result: dict) -> dict:
    rows = [r for r in result.get("people_count_by_country") or [] if r.get("country")]
    total = result.get("people_count") or sum(r.get("count") or 0 for r in rows) or 0
    by = sorted(((r["country"], r.get("count") or 0) for r in rows), key=lambda x: -x[1])

    def share(group: set[str]) -> float | None:
        return round(sum(n for c, n in by if c.strip().lower() in group) / total, 2) if total else None

    return {"people_count": total, "by_country": by[:10], "share_west": share(WEST), "share_latam": share(LATAM),
            "share_other": share_other(by, total), "brazil": sum(n for c, n in by if c.strip().lower() in ("brazil", "br"))}


def share_other(by: list, total: int) -> float | None:
    """Share of the team outside North America, Europe and LatAm."""
    if not total:
        return None
    return round(sum(n for c, n in by if c.strip().lower() not in WEST | LATAM) / total, 2)


def identifier_index() -> dict[str, str]:
    """company_identifier (LinkedIn URL or domain) -> domain, from every CSV sent to the workflow."""
    idx = {}
    for path in (ROOT / "clay").glob("geo_batch*_index.csv"):
        for row in csv.DictReader(path.open(encoding="utf-8")):
            idx[row["company_identifier"].rstrip("/").lower()] = row["domain"]
    return idx


def main() -> None:
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    idx = identifier_index()
    page = clay("workflows", "runs", "list", WORKFLOW, "--limit", "100")
    runs, cursor = page.get("data", []), page.get("cursor")
    while cursor:
        page = clay("workflows", "runs", "list", WORKFLOW, "--limit", "100", "--cursor", cursor)
        runs += page.get("data", [])
        cursor = page.get("cursor")
    status = {}
    for run in runs:
        status[run["status"]] = status.get(run["status"], 0) + 1
        if run["status"] != "completed" or any(v.get("run_id") == run["runId"] for v in out.values()):
            continue
        for st in clay("workflows", "runs", "steps", WORKFLOW, run["runId"]).get("data", []):
            result = (st.get("stepOutputs") or {}).get("result")
            if not isinstance(result, dict):
                continue
            ident = (st.get("stepInputs") or {}).get("company_identifier") or ""
            domain = idx.get(ident.rstrip("/").lower()) or ("" if "linkedin.com" in ident else root_domain(ident))
            out[domain or ident] = {**summarize(result), "identifier": ident, "run_id": run["runId"]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"runs by status {status} | companies with geography: {len(out)}")


if __name__ == "__main__":
    main()
