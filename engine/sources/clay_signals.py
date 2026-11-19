"""Team geography and hiring signals from Clay Search (free plan).

Websites rarely say where a team works or list every open role, and Apollo's
people search is paid. Clay Search can filter OUR candidate domains by
employee location and by open job postings. It cannot count (no count mode),
so each signal is a yes/no query that returns only the matching companies.

Cost: every company returned uses 1 of the workspace's 100 results per rolling
30 days (50 per search). The script reads `periodQuota` after each page and
stops before the --budget (default 100) or the remaining quota is exceeded.
Queries run in priority order, so if the budget runs out it is the least
important signal that is missing.

Usage: python engine/sources/clay_signals.py [--budget 100] [--only name,name] [--dry-run]
Output: data/raw/clay_signals.json  {signal: {"domains": [...], "complete": bool, ...}, "_quota": {...}}
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from consolidate import root_domain  # noqa: E402

OUT = ROOT / "data" / "raw" / "clay_signals.json"
WEST = ["United States", "Canada", "United Kingdom", "Ireland", "Germany", "France", "Netherlands", "Belgium",
        "Spain", "Portugal", "Italy", "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Poland",
        "Czech Republic", "Estonia", "Lithuania", "Latvia", "Romania", "Greece", "Hungary", "Luxembourg"]
OFFSHORE = ["Pakistan", "India", "Bangladesh", "Sri Lanka", "Nepal", "Philippines", "Indonesia", "Vietnam", "Malaysia"]
GTM_JOB_TITLES = ["GTM Engineer", "Go-to-Market Engineer", "Revenue Operations", "Sales Operations",
                  "Marketing Operations", "Campaign Manager", "Growth Engineer", "Automation", "Clay", "Outbound",
                  "Lead Generation", "Data Enrichment"]


def q_list(values: list[str]) -> str:
    return "(" + ", ".join(json.dumps(v) for v in values) + ")"


def here(countries: list[str]) -> str:
    return f"is_current = true and person.location_country in {q_list(countries)}"


# Priority order (Michel, 2026-11-08): hiring and where the team works first;
# "already employs people in Brazil" last. The target stays international agencies.
SIGNALS = [
    ("hiring_gtm_role", f"jobs.exists(job_still_open = true and job_title is_similar_to {q_list(GTM_JOB_TITLES)})"),
    ("offshore_concentrated", f"people.count({here(OFFSHORE)}) >= 3 and not people.count({here(WEST)}) >= 3"),
    ("mixed_west_offshore", f"people.count({here(OFFSHORE)}) >= 3 and people.count({here(WEST)}) >= 3"),
    ("employs_in_brazil", "people.exists(is_current = true and person.location_country = \"Brazil\")"),
    ("hiring_any_role", "jobs.exists(job_still_open = true)"),
]


def clay(*args: str) -> dict:
    exe = shutil.which("clay") or "clay"  # on Windows this is clay.cmd
    res = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8")
    try:
        data = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    if res.returncode != 0:
        raise RuntimeError(f"clay {' '.join(args[:3])} failed ({res.returncode}): {(res.stdout or res.stderr)[:400]}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=100, help="max results to spend in this run")
    ap.add_argument("--only", default="", help="comma-separated signal names")
    ap.add_argument("--dry-run", action="store_true", help="print the queries, spend nothing")
    args = ap.parse_args()

    cands = json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))
    domains = sorted({c["domain"] for c in cands if c["domain"]})
    ident = f"clay.include_company_identifiers({q_list(domains)})"
    state = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    only = {s for s in args.only.split(",") if s}
    spent = 0

    for name, cond in SIGNALS:
        if only and name not in only:
            continue
        if state.get(name, {}).get("complete"):
            print(f"{name}: already complete ({len(state[name]['domains'])} companies), skipped")
            continue
        query = f"select from companies where {ident} and {cond}"
        if args.dry_run:
            print(f"--- {name} ({len(query)} chars)\n{query[:300]} ... {cond}")
            continue
        room = args.budget - spent
        remaining = state.get("_quota", {}).get("remaining")
        if remaining is not None:
            room = min(room, remaining)
        if room <= 0:
            print(f"{name}: no budget left, stopping")
            break
        search = clay("searches", "query-mode", "create", "--query", query)
        found, complete = [], False
        while room > 0:
            page = clay("searches", "query-mode", "run", search["searchId"], "--limit", str(min(50, room)))
            rows = page.get("data", [])
            spent += len(rows)
            room -= len(rows)
            found += [{"domain": root_domain(r.get("domain") or ""), "name": r.get("name"), "size": r.get("size"),
                       "country": r.get("country"), "linkedin_url": r.get("linkedin_url")} for r in rows]
            if page.get("periodQuota"):
                state["_quota"] = page["periodQuota"]
                room = min(room, page["periodQuota"]["remaining"])
            if not page.get("hasMore"):
                complete = page.get("exhaustionReason") != "query_limit"
                break
        state[name] = {"domains": sorted({f["domain"] for f in found if f["domain"]}), "rows": found,
                       "complete": complete, "condition": cond}
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        q = state.get("_quota", {})
        print(f"{name}: {len(found)} companies (complete={complete}) | spent this run {spent} | "
              f"quota {q.get('used')}/{q.get('limit')}, resets {q.get('resetsAt')}", flush=True)
    if not args.dry_run:
        print(f"total spent this run: {spent}")


if __name__ == "__main__":
    main()
