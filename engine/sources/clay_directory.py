"""Source 1: Clay's Solutions Partner Directory (clay.com/experts).

Being listed is the strongest public signal that an agency runs Clay for
clients. The directory is hosted on PartnerPage, which exposes public JSON:
a paginated list endpoint and one detail endpoint per partner (location,
ICPs, industry, language, minimum engagement).

Output: data/raw/clay_directory.json (one record per partner).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

DIRECTORY_ID = "2f38fc7e-c90f-40bd-9890-4e2b55b313de"
BASE = "https://admin.partnerpage.io/api"
LIST_URL = f"{BASE}/search/v1alpha/directories/{DIRECTORY_ID}/entries/"
DETAIL_URL = f"{BASE}/directory/public/v1alpha/directories/{DIRECTORY_ID}/entries/partners/slugs/{{slug}}/"
PROFILE_URL = "https://www.clay.com/experts/partner/{slug}"
HEADERS = {"User-Agent": "Mozilla/5.0 (gtm-talent-engine research script)"}
OUT = Path(__file__).resolve().parents[2] / "data" / "raw" / "clay_directory.json"


def list_entries(session: requests.Session) -> list[dict]:
    entries, page = [], 1
    while True:
        resp = session.get(LIST_URL, params={"page": page, "page_size": 100, "ordering": "tier", "seed": 7}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        entries.extend(data["results"])
        if not data.get("next"):
            return entries
        page += 1


def detail(session: requests.Session, slug: str) -> dict:
    for attempt in range(3):
        resp = session.get(DETAIL_URL.format(slug=slug), timeout=30)
        if resp.status_code == 200:
            return resp.json()
        time.sleep(2 * (attempt + 1))
    resp.raise_for_status()
    return {}


def normalize(entry: dict, det: dict) -> dict:
    filter_names = {f["id"]: f["name"] for f in det.get("filters", [])}
    facets: dict[str, list[str]] = {}
    for opt in det.get("assignedFilterOptions", []):
        facets.setdefault(filter_names.get(opt["filter"], "other"), []).append(opt["name"])
    return {
        "source": "clay_directory",
        "name": entry["title"].strip(),
        "website": entry.get("website") or "",
        "clay_tier": (entry.get("tier") or {}).get("title", ""),
        "clay_profile": PROFILE_URL.format(slug=entry["slug"]),
        "location": det.get("location") or "",
        "locations": det.get("locations") or [],
        "headline": entry.get("headline") or "",
        "description": entry.get("description") or "",
        "icps": facets.get("ICPs", []),
        "industries": facets.get("Industry", []),
        "languages": facets.get("Language", []),
        "min_engagement": facets.get("Minimum Engagement", []),
    }


def main() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)
    entries = list_entries(session)
    print(f"{len(entries)} partners listed")
    records = []
    for i, entry in enumerate(entries, 1):
        try:
            det = detail(session, entry["slug"])
        except requests.HTTPError as exc:
            print(f"  ! {entry['slug']}: {exc}")
            det = {}
        records.append(normalize(entry, det))
        if i % 25 == 0:
            print(f"  {i}/{len(entries)}")
        time.sleep(0.4)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {len(records)} -> {OUT}")


if __name__ == "__main__":
    main()
