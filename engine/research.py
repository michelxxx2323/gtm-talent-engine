"""Phase 2, step 1: build an evidence pack per company (no AI).

For each company: the homepage plus up to 6 internal pages that matter for
the rubric (about/team, careers/jobs, services, case studies, blog), links
to job boards/ATS, and Apollo's organization record (headcount, growth,
location, technologies). Every snippet keeps its URL so the evaluators can
cite evidence.

Usage: python engine/research.py [pilot|candidates] [--limit N]
Output: data/research/<key>.json  (one pack per company; cached, re-run skips)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "research"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
PAGE_CHARS = 2500
PAGE_KINDS = [  # (kind, url/anchor pattern) in priority order; one page per kind
    ("team", r"\b(about|team|company|who-we-are|our-story|people)\b"),
    ("careers", r"\b(careers?|jobs|join|hiring|work-with-us|open-roles|positions)\b"),
    ("services", r"\b(services?|what-we-do|solutions|offer|how-we-work)\b"),
    ("cases", r"\b(case-stud(y|ies)|clients|customers|results|work|portfolio)\b"),
    ("blog", r"\b(blog|insights|resources|articles|newsletter)\b"),
    ("pricing", r"\b(pricing|packages|plans)\b"),
]
ATS = re.compile(r"(ashbyhq\.com|greenhouse\.io|lever\.co|workable\.com|wellfound\.com|breezy\.hr|bamboohr\.com|"
                 r"teamtailor\.com|recruitee\.com|notion\.site/[^\"']*(career|job)|jobs\.gem\.com|rippling\.com/[^\"']*job)", re.I)


def env(name: str) -> str:
    """A setting from .env (see .env.example), else from the environment."""
    path = ROOT / ".env"
    for line in (path.read_text(encoding="utf-8").splitlines() if path.exists() else []):
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    return os.environ.get(name, "")


def key_of(c: dict) -> str:
    return re.sub(r"[^a-z0-9.-]", "-", (c["domain"] or c["name"]).lower())


PARKED = re.compile(r"(atom\.com/name|sedo\.com|dan\.com|afternic|hugedomains|godaddy\.com/domainsearch|"
                    r"domain (is )?for sale|buy this domain|parked free)", re.I)
LAST_STATUS: dict[str, str] = {}


def fetch(url: str) -> tuple[str, str]:
    """(final url, html) or ('', ''). Sites that refuse automated access are
    NOT worked around (no proxies, no headless readers): the status is kept
    as evidence and the evaluators fall back to directory + Apollo data."""
    try:
        resp = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
    except requests.RequestException as exc:
        LAST_STATUS[url] = f"no response ({type(exc).__name__})"
        return "", ""
    if PARKED.search(resp.url) or PARKED.search(resp.text[:20000]):
        LAST_STATUS[url] = f"domain parked or for sale ({resp.url})"
        return "", ""
    if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
        LAST_STATUS[url] = f"HTTP {resp.status_code}" + (" (blocks automated access)" if resp.status_code in (401, 403, 429) else "")
        return "", ""
    return resp.url, resp.text


def page_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "header"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    return title, text


MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
DATE_RE = re.compile(rf"\b(?:(?:{MONTHS})[a-z]*\.? \d{{1,2}},? (20\d\d)|\d{{1,2}} (?:{MONTHS})[a-z]* (20\d\d)|(20\d\d)-\d\d-\d\d)\b", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:20\d\d\s*[-–]\s*)?(20\d\d)", re.I)


def dates_in(html: str, text: str) -> dict:
    """Dated evidence for the 'recent activity' cap: the latest full date and
    the copyright year. Read from the full page, before text is truncated."""
    found = [(int(next(g for g in m.groups() if g)), m.group(0)) for m in DATE_RE.finditer(text)]
    found = [f for f in found if f[0] <= 2026]
    cy = [int(y) for y in COPYRIGHT_RE.findall(html) if int(y) <= 2026]
    latest = max(found) if found else None
    return {"latest_date": latest[1] if latest else "", "latest_year": latest[0] if latest else None,
            "copyright_year": max(cy) if cy else None}


def internal_links(base_url: str, html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base_url).netloc.removeprefix("www.")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].split("#")[0])
        p = urlparse(href)
        if p.scheme not in ("http", "https") or p.netloc.removeprefix("www.") != host:
            continue
        if href.rstrip("/") in seen or href.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(href.rstrip("/"))
        out.append((href, a.get_text(" ", strip=True).lower()))
    return out


def apollo(domain: str) -> dict:
    key = env("APOLLO_API_KEY")
    if not key or not domain:
        return {}
    try:
        resp = requests.get("https://api.apollo.io/api/v1/organizations/enrich", params={"domain": domain},
                            headers={"X-Api-Key": key, "Cache-Control": "no-cache"}, timeout=30)
    except requests.RequestException as exc:
        return {"error": str(exc)}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}
    o = resp.json().get("organization") or {}
    if not o:
        return {"error": "not found"}
    return {
        "name": o.get("name"), "employees": o.get("estimated_num_employees"), "founded": o.get("founded_year"),
        "location": ", ".join(x for x in (o.get("city"), o.get("state"), o.get("country")) if x),
        "linkedin": o.get("linkedin_url"), "description": (o.get("short_description") or "")[:1200],
        "growth_6m": o.get("organization_headcount_six_month_growth"),
        "growth_12m": o.get("organization_headcount_twelve_month_growth"),
        "departments": {k: v for k, v in (o.get("departmental_head_count") or {}).items() if v},
        "technologies": (o.get("technology_names") or [])[:40],
        "keywords": (o.get("keywords") or [])[:25],
    }


def research(c: dict, cached_apollo: dict | None = None) -> dict:
    pack = {
        "name": c["name"], "domain": c["domain"], "aliases": c.get("aliases", []), "country": c["country"],
        "region": c["region"], "directory": {
            "clay_tier": c["clay_tier"], "clay_profile": c["clay_profile"], "gtm_daily_profile": c["gtm_daily_profile"],
            "location": c["location"], "description": c["description"][:1500], "services": c["services"],
            "icps": c["icps"], "languages": c["languages"], "min_engagement": c["min_engagement"],
            "linkedin": c.get("linkedin", ""),
        },
        "gtm_jobs": c["gtm_jobs"], "pages": [], "ats_links": [], "errors": [], "dates": [],
    }
    if not c["domain"]:
        pack["errors"].append("no domain: website not researched")
        return pack
    home_url, home = fetch(f"https://{c['domain']}")
    if not home:
        home_url, home = fetch(f"https://www.{c['domain']}")
    if not home:
        pack["errors"].append("homepage did not load: " + LAST_STATUS.get(f"https://www.{c['domain']}", LAST_STATUS.get(f"https://{c['domain']}", "")))
    else:
        title, text = page_text(home)
        pack["dates"] = [{"url": home_url, **dates_in(home, text)}]
        if len(text) < 400:
            pack["errors"].append("thin page: site renders with JavaScript, little readable text")
        pack["pages"].append({"kind": "home", "url": home_url, "title": title, "text": text[:PAGE_CHARS]})
        pack["ats_links"] = sorted(set(m.group(0) for m in ATS.finditer(home)))
        links = internal_links(home_url, home)
        for kind, pattern in PAGE_KINDS:
            match = next((u for u, label in links if re.search(pattern, urlparse(u).path.lower()) or re.search(pattern, label)), None)
            if not match or any(p["url"] == match for p in pack["pages"]):
                continue
            url, html = fetch(match)
            time.sleep(0.5)
            if not html:
                continue
            title, text = page_text(html)
            pack["dates"].append({"url": url, **dates_in(html, text)})
            pack["pages"].append({"kind": kind, "url": url, "title": title, "text": text[:PAGE_CHARS]})
            pack["ats_links"] = sorted(set(pack["ats_links"]) | set(m.group(0) for m in ATS.finditer(html)))
    pack["apollo"] = cached_apollo or apollo(c["domain"])
    return pack


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["pilot", "candidates"], default="pilot", nargs="?")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true", help="re-read websites; Apollo records are reused")
    args = ap.parse_args()
    cands = json.loads((ROOT / "data" / "out" / f"{args.which}.json").read_text(encoding="utf-8"))
    if args.limit:
        cands = cands[: args.limit]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(cands, 1):
        path = OUT_DIR / f"{key_of(c)}.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if old and not args.refresh:
            continue
        # --refresh re-reads the website but reuses Apollo (free-plan credits)
        keep = (old or {}).get("apollo") if (old and (old.get("apollo") or {}).get("name")) else None
        pack = research(c, cached_apollo=keep)
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
        ap_ = pack.get("apollo") or {}
        print(f"{i:>3}/{len(cands)} {c['name'][:35]:<35} pages={len(pack['pages'])} ats={len(pack['ats_links'])} "
              f"apollo={'ok' if ap_.get('name') else ap_.get('error', '-')} {'; '.join(pack['errors'])}", flush=True)


if __name__ == "__main__":
    main()
