"""Phase 3: pipeline in Attio (Michel's CRM, shared with the Passionfroot case).

What it writes (idempotent: safe to run again):
  - list "GTM Talent Pipeline" (api_slug gtm_talent_pipeline) on Companies, with its own
    attributes; the Passionfroot list `supply_pipeline` is never touched
  - Companies: asserted by domain (existing records are updated, not duplicated)
  - People: decision makers (name, job title, LinkedIn, company link, a description).
    No email, no phone, and no `creator_id`, so the Passionfroot case snapshot
    (which counts only people with creator_id) does not change
  - one list entry per company, asserted by parent; an existing entry keeps its
    stage (the sync never moves a company back)

Usage: python engine/attio_sync.py [A|AB|ABD] [--dry-run] [--records-only]

Note (2026-11-13): POST /v2/lists returned HTTP 500 three times, so the list is
created by hand in Attio (name "GTM Talent Pipeline", object Companies, slug
gtm_talent_pipeline); the script then adds its attributes, stages and entries.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from research import env  # noqa: E402

API = "https://api.attio.com/v2"
LIST = {"name": "GTM Talent Pipeline", "api_slug": "gtm_talent_pipeline"}
STAGES = ["Qualified", "Contact found", "Drafted", "Contacted", "Replied", "Call", "Trial project", "Offer", "Closed"]
LIST_ATTRS = [
    {"api_slug": "stage", "title": "Stage", "type": "status"},
    {"api_slug": "band", "title": "Band", "type": "select", "options": ["A", "B", "C", "Dispute"]},
    {"api_slug": "fit_score", "title": "Fit score", "type": "number"},
    {"api_slug": "clay_tier", "title": "Clay partner tier", "type": "text"},
    {"api_slug": "team_geography", "title": "Team geography", "type": "text"},
    {"api_slug": "brazilians_on_team", "title": "People in Brazil", "type": "number"},
    {"api_slug": "hiring_signal", "title": "Hiring signal", "type": "text"},
    {"api_slug": "why_fit", "title": "Why it fits", "type": "text"},
    {"api_slug": "primary_contact", "title": "Primary contact", "type": "text"},
    {"api_slug": "backup_contact", "title": "Backup contact", "type": "text"},
    {"api_slug": "engine_version", "title": "Engine version", "type": "text"},
]
DRY = "--dry-run" in sys.argv
RECORDS_ONLY = "--records-only" in sys.argv  # Companies + People only (when the list cannot be created by API)
LOG: list[str] = []


def attio(method: str, path: str, body: dict | None = None) -> dict:
    if DRY and method != "GET" and not path.endswith("/query"):
        LOG.append(f"{method} {path} {json.dumps(body, ensure_ascii=False)[:220] if body else ''}")
        return {"data": {"id": {"record_id": f"dry-{len(LOG)}", "entry_id": f"dry-{len(LOG)}"}}}
    for attempt in range(5):
        r = requests.request(method, f"{API}/{path}", json=body, timeout=30,
                             headers={"Authorization": f"Bearer {env('ATTIO_API_KEY')}", "Content-Type": "application/json"})
        if r.status_code == 429:
            time.sleep(1 + attempt)
            continue
        if not r.ok:
            raise RuntimeError(f"{method} {path}: HTTP {r.status_code} {r.text[:400]}")
        return r.json() if r.text else {}
    raise RuntimeError(f"{method} {path}: rate limited")


def ensure_schema() -> None:
    lists = attio("GET", "lists")["data"]
    if not any(l["api_slug"] == LIST["api_slug"] for l in lists):
        attio("POST", "lists", {"data": {**LIST, "parent_object": "companies", "workspace_access": "full-access",
                                         "workspace_member_access": []}})
    target = f"lists/{LIST['api_slug']}"
    existing = set() if DRY and not any(l["api_slug"] == LIST["api_slug"] for l in lists) else \
        {a["api_slug"] for a in attio("GET", f"{target}/attributes")["data"]}
    for a in LIST_ATTRS:
        if a["api_slug"] not in existing:
            spec = {k: v for k, v in a.items() if k != "options"}
            attio("POST", f"{target}/attributes", {"data": {"description": None, "is_required": False, "is_unique": False,
                                                            "is_multiselect": False, "config": {}, **spec}})
        if a.get("options"):
            have = set() if DRY and a["api_slug"] not in existing else \
                {o["title"] for o in attio("GET", f"{target}/attributes/{a['api_slug']}/options")["data"]}
            for o in a["options"]:
                if o not in have:
                    attio("POST", f"{target}/attributes/{a['api_slug']}/options", {"data": {"title": o}})
    have = set() if DRY and "stage" not in existing else \
        {s["title"] for s in attio("GET", f"{target}/attributes/stage/statuses")["data"]}
    for s in STAGES:
        if s not in have:
            attio("POST", f"{target}/attributes/stage/statuses", {"data": {"title": s}})


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def company_payload(r: dict, cc: dict, geo: dict, apollo: dict, ats: dict, contacts: list[dict]) -> tuple[dict, dict]:
    li = (cc.get("linkedin") or apollo.get("linkedin") or "").replace("http://", "https://")
    company = {k: v for k, v in {"name": r["name"].replace("🚢", "").replace("🐰", "").replace("🌲", "").strip(),
                                 "domains": [r["domain"]], "linkedin": li or None}.items() if v}
    jobs = [j["title"] for j in ats.get("jobs", []) if j.get("gtm_role")] if ats.get("confidence") in ("high", "medium") else []
    hiring = []
    if jobs:
        hiring.append("Open GTM roles: " + ", ".join(jobs[:4]))
    if apollo.get("growth_12m"):
        hiring.append(f"headcount {apollo['growth_12m']:+.0%} in 12 months (Apollo)")
    geo_txt = ""
    if geo.get("people_count"):
        geo_txt = (f"{geo['people_count']} people: North America/Europe {round(geo['share_west'] * 100)}%, "
                   f"offshore {round(geo['share_offshore'] * 100)}%, LatAm {round(geo['share_latam'] * 100)}%, Brazil {geo['brazil']} "
                   f"(Clay, top: {', '.join(f'{c} {n}' for c, n in geo['by_country'][:3])})")
    primary = next((c for c in contacts if c["contact"] == "primary"), None)
    backup = next((c for c in contacts if c["contact"] == "backup"), None)
    why = r.get("claude_notes") or ""
    if not why:
        bits = [f"Clay {r['clay_tier']} partner" if r["clay_tier"] else "", geo_txt.split(" (Clay")[0] if geo_txt else "",
                f"{cc.get('employee_count')} employees" if cc.get("employee_count") else ""]
        why = "; ".join(b for b in bits if b)
    entry = {k: v for k, v in {
        "band": "Dispute" if r["final_band"].startswith("Dispute") else r["final_band"],
        "fit_score": float(r["avg_points"]), "clay_tier": r["clay_tier"] or None, "team_geography": geo_txt or None,
        "brazilians_on_team": geo.get("brazil") if geo.get("people_count") else None,
        "hiring_signal": "; ".join(hiring) or None, "why_fit": why[:1000] or None,
        "primary_contact": f"{primary['name']} ({primary['title']})" if primary else None,
        "backup_contact": f"{backup['name']} ({backup['title']})" if backup else None,
        "engine_version": "rubric v2.2 · 2026-11-13",
    }.items() if v not in (None, "")}
    return company, entry


ISO2 = {
    "united states": "US", "usa": "US", "us": "US", "canada": "CA", "united kingdom": "GB", "uk": "GB", "gb": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "ireland": "IE", "germany": "DE", "deutschland": "DE",
    "netherlands": "NL", "the netherlands": "NL", "france": "FR", "spain": "ES", "portugal": "PT", "belgium": "BE",
    "switzerland": "CH", "sweden": "SE", "denmark": "DK", "norway": "NO", "finland": "FI", "poland": "PL",
    "italy": "IT", "austria": "AT", "hungary": "HU", "romania": "RO", "bulgaria": "BG", "latvia": "LV",
    "estonia": "EE", "lithuania": "LT", "luxembourg": "LU", "czech republic": "CZ", "czechia": "CZ", "greece": "GR",
    "croatia": "HR", "slovenia": "SI", "slovakia": "SK", "serbia": "RS", "ukraine": "UA", "macedonia": "MK",
    "north macedonia": "MK", "australia": "AU", "new zealand": "NZ", "israel": "IL", "brazil": "BR", "mexico": "MX",
    "united arab emirates": "AE", "uae": "AE", "puerto rico": "PR",
}


VALID_ISO2 = set(ISO2.values())


def iso2(country: str) -> str | None:
    """Country name or code -> ISO 3166 alpha-2. A 2-letter value counts only if it is a
    known country code ("NY" in "New York, NY" is a US state, not a country)."""
    c = (country or "").strip()
    if len(c) == 2 and c.isalpha():
        return c.upper() if c.upper() in VALID_ISO2 else None
    return ISO2.get(c.lower())


def location_for(domain: str, pack: dict, cc: dict, cand: dict) -> dict | None:
    """Best known HQ: Clay record (city + country), else Apollo ("City, State, Country"),
    else the directory listing (often country only). None when nothing is known."""
    city = region = country = None
    if cc.get("hq") and iso2(cc.get("country") or ""):
        city, country = cc["hq"].split(",")[0].strip(), iso2(cc["country"])
        parts = [p.strip() for p in cc["hq"].split(",")]
        region = parts[1] if len(parts) > 1 and not iso2(parts[1]) else None
    elif (pack.get("apollo") or {}).get("location"):
        parts = [p.strip() for p in pack["apollo"]["location"].split(",") if p.strip()]
        country = iso2(parts[-1]) if parts else None
        city = parts[0] if len(parts) >= 2 else None
        region = parts[1] if len(parts) >= 3 else None
    else:
        parts = [p.strip() for p in re.split(r"[,|]", cand.get("location") or "") if p.strip()]
        codes = [iso2(p) for p in parts if iso2(p)]
        # prefer the consolidator's country label: it already maps US states ("NY") to US and
        # reads "San Jose, CA" as California, not Canada
        country = iso2(cand.get("country") or "") or (codes[-1] if codes else None)
        city = parts[0] if len(parts) >= 2 and not iso2(parts[0]) else None
    if not country:
        return None
    return {"line_1": None, "line_2": None, "line_3": None, "line_4": None, "locality": city, "region": region,
            "postcode": None, "country_code": country, "latitude": None, "longitude": None}


def find_person(linkedin: str) -> str | None:
    """Attio stores LinkedIn URLs without the trailing slash Clay returns, so an exact match
    on the raw URL never hits (that created 31 duplicates on 2026-11-13). Match on the
    normalized URL and take the oldest record."""
    if not linkedin:
        return None
    url = linkedin.strip().rstrip("/").replace("http://", "https://")
    res = attio("POST", "objects/people/records/query", {"filter": {"linkedin": {"$eq": url}}, "limit": 10})
    rows = sorted(res.get("data", []), key=lambda p: p["created_at"])
    return rows[0]["id"]["record_id"] if rows else None


def main() -> None:
    bands = {"A": ("A",), "AB": ("A", "B"), "ABD": ("A", "B", "Dispute: Michel decides")}[
        next((a for a in sys.argv[1:] if not a.startswith("--")), "A")]
    ranked = [r for r in csv.DictReader((ROOT / "data" / "out" / "ranked.csv").open(encoding="utf-8-sig")) if r["final_band"] in bands]
    no_domain = [r["name"] for r in ranked if not r["domain"]]
    ranked = [r for r in ranked if r["domain"]]  # companies are matched by domain in Attio
    if no_domain:
        print(f"skipped (no domain to match in Attio): {no_domain}")
    contacts = list(csv.DictReader((ROOT / "data" / "private" / "decision_makers.csv").open(encoding="utf-8-sig")))
    cc_all = load_json(ROOT / "data" / "raw" / "clay_company.json")
    geo_all = load_json(ROOT / "data" / "raw" / "clay_geography.json")
    ats_all = load_json(ROOT / "data" / "raw" / "ats_jobs.json")
    sys.path.insert(0, str(ROOT / "engine"))
    from research import key_of
    cands = {c["name"]: c for c in json.loads((ROOT / "data" / "out" / "candidates.json").read_text(encoding="utf-8"))}

    if not RECORDS_ONLY:
        ensure_schema()
    in_list = {} if (DRY or RECORDS_ONLY) else {e["parent_record_id"]: e for e in
                              attio("POST", f"lists/{LIST['api_slug']}/entries/query", {"limit": 500}).get("data", [])}
    made = {"companies": 0, "people_new": 0, "people_updated": 0, "entries_new": 0, "entries_updated": 0}
    for r in ranked:
        pack = load_json(ROOT / "data" / "research" / f"{key_of(cands[r['name']])}.json")
        mine = [c for c in contacts if c["company"] == r["name"] and c["contact"] in ("primary", "backup") and c["name"]]
        company, entry = company_payload(r, cc_all.get(r["domain"], {}), geo_all.get(r["domain"], {}),
                                         pack.get("apollo") or {}, ats_all.get(r["domain"], {}), mine)
        rec = attio("PUT", "objects/companies/records?matching_attribute=domains", {"data": {"values": company}})
        company_id = rec["data"]["id"]["record_id"]
        # Location only when Attio has none: never overwrite what Attio's own enrichment filled
        has_loc = bool(((rec.get("data") or {}).get("values") or {}).get("primary_location"))
        loc = location_for(r["domain"], pack, cc_all.get(r["domain"], {}), cands.get(r["name"], {}))
        if loc and not has_loc:
            attio("PATCH", f"objects/companies/records/{company_id}", {"data": {"values": {"primary_location": [loc]}}})
            made["locations"] = made.get("locations", 0) + 1
        made["companies"] += 1
        for c in mine:
            first, _, last = c["name"].partition(" ")
            values = {"name": [{"first_name": first, "last_name": last, "full_name": c["name"]}], "job_title": c["title"],
                      "company": [{"target_object": "companies", "target_record_id": company_id}],
                      "description": f"GTM Talent Engine: {c['contact']} contact at {company['name']} ({c['source']})."}
            if c["linkedin"]:
                values["linkedin"] = c["linkedin"]
            pid = None if DRY else find_person(c["linkedin"])
            if pid:
                attio("PATCH", f"objects/people/records/{pid}", {"data": {"values": values}})
                made["people_updated"] += 1
            else:
                attio("POST", "objects/people/records", {"data": {"values": values}})
                made["people_new"] += 1
        existing = in_list.get(company_id)
        if RECORDS_ONLY:
            continue
        if existing:  # keep the stage Michel may have moved; refresh the engine fields
            attio("PATCH", f"lists/{LIST['api_slug']}/entries/{existing['id']['entry_id']}", {"data": {"entry_values": entry}})
            made["entries_updated"] += 1
        else:
            attio("POST", f"lists/{LIST['api_slug']}/entries", {"data": {
                "parent_record_id": company_id, "parent_object": "companies",
                "entry_values": {**entry, "stage": "Contact found" if mine else "Qualified"}}})
            made["entries_new"] += 1
    print(json.dumps(made))
    if DRY:
        print(f"{len(LOG)} write calls planned; first ones:")
        for line in LOG[:14]:
            print(" ", line)


if __name__ == "__main__":
    main()
