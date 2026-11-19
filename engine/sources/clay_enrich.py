"""Company records from the Clay enrichment waterfall (Clay first, 2026-11-08).

Workflow "GTM Talent Engine — company enrichment waterfall" (CLAY_ENRICH_WORKFLOW in .env):
  CSV upload (name, domain, linkedin_url)
    -> Enrich company (Clay, cpj-enrich-company-v2, 0.5 credit)
    -> "Clay found nothing?" (conditional; run ends when Clay found the company)
    -> Enrich company (Datagma fallback, 0.4 credit)

Rows are started with `clay workflows triggers csv upload/run` (see README).
This script only READS finished runs (no credits) and writes one normalized
record per domain.

Usage: python engine/sources/clay_enrich.py
Output: data/raw/clay_company.json  {domain: {source, name, employee_count, size, founded, hq, country,
                                               linkedin, description, specialties, industry, run_id}}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from consolidate import root_domain  # noqa: E402
from research import env  # noqa: E402

WORKFLOW = env("CLAY_ENRICH_WORKFLOW")
OUT = ROOT / "data" / "raw" / "clay_company.json"


def clay(*args: str) -> dict:
    exe = shutil.which("clay") or "clay"
    res = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise RuntimeError(f"clay {' '.join(args[:3])}: {(res.stdout or res.stderr)[:300]}")
    return json.loads(res.stdout)


def runs() -> list[dict]:
    out, cursor = [], None
    while True:
        args = ["workflows", "runs", "list", WORKFLOW, "--limit", "100"]
        if cursor:
            args += ["--cursor", cursor]
        page = clay(*args)
        out += page.get("data", [])
        cursor = page.get("cursor") or page.get("nextCursor")
        if not cursor:
            return out


def from_clay(r: dict) -> dict:
    primary = next((l for l in r.get("locations") or [] if l.get("is_primary")), {})
    return {"source": "clay", "name": r.get("name"), "employee_count": r.get("employee_count"), "size": r.get("size"),
            "founded": r.get("founded"), "hq": r.get("locality") or primary.get("address"), "country": r.get("country"),
            "linkedin": r.get("url"), "description": (r.get("description") or "")[:800],
            "derived_description": ((r.get("derived_datapoints") or {}).get("description") or "")[:800],
            "specialties": r.get("specialties") or [], "industry": r.get("industry"),
            "follower_count": r.get("follower_count"), "locations": [l.get("address") for l in r.get("locations") or []][:6]}


def from_datagma(r: dict) -> dict:
    flat = r.get("result") if isinstance(r.get("result"), dict) else r
    return {"source": "datagma", "name": flat.get("name"), "employee_count": flat.get("employees") or flat.get("employee_count"),
            "size": flat.get("size") or flat.get("employeesRange"), "founded": flat.get("founded") or flat.get("foundedYear"),
            "hq": flat.get("location") or flat.get("city"), "country": flat.get("country"),
            "linkedin": flat.get("linkedin") or flat.get("linkedInUrl"), "description": (flat.get("description") or "")[:800],
            "specialties": flat.get("specialties") or [], "industry": flat.get("industry"), "raw_keys": sorted(flat)[:40]}


def main() -> None:
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    status = {}
    for run in runs():
        status[run["status"]] = status.get(run["status"], 0) + 1
        if run["status"] != "completed":
            continue
        steps = clay("workflows", "runs", "steps", WORKFLOW, run["runId"]).get("data", [])
        domain, rec = "", None
        for st in steps:
            inputs = st.get("stepInputs") or {}
            domain = domain or root_domain(inputs.get("company_identifier") or inputs.get("data") or "")
            result = (st.get("stepOutputs") or {}).get("result")
            if not isinstance(result, dict) or not result:
                continue
            if "Clay)" in (st.get("nodeName") or "") and result.get("name"):
                rec = from_clay(result)
            elif "Datagma" in (st.get("nodeName") or ""):
                rec = rec or from_datagma(result)
        if domain:
            out[domain] = {**(rec or {"source": "none"}), "run_id": run["runId"]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    found = {}
    for v in out.values():
        found[v["source"]] = found.get(v["source"], 0) + 1
    print(f"runs by status {status} | records {len(out)} by source {found}")


if __name__ == "__main__":
    main()
