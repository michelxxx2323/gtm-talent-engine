"""Free hiring signal: open jobs from public ATS job-board APIs.

Clay's free plan cannot filter companies by open jobs (cross-entity filters
need a paid plan), so this probes the public, key-less job-board APIs that
agencies commonly use, with slugs derived from each candidate's domain and
name (same idea as job-fit-screener/descobrir_ats.py):

  Ashby       https://api.ashbyhq.com/posting-api/job-board/<slug>
  Greenhouse  https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
  Lever       https://api.lever.co/v0/postings/<slug>?mode=json
  Workable    https://apply.workable.com/api/v1/widget/accounts/<slug>

A board with the same slug can belong to another company (an "acme" board
is not necessarily Acme Outbound). A hit is kept with a confidence:
  high   slug == the domain's first label AND the board name (when the API
         gives one) matches the company, or the site links to that board
  medium slug == the domain's first label, board name unknown
  low    slug only matches the company name -> listed, not used for scoring

Usage: python engine/sources/ats_jobs.py [candidates|pilot]
Output: data/raw/ats_jobs.json  {domain: {"ats", "slug", "confidence", "board_name", "jobs": [...]}}
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
from consolidate import fold, name_key  # noqa: E402
from research import key_of  # noqa: E402

OUT = ROOT / "data" / "raw" / "ats_jobs.json"
UA = {"User-Agent": "Mozilla/5.0 (gtm-talent-engine research script)", "Accept": "application/json"}
GTM_ROLE = re.compile(
    r"\b(gtm|go[- ]to[- ]market|rev ?ops|revenue operations|sales operations|marketing operations|campaign|"
    r"growth (engineer|ops|operations)|automation|clay|outbound|lead gen|data enrichment|enrichment|"
    r"deliverability|crm|hubspot|salesforce admin|solutions (engineer|architect)|implementation|"
    r"ai (engineer|automation|ops)|workflow)\b", re.I)


def get_json(url: str):
    for attempt in range(2):
        try:
            r = requests.get(url, headers=UA, timeout=15)
        except requests.RequestException:
            time.sleep(1)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
        if r.status_code in (404, 410, 400, 401, 403):
            return None
        time.sleep(1.5 * (attempt + 1))
    return None


def ashby(slug: str):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not d or "jobs" not in d:
        return None
    return None, [{"title": j.get("title", ""), "location": j.get("location", ""), "remote": j.get("isRemote"),
                   "url": j.get("jobUrl", ""), "posted": (j.get("publishedAt") or "")[:10]} for j in d["jobs"]]


def greenhouse(slug: str):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    if not d or "jobs" not in d:
        return None
    meta = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}") or {}
    return meta.get("name"), [{"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                               "remote": None, "url": j.get("absolute_url", ""), "posted": (j.get("updated_at") or "")[:10]}
                              for j in d["jobs"]]


def lever(slug: str):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return None
    return None, [{"title": j.get("text", ""), "location": (j.get("categories") or {}).get("location", ""),
                   "remote": j.get("workplaceType") == "remote", "url": j.get("hostedUrl", ""),
                   "posted": time.strftime("%Y-%m-%d", time.gmtime((j.get("createdAt") or 0) / 1000)) if j.get("createdAt") else ""}
                  for j in d]


def workable(slug: str):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if not d or "jobs" not in d:
        return None
    return d.get("name"), [{"title": j.get("title", ""),
                            "location": ", ".join(x for x in (j.get("city"), j.get("country")) if x),
                            "remote": j.get("telecommuting"), "url": j.get("url", ""), "posted": (j.get("published_on") or "")[:10]}
                           for j in d["jobs"]]


ATS = {"ashby": ashby, "greenhouse": greenhouse, "lever": lever, "workable": workable}
LINK_SLUG = {  # slug as it appears in links found on the company's own site
    "ashby": re.compile(r"(?:jobs\.)?ashbyhq\.com/([A-Za-z0-9._-]+)"),
    "greenhouse": re.compile(r"greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    "lever": re.compile(r"jobs\.lever\.co/([A-Za-z0-9_-]+)"),
    "workable": re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
}


def site_links(c: dict) -> dict[str, str]:
    """ATS slugs linked from the company's own pages (strongest evidence)."""
    path = ROOT / "data" / "research" / f"{key_of(c)}.json"
    if not path.exists():
        return {}
    links = json.loads(path.read_text(encoding="utf-8")).get("ats_links", [])
    out = {}
    for ats, pat in LINK_SLUG.items():
        for link in links:
            m = pat.search(link)
            if m:
                out[ats] = m.group(1).lower()
    return out


def slugs(c: dict) -> list[tuple[str, str]]:
    """(slug, kind) candidates; kind 'domain' is stronger than 'name'."""
    first = c["domain"].split(".")[0].lower()
    out = [(first, "domain")]
    n = fold(c["name"])
    n = re.sub(r"[^\x00-\x7f]", "", n).strip()
    for s in {name_key(c["name"]), re.sub(r"[^a-z0-9]+", "-", n).strip("-")}:
        if s and s != first and len(s) >= 4:
            out.append((s, "name"))
    return out


def names_match(board: str | None, c: dict) -> bool | None:
    if not board:
        return None
    b = name_key(board)
    return bool(b) and (b in name_key(c["name"]) or name_key(c["name"]) in b or b in c["domain"].replace(".", ""))


def probe(c: dict) -> dict | None:
    linked = site_links(c)
    for ats, slug in linked.items():
        res = ATS[ats](slug)
        if res is not None:
            board, jobs = res
            return {"ats": ats, "slug": slug, "confidence": "high", "board_name": board, "source": "linked from site", "jobs": jobs}
    best = None
    for slug, kind in slugs(c):
        for ats, fn in ATS.items():
            res = fn(slug)
            if res is None:
                continue
            board, jobs = res
            match = names_match(board, c)
            if match is False:
                continue  # a board of another company with the same slug
            conf = "high" if (kind == "domain" and match) else "medium" if kind == "domain" else "low"
            hit = {"ats": ats, "slug": slug, "confidence": conf, "board_name": board, "source": f"slug from {kind}", "jobs": jobs}
            rank = {"high": 0, "medium": 1, "low": 2}[conf]
            if best is None or rank < {"high": 0, "medium": 1, "low": 2}[best["confidence"]]:
                best = hit
    return best


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "candidates"
    cands = [c for c in json.loads((ROOT / "data" / "out" / f"{which}.json").read_text(encoding="utf-8")) if c["domain"]]
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [c for c in cands if c["domain"] not in out]
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for c, hit in zip(todo, pool.map(probe, todo)):
            out[c["domain"]] = hit or {}
            if hit:
                for j in hit["jobs"]:
                    j["gtm_role"] = bool(GTM_ROLE.search(j["title"]))
                g = sum(j["gtm_role"] for j in hit["jobs"])
                print(f"{c['name'][:34]:<34} {hit['ats']:<10} {hit['slug']:<22} {hit['confidence']:<6} "
                      f"jobs={len(hit['jobs'])} gtm={g}", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    hits = {d: h for d, h in out.items() if h}
    print(f"\n{len(cands)} probed | boards found: {len(hits)} "
          f"(high {sum(h['confidence'] == 'high' for h in hits.values())}, medium {sum(h['confidence'] == 'medium' for h in hits.values())}, "
          f"low {sum(h['confidence'] == 'low' for h in hits.values())}) | with open jobs: {sum(1 for h in hits.values() if h['jobs'])}")


if __name__ == "__main__":
    main()
