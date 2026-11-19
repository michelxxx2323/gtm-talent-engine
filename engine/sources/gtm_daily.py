"""Source 2 and 3: GTM Daily (gtmdaily.com), a curated GTM-engineering site.

- /agencies/<slug>: ~90 GTM agencies with "Based in" and services.
- /jobs/<slug>: ~250 GTM engineering / RevOps / outbound jobs with tools
  (Clay, n8n...). A company hiring for these roles is a hiring signal; if it
  is an agency, it is also a candidate.

robots.txt allows these pages but forbids /go, /tools/go and /jobs/go (the
outbound "Visit website" and "Apply" links), so websites are NOT taken from
here: consolidate.py resolves domains later. Job pages already cached by
job-fit-screener are reused so we do not download them twice.

Output: data/raw/gtm_daily_agencies.json and data/raw/gtm_daily_jobs.json.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://gtmdaily.com"
UA = {"User-Agent": "Mozilla/5.0 (gtm-talent-engine research script)"}
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
JFS_CACHE = ROOT.parent / "job-fit-screener" / "output" / "descricoes.json"
PAUSE = 1.0


def get(url: str) -> str:
    for attempt in range(3):
        resp = requests.get(url, headers=UA, timeout=30)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 404:
            return ""
        time.sleep(3 * (attempt + 1))
    resp.raise_for_status()
    return ""


def sitemap(section: str) -> list[str]:
    xml = get(BASE + "/sitemap.xml")
    return sorted(set(re.findall(rf"<loc>({re.escape(BASE)}/{section}/[^<?]+)</loc>", xml)))


def side_fields(soup: BeautifulSoup) -> dict[str, str]:
    fields = {}
    for dt_ in soup.select("dl dt"):
        dd = dt_.find_next_sibling("dd")
        if dd:
            fields[dt_.get_text(" ", strip=True).lower()] = dd.get_text(", ", strip=True)
    return fields


def parse_agency(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    name = title.split(",")[0].split("|")[0].strip()
    text = soup.find("main").get_text(" ", strip=True) if soup.find("main") else ""
    quote = re.search(r'describes it as follows: "(.+?)"', text)
    services = re.search(r"Services (.+?) Reviews", text)
    fields = side_fields(soup)
    return {
        "source": "gtm_daily_agencies",
        "name": name,
        "gtm_daily_profile": url,
        "location": fields.get("based in", ""),
        "description": quote.group(1) if quote else "",
        # when a listing has no "Services" block the regex can swallow page chrome
        "services": services.group(1) if services and "Visit website" not in services.group(1) else "",
    }


def parse_job(url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    fields = side_fields(soup)
    h1 = soup.find("h1")
    company = h1.find_previous_sibling() if h1 else None
    return {
        "source": "gtm_daily_jobs",
        "title": h1.get_text(" ", strip=True) if h1 else "",
        "company": company.get_text(" ", strip=True) if company else "",
        "location": fields.get("location", ""),
        "pay": fields.get("pay", ""),
        "tools": fields.get("tools", ""),
        "posted": fields.get("originally posted", ""),
        "link": url,
    }


def load_jfs_cache() -> dict:
    """job-fit-screener stores parsed job pages under 'gtmdaily-pagina:<url>'."""
    if not JFS_CACHE.exists():
        return {}
    data = json.loads(JFS_CACHE.read_text(encoding="utf-8"))
    out = {}
    for key, val in data.items():
        if key.startswith("gtmdaily-pagina:"):
            v = val.get("v", val) if isinstance(val, dict) else {}
            out[key.split(":", 1)[1]] = v
    return out


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)

    agencies = []
    for url in sitemap("agencies"):
        html = get(url)
        if html:
            agencies.append(parse_agency(url, html))
        time.sleep(PAUSE)
    (RAW / "gtm_daily_agencies.json").write_text(json.dumps(agencies, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"agencies: {len(agencies)}")

    cache = load_jfs_cache()
    jobs, downloaded = [], 0
    for url in sitemap("jobs"):
        hit = cache.get(url)
        if hit and hit.get("empresa"):
            jobs.append({
                "source": "gtm_daily_jobs", "title": hit.get("titulo", ""), "company": hit.get("empresa", ""),
                "location": hit.get("local", ""), "pay": hit.get("pay", ""), "tools": hit.get("ferramentas", ""),
                "posted": hit.get("publicado", ""), "link": url,
            })
            continue
        html = get(url)
        downloaded += 1
        if html:
            jobs.append(parse_job(url, html))
        time.sleep(PAUSE)
    (RAW / "gtm_daily_jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"jobs: {len(jobs)} ({downloaded} downloaded, rest from job-fit-screener cache)")


if __name__ == "__main__":
    main()
