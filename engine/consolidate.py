"""Merge all sources into one candidate list and apply the cheap filters
from config/rubric.md (no AI, no credits).

Inputs : data/raw/*.json written by engine/sources/*
Outputs: data/out/candidates.csv   (pass, ready for phase 2 research)
         data/out/rejected.csv     (fail, with the reason)
         data/out/inhouse_hiring.csv (non-agency companies hiring GTM roles:
                                      not targets for the 100, kept as a lead list)
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "out"
DOMAIN_CACHE = ROOT / "data" / "raw" / "domain_guesses.json"
OVERRIDES = {k: v for k, v in json.loads((ROOT / "config" / "domain_overrides.json").read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
UA = {"User-Agent": "Mozilla/5.0 (gtm-talent-engine research script)"}

PRIMARY = {
    "US", "USA", "UNITED STATES", "CA", "CANADA", "GB", "UK", "UNITED KINGDOM", "ENGLAND", "SCOTLAND", "WALES",
    "IE", "IRELAND", "FR", "FRANCE", "DE", "GERMANY", "NL", "NETHERLANDS", "BE", "BELGIUM", "ES", "SPAIN",
    "PT", "PORTUGAL", "IT", "ITALY", "CH", "SWITZERLAND", "AT", "AUSTRIA", "SE", "SWEDEN", "NO", "NORWAY",
    "DK", "DENMARK", "FI", "FINLAND", "PL", "POLAND", "CZ", "CZECHIA", "CZECH REPUBLIC", "EE", "ESTONIA",
    "LT", "LITHUANIA", "LV", "LATVIA", "GR", "GREECE", "RO", "ROMANIA", "HU", "HUNGARY", "LU", "LUXEMBOURG",
    "BG", "BULGARIA", "HR", "CROATIA", "SI", "SLOVENIA", "SK", "SLOVAKIA", "CY", "CYPRUS", "MT", "MALTA",
    "UA", "UKRAINE", "RS", "SERBIA",
}
SECONDARY = {
    "AU", "AUSTRALIA", "NZ", "NEW ZEALAND", "IL", "ISRAEL", "BR", "BRAZIL", "AR", "ARGENTINA", "MX", "MEXICO",
    "CO", "COLOMBIA", "CL", "CHILE", "UY", "URUGUAY", "PE", "PERU", "CR", "COSTA RICA", "AE", "UNITED ARAB EMIRATES",
}
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
US_STATE_NAMES = {
    "ALABAMA", "ALASKA", "ARIZONA", "ARKANSAS", "CALIFORNIA", "COLORADO", "CONNECTICUT", "DELAWARE", "FLORIDA",
    "GEORGIA", "HAWAII", "IDAHO", "ILLINOIS", "INDIANA", "IOWA", "KANSAS", "KENTUCKY", "LOUISIANA", "MAINE",
    "MARYLAND", "MASSACHUSETTS", "MICHIGAN", "MINNESOTA", "MISSISSIPPI", "MISSOURI", "MONTANA", "NEBRASKA",
    "NEVADA", "NEW HAMPSHIRE", "NEW JERSEY", "NEW MEXICO", "NEW YORK", "NORTH CAROLINA", "NORTH DAKOTA", "OHIO",
    "OKLAHOMA", "OREGON", "PENNSYLVANIA", "RHODE ISLAND", "SOUTH CAROLINA", "SOUTH DAKOTA", "TENNESSEE", "TEXAS",
    "UTAH", "VERMONT", "VIRGINIA", "WASHINGTON", "WEST VIRGINIA", "WISCONSIN", "WYOMING",
}
PRIMARY |= US_STATE_NAMES | {"EUROPE", "EU", "THE NETHERLANDS", "NORTH AMERICA", "DEUTSCHLAND", "MACEDONIA", "NORTH MACEDONIA"}
SECONDARY |= {"UAE"}
CITY_HINTS = {
    "london": "UK", "new york": "US", "san francisco": "US", "nyc": "US", "austin": "US", "toronto": "CANADA",
    "vancouver": "CANADA", "montreal": "CANADA", "berlin": "GERMANY", "amsterdam": "NETHERLANDS", "paris": "FRANCE",
    "dublin": "IRELAND", "lisbon": "PORTUGAL", "barcelona": "SPAIN", "madrid": "SPAIN", "stockholm": "SWEDEN",
    "copenhagen": "DENMARK", "sydney": "AUSTRALIA", "melbourne": "AUSTRALIA", "tel aviv": "ISRAEL",
}

# Clear non-employers for this purpose. Conservative: anything ambiguous is
# only flagged and left for the phase 2 gates.
NON_EMPLOYER = re.compile(
    r"\b(our (software|platform|app|saas)|chrome extension|job board|data provider|bootcamp|online course|"
    r"cohort-based course|course on|coaching program|money-back guarantee|learn clay in)\b",
    re.I,
)
AGENCY_WORDS = re.compile(
    r"\b(agency|studio|consultan\w*|done[- ]for[- ]you|we (build|help|run|design|implement)|fractional|partners?|clients?|lead gen\w*|outbound|services?)\b",
    re.I,
)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def name_key(name: str) -> str:
    """'Acme Growth 🎯' and 'Acme Growth, Inc.' -> 'acmegrowth'."""
    n = fold(name)
    n = re.sub(r"\b(inc|llc|ltd|limited|gmbh|bv|co|corp|the|agency|studio|hq|io|ai)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


NOT_A_DOMAIN = {"linkedin.com", "calendly.com", "linktr.ee", "notion.site", "carrd.co", "substack.com",
                "medium.com", "twitter.com", "x.com", "youtube.com", "google.com", "upwork.com", "contra.com"}


def root_domain(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower().split(":")[0]
    host = host.removeprefix("www.")
    parts = host.split(".")
    if len(parts) > 2 and parts[-2] in {"co", "com", "org", "net"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])  # foo.co.uk
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def company_domain(url: str) -> str:
    """root_domain, but '' for shared hosts (a LinkedIn profile is not a company site)."""
    dom = root_domain(url)
    return "" if dom in NOT_A_DOMAIN else dom


CANONICAL = {"USA": "US", "UNITED STATES": "US", "NORTH AMERICA": "US", "GB": "UK", "UNITED KINGDOM": "UK",
             "ENGLAND": "UK", "SCOTLAND": "UK", "WALES": "UK", "THE NETHERLANDS": "NETHERLANDS", "DEUTSCHLAND": "GERMANY",
             "CA": "CANADA", "UAE": "UNITED ARAB EMIRATES"}


def region(location: str) -> tuple[str, str]:
    """(canonical country, primary|secondary|other|unknown)."""
    country, reg = _region(location)
    if country in US_STATE_NAMES or country in US_STATES - {"CA"}:
        country = "US"
    if country == "CA" and re.search(r"\w,\s*CA\b", location or ""):  # "San Jose, CA" is California
        country = "US"
    return CANONICAL.get(country, country), reg


def _region(location: str) -> tuple[str, str]:
    loc = (location or "").strip()
    if not loc:
        return "", "unknown"
    up = re.sub(r"\(.*?\)", " ", loc.upper()).replace(".", "")
    tokens = [t.strip() for t in re.split(r"[,/;|·-]", up) if t.strip()]
    # "Brussels, Belgium London, UK" (sentence-joined) -> also try each word pair
    tokens = [re.sub(r"\s+REMOTE$", "", t) for t in tokens]
    for tok in reversed(tokens):
        if tok in PRIMARY:
            return tok, "primary"
        if tok in SECONDARY:
            return tok, "secondary"
        if tok in US_STATES and len(tokens) > 1:
            return "US", "primary"
    low = loc.lower()
    for city, country in CITY_HINTS.items():
        if city in low:
            return country, "primary" if country in PRIMARY else "secondary"
    if re.search(r"\b(remote|global|worldwide|anywhere)\b", low):
        return "", "unknown"
    return tokens[-1] if tokens else "", "other"


def load(name: str) -> list[dict]:
    path = RAW / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def guess_domain(name: str, cache: dict) -> str:
    """Try name.com/.io/.ai/.co and accept only when the page mentions the
    name. Marked domain_source=guessed so a human (or phase 2) can confirm."""
    key = name_key(name)
    if key in cache:
        return cache[key]
    base = re.sub(r"[^a-z0-9]", "", fold(name))
    found = ""
    for cand in [f"{base}.com", f"{base}.io", f"{base}.ai", f"{base}.co", f"get{base}.com", f"{base}hq.com"]:
        try:
            resp = requests.get("https://" + cand, headers=UA, timeout=8, allow_redirects=True)
        except requests.RequestException:
            continue
        body = fold(resp.text[:200_000])
        if resp.status_code == 200 and (fold(name) in body or base in body.replace(" ", "")):
            found = root_domain(resp.url) or cand
            break
        time.sleep(0.2)
    cache[key] = found
    return found


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clay = load("clay_directory.json")
    gd_agencies = load("gtm_daily_agencies.json")
    jobs = load("gtm_daily_jobs.json")
    cache = json.loads(DOMAIN_CACHE.read_text(encoding="utf-8")) if DOMAIN_CACHE.exists() else {}

    companies: dict[str, dict] = {}  # key -> merged record
    by_name: dict[str, str] = {}

    def upsert(key: str, name: str, rec: dict) -> dict:
        cur = companies.get(key)
        if not cur:
            cur = companies[key] = {
                "name": name, "domain": "", "domain_source": "", "sources": [], "clay_tier": "",
                "clay_profile": "", "gtm_daily_profile": "", "location": "", "description": "",
                "services": "", "icps": "", "languages": "", "min_engagement": "", "gtm_jobs": [],
                "aliases": [], "linkedin": "",
            }
        by_name.setdefault(name_key(name), key)
        if name != cur["name"] and name not in cur["aliases"]:
            cur["aliases"].append(name)  # often the founder listed as a separate Clay partner
        for field, val in rec.items():
            if field == "sources":
                cur["sources"] = sorted(set(cur["sources"]) | set(val))
            elif val and not cur.get(field):
                cur[field] = val
        return cur

    for r in clay:
        dom = company_domain(r["website"])
        key = dom or "name:" + name_key(r["name"])
        upsert(key, r["name"], {
            "linkedin": r["website"] if "linkedin.com" in r["website"] else "",
            "domain": dom, "domain_source": "clay_directory" if dom else "", "sources": ["clay_directory"],
            "clay_tier": r["clay_tier"], "clay_profile": r["clay_profile"], "location": r["location"],
            "description": r["headline"] + ("\n\n" + r["description"] if r["description"] else ""),
            "icps": "; ".join(r["icps"] + r["industries"]), "languages": "; ".join(r["languages"]),
            "min_engagement": "; ".join(r["min_engagement"]),
        })

    for r in gd_agencies:
        key = by_name.get(name_key(r["name"]))
        override = OVERRIDES.get(r["name"], {}).get("domain")
        if override:  # a wrong guess fixed by hand (config/domain_overrides.json)
            key = override if override in companies else key or override
            r = {**r, "domain": override, "domain_source": "override"}
        elif not key:
            dom = guess_domain(r["name"], cache)
            key = dom if dom else "name:" + name_key(r["name"])
            if dom and dom in companies:
                by_name[name_key(r["name"])] = dom
            r = {**r, "domain": dom, "domain_source": "guessed" if dom else ""}
        upsert(key, r["name"], {
            "domain": r.get("domain", ""), "domain_source": r.get("domain_source", ""),
            "sources": ["gtm_daily_agencies"], "gtm_daily_profile": r["gtm_daily_profile"],
            "location": r["location"], "description": r["description"], "services": r["services"],
        })
    DOMAIN_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    inhouse: dict[str, dict] = {}
    for j in jobs:
        if not j.get("company"):
            continue
        brief = {k: j[k] for k in ("title", "location", "tools", "posted", "link")}
        key = by_name.get(name_key(j["company"]))
        if key:
            companies[key]["gtm_jobs"].append(brief)
            companies[key]["sources"] = sorted(set(companies[key]["sources"]) | {"gtm_daily_jobs"})
        else:
            inhouse.setdefault(j["company"], {"company": j["company"], "jobs": []})["jobs"].append(brief)

    passed, rejected = [], []
    for c in companies.values():
        country, reg = region(c["location"])
        c["country"], c["region"] = country, reg
        text = f"{c['description']} {c['services']}"
        flags = []
        if not AGENCY_WORDS.search(text):
            flags.append("no agency wording")
        if not c["domain"]:
            flags.append("domain missing")
        if c["domain_source"] == "guessed":
            flags.append("domain guessed")
        c["flags"] = "; ".join(flags)
        reason = ""
        if reg == "other":
            reason = f"region outside target ({c['location']})"
        elif c["languages"] and "english" not in c["languages"].lower():
            reason = f"no English listed ({c['languages']})"
        elif NON_EMPLOYER.search(text) and not AGENCY_WORDS.search(text):
            reason = "looks like a product/course, not a service business"
        (rejected if reason else passed).append({**c, "reject_reason": reason})

    def tier_rank(c: dict) -> int:
        return {"Elite Studio": 0, "Studio": 1, "Advanced Artisan": 2, "Artisan": 3}.get(c["clay_tier"], 4)

    passed.sort(key=lambda c: ({"primary": 0, "unknown": 1, "secondary": 2}[c["region"]], tier_rank(c), -len(c["gtm_jobs"]), c["name"].lower()))
    cols = ["name", "aliases", "domain", "linkedin", "domain_source", "country", "region", "location", "clay_tier", "sources", "gtm_jobs_count",
            "gtm_jobs", "icps", "languages", "min_engagement", "flags", "clay_profile", "gtm_daily_profile", "description",
            "services", "reject_reason"]

    def write(path: Path, rows: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({**r, "sources": "; ".join(r["sources"]), "aliases": "; ".join(r["aliases"]), "gtm_jobs_count": len(r["gtm_jobs"]),
                            "gtm_jobs": " | ".join(f"{j['title']} ({j['location']})" for j in r["gtm_jobs"])})

    write(OUT / "candidates.csv", passed)
    write(OUT / "rejected.csv", rejected)
    with (OUT / "inhouse_hiring.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["company", "jobs_count", "jobs", "tools"])
        for c in sorted(inhouse.values(), key=lambda x: -len(x["jobs"])):
            w.writerow([c["company"], len(c["jobs"]), " | ".join(f"{j['title']} ({j['location']})" for j in c["jobs"]),
                        "; ".join(sorted({t.strip() for j in c["jobs"] for t in j["tools"].split(",") if t.strip()}))])
    (OUT / "candidates.json").write_text(json.dumps(passed, ensure_ascii=False, indent=1), encoding="utf-8")

    regions = {}
    for c in passed:
        regions[c["region"]] = regions.get(c["region"], 0) + 1
    print(f"companies merged: {len(companies)} | pass: {len(passed)} {regions} | rejected: {len(rejected)} | in-house hiring: {len(inhouse)}")


if __name__ == "__main__":
    main()
