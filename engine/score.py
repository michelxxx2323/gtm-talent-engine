"""Phase 2, step 2: blind double scoring with the rubric in config/rubric.yaml.

  python engine/score.py dossier [pilot|candidates]  -> data/dossiers/<key>.md (same text for both evaluators)
  python engine/score.py jev [pilot|candidates]      -> data/scores/jev/<key>.json
  python engine/score.py compare [pilot|candidates]  -> data/out/scored_<which>.csv/.json

Claude's scores are written to data/scores/claude/<key>.json by a Claude Code
session that reads only the dossiers and the rubric, BEFORE the Jev run, so
neither evaluator sees the other. Both files share one shape:
  {"gates": {id: prob 0-1}, "levels": {id: 0-4}, "evidence": {id: url}, "notes": "..."}
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from research import env, key_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = yaml.safe_load((ROOT / "config" / "rubric.yaml").read_text(encoding="utf-8"))
DOSSIERS = ROOT / "data" / "dossiers"
SCORES = ROOT / "data" / "scores"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
ATS_JOBS = ROOT / "data" / "raw" / "ats_jobs.json"
CLAY_COMPANY = ROOT / "data" / "raw" / "clay_company.json"
CLAY_GEO = ROOT / "data" / "raw" / "clay_geography.json"
BOARD_MATCHES = ROOT / "data" / "raw" / "jobboard_matches.json"
CAPS = {"home": 2200, "team": 1600, "careers": 1400, "services": 1300, "cases": 1000, "blog": 700, "pricing": 600}


def strip_shared_chrome(pages: list[dict]) -> list[dict]:
    """Sites repeat the same menu on every page, which eats the character
    budget. Remove from each page the longest block (>= 120 chars, within the
    first 4,000) it shares with another page of the same site, up to 3 times."""
    from difflib import SequenceMatcher

    texts = [p["text"] for p in pages]
    out = []
    for i, p in enumerate(pages):
        text = texts[i]
        for _ in range(3):
            best = None
            for j, other in enumerate(texts):
                if i == j:
                    continue
                m = SequenceMatcher(None, text[:4000], other[:4000], autojunk=False).find_longest_match(0, min(len(text), 4000), 0, min(len(other), 4000))
                if m.size >= 120 and (best is None or m.size > best.size):
                    best = m
            if not best:
                break
            text = (text[: best.a] + " " + text[best.a + best.size:]).strip()
        out.append({**p, "text": text})
    return out


def load(which: str) -> list[dict]:
    return json.loads((ROOT / "data" / "out" / f"{which}.json").read_text(encoding="utf-8"))


def dossier(c: dict) -> str:
    pack = json.loads((ROOT / "data" / "research" / f"{key_of(c)}.json").read_text(encoding="utf-8"))
    d, a = pack["directory"], pack.get("apollo") or {}
    lines = [f"# {pack['name']} ({pack['domain'] or 'no website'})", ""]
    if pack["aliases"]:
        lines.append(f"Also listed under: {', '.join(pack['aliases'])}")
    lines.append(f"Directory location: {d['location'] or 'unknown'} | region: {pack['region']}")
    if d["clay_tier"]:
        lines.append(f"Clay Solutions Partner Directory: tier {d['clay_tier']} ({d['clay_profile']})")
        lines.append(f"Directory ICPs/industries: {d['icps']} | languages: {d['languages']} | minimum engagement: {d['min_engagement']}")
    if d["gtm_daily_profile"]:
        lines.append(f"GTM Daily agency listing: {d['gtm_daily_profile']} | services: {d['services'] or '-'}")
    if d.get("linkedin"):
        lines.append(f"Listed website is a LinkedIn profile: {d['linkedin']}")
    lines += ["", "## Directory description", d["description"] or "-", ""]
    cc = json.loads(CLAY_COMPANY.read_text(encoding="utf-8")).get(pack["domain"], {}) if CLAY_COMPANY.exists() else {}
    if cc.get("name"):  # Clay enrichment waterfall (Clay first; Datagma only as fallback)
        lines += [f"## Clay company record (enrichment waterfall, provider: {cc['source']})",
                  f"Employees: {cc.get('employee_count')} | size range: {cc.get('size')} | founded: {cc.get('founded')} | "
                  f"HQ: {cc.get('hq') or '-'} ({cc.get('country') or '-'})",
                  f"Office locations: {'; '.join(x for x in cc.get('locations') or [] if x) or '-'}",
                  f"LinkedIn: {cc.get('linkedin') or '-'} | followers: {cc.get('follower_count') or '-'} | industry: {cc.get('industry') or '-'}",
                  f"Specialties: {', '.join(cc.get('specialties') or []) or '-'}",
                  f"Description: {cc.get('derived_description') or cc.get('description') or '-'}", ""]
    geo = json.loads(CLAY_GEO.read_text(encoding="utf-8")).get(pack["domain"], {}) if CLAY_GEO.exists() else {}
    if geo.get("people_count"):  # Clay: current employees per country (the team_geography evidence)
        pct = lambda v: "-" if v is None else f"{round(v * 100)}%"  # noqa: E731
        lines += ["## Team geography (Clay, current employees by country)",
                  f"People found: {geo['people_count']} | North America + Europe: {pct(geo['share_west'])} | "
                  f"LatAm: {pct(geo['share_latam'])} | elsewhere: {pct(geo.get('share_other'))} | "
                  f"in Brazil: {geo['brazil']}",
                  "Top countries: " + ", ".join(f"{c} {n}" for c, n in geo["by_country"]), ""]
    if a.get("name"):
        lines += ["## Apollo company record", f"Employees: {a.get('employees')} | founded: {a.get('founded')} | HQ: {a.get('location')}",
                  f"Headcount growth 6m: {a.get('growth_6m')} | 12m: {a.get('growth_12m')} | departments: {a.get('departments')}",
                  f"LinkedIn: {a.get('linkedin')}", f"Technologies on site: {', '.join(a.get('technologies') or []) or '-'}",
                  f"Description: {a.get('description') or '-'}", ""]
    else:
        err = a.get("error", "not available")
        if "422" in err:  # free-plan credits ran out: says nothing about the company
            err = "not available: Apollo credits ran out for this run. This is MISSING DATA, not evidence about the company"
        if not cc.get("name"):  # when Clay has the record, the Apollo gap does not matter
            lines += [f"## Apollo company record\n{err}", ""]
    if pack["gtm_jobs"]:
        lines.append("## GTM jobs posted on GTM Daily")
        lines += [f"- {j['title']} | {j['location']} | tools: {j['tools']} | posted {j['posted'] or '?'} | {j['link']}" for j in pack["gtm_jobs"]]
        lines.append("")
    ats = json.loads(ATS_JOBS.read_text(encoding="utf-8")).get(pack["domain"], {}) if ATS_JOBS.exists() else {}
    if ats and ats.get("confidence") in ("high", "medium"):
        lines.append(f"## Public job board ({ats['ats']}, board '{ats['slug']}', match confidence {ats['confidence']})")
        if not ats["jobs"]:
            lines.append("- board exists, no open jobs right now")
        lines += [f"- {j['title']} | {j['location'] or '-'} | remote: {j.get('remote')} | posted {j['posted'] or '?'} | {j['url']}"
                  for j in ats["jobs"][:8]]
        lines.append("")
    board_jobs = json.loads(BOARD_MATCHES.read_text(encoding="utf-8")).get(pack["name"], []) if BOARD_MATCHES.exists() else []
    if board_jobs:
        lines.append("## Jobs by this company seen on remote job boards (job-fit-screener collection)")
        lines += [f"- {j['title']} | {j['location'] or '-'} | {j['source']} | posted {j['posted'] or '?'} | {j['link']}" for j in board_jobs[:8]]
        lines.append("")
    if pack["ats_links"]:
        lines += ["## Job board / ATS links found on the site", *[f"- {x}" for x in pack["ats_links"]], ""]
    dated = [d for d in pack.get("dates", []) if d.get("latest_year") or d.get("copyright_year")]
    if dated:
        lines.append("## Dates found on the website")
        lines += [f"- {d['url']}: latest date '{d['latest_date'] or '-'}' | copyright {d['copyright_year'] or '-'}" for d in dated]
        lines.append("")
    if pack["errors"]:
        lines += ["## Research problems", *[f"- {e}" for e in pack["errors"]], ""]
    for p in strip_shared_chrome(pack["pages"]):
        lines += [f"## Website: {p['kind']} page ({p['url']})", p["text"][: CAPS.get(p["kind"], 800)], ""]
    return "\n".join(lines)


def cmd_dossier(which: str) -> None:
    DOSSIERS.mkdir(parents=True, exist_ok=True)
    for c in load(which):
        (DOSSIERS / f"{key_of(c)}.md").write_text(dossier(c), encoding="utf-8")
    print(f"dossiers written to {DOSSIERS}")


def checks() -> dict:
    """Gates (fail -> Out) and caps (fail -> at most C), in one id space."""
    return {**RUBRIC["gates"], **RUBRIC.get("caps", {})}


def jev_questions() -> dict:
    q = {f"gate_{gid}": {"type": "noul", "instructions": text} for gid, text in checks().items()}
    for cid, crit in RUBRIC["criteria"].items():
        q[cid] = {"type": "score", "instructions": crit["instructions"], "criteria": crit["levels"]}
    return q


def ask_jev(state: dict, questions: dict) -> dict:
    headers = {"Authorization": f"Bearer {env('TYPESAFE_API_KEY')}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(6):
        try:
            resp = requests.post(JEV_URL, json={"state": state, "model": "jev-latest", "questions": questions},
                                 headers=headers, timeout=60)
        except requests.RequestException:
            resp = None
        if resp is not None and resp.status_code == 200:
            return resp.json()
        if resp is not None and resp.status_code in (401, 422):
            raise RuntimeError(f"Jev {resp.status_code}: {resp.text[:300]}")
        time.sleep(delay + random.random() / 2)
        delay *= 2
    raise RuntimeError("Jev did not answer")


def cmd_jev(which: str) -> None:
    out = SCORES / "jev"
    out.mkdir(parents=True, exist_ok=True)
    questions = jev_questions()
    for c in load(which):
        path = out / f"{key_of(c)}.json"
        if path.exists():
            continue
        text = (DOSSIERS / f"{key_of(c)}.md").read_text(encoding="utf-8")
        state = {"task": RUBRIC["question"], "company_evidence": text}
        resp = ask_jev(state, questions)
        ans = resp.get("answers", {})
        rec = {
            "gates": {gid: ans.get(f"gate_{gid}", {}).get("noul") for gid in checks()},
            "levels": {cid: ans.get(cid, {}).get("score") for cid in RUBRIC["criteria"]},
            "confidence": {cid: ans.get(cid, {}).get("confidence") for cid in RUBRIC["criteria"]},
            "evidence": {}, "notes": "", "model": resp.get("model"),
        }
        path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        print(f"jev: {c['name']}", flush=True)


def total(rec: dict, region: str) -> tuple[float, bool, list[str], list[str]]:
    """(points, passes gates, failed gates, failed caps)."""
    def low(g: str) -> bool:
        p = rec["gates"].get(g)
        return p is None or p < 0.5
    failed = [g for g in RUBRIC["gates"] if low(g)]
    capped = [g for g in RUBRIC.get("caps", {}) if low(g)]
    pts = sum(RUBRIC["criteria"][cid]["weight"] * (rec["levels"].get(cid) or 0) / 4 for cid in RUBRIC["criteria"])
    if region == "secondary":
        pts -= RUBRIC["secondary_region_penalty"]
    return round(pts, 1), not failed, failed, capped


def band(points: float, passes: bool, capped: list[str] | None = None) -> str:
    if not passes:
        return "Out"
    b = "A" if points >= RUBRIC["bands"]["A"] else "B" if points >= RUBRIC["bands"]["B"] else "C"
    return "C" if capped and b in ("A", "B") else b


def company_record(pack: dict) -> str:
    """Where the firmographics came from: clay (waterfall), apollo, or missing."""
    if CLAY_COMPANY.exists() and json.loads(CLAY_COMPANY.read_text(encoding="utf-8")).get(pack["domain"], {}).get("name"):
        return "clay"
    return "apollo" if (pack.get("apollo") or {}).get("name") else "missing"


def cmd_compare(which: str) -> None:
    rows = []
    for c in load(which):
        k = key_of(c)
        recs = {}
        for ev in ("claude", "jev"):
            p = SCORES / ev / f"{k}.json"
            if p.exists():
                recs[ev] = json.loads(p.read_text(encoding="utf-8"))
        if "jev" not in recs:
            print(f"skip {c['name']}: no Jev score")
            continue
        if "claude" not in recs:  # full run: Jev on everything, Claude only on a sample
            recs["claude"] = None
        res = {ev: total(r, c["region"]) for ev, r in recs.items() if r}
        bands = {ev: band(pts, ok, cap) for ev, (pts, ok, _, cap) in res.items()}
        disputes = []
        if recs["claude"]:
            avg = round((res["claude"][0] + res["jev"][0]) / 2, 1)
            both_pass = res["claude"][1] and res["jev"][1]
            both_capped = [g for g in res["claude"][3] if g in res["jev"][3]]
            final = band(avg, both_pass, both_capped)
            if res["claude"][1] != res["jev"][1] or set(res["claude"][3]) != set(res["jev"][3]):
                disputes.append(f"gates/caps differ (Claude {res['claude'][2] + res['claude'][3] or '-'}, Jev {res['jev'][2] + res['jev'][3] or '-'})")
            if bands["claude"] != bands["jev"]:
                disputes.append(f"band {bands['claude']} vs {bands['jev']}")
            if abs(res["claude"][0] - res["jev"][0]) >= 15:
                disputes.append(f"points {res['claude'][0]} vs {res['jev'][0]}")
        else:
            avg, final = res["jev"][0], bands["jev"]
        # Fixed rule, not a model call: a parked / for-sale domain is a closed company.
        pack = json.loads((ROOT / "data" / "research" / f"{k}.json").read_text(encoding="utf-8"))
        if any("domain parked or for sale" in e for e in pack.get("errors", [])):
            final, disputes = "Out", []
        cl = recs["claude"] or {"levels": {}, "notes": "", "evidence": {}}
        rows.append({
            "name": c["name"], "domain": c["domain"], "country": c["country"], "clay_tier": c["clay_tier"],
            "evaluators": "claude+jev" if recs["claude"] else "jev only",
            "stratum": c.get("pilot_stratum", ""), "final_band": "Dispute: Michel decides" if disputes else final,
            "avg_points": avg, "claude_points": res["claude"][0] if recs["claude"] else "",
            "claude_band": bands.get("claude", ""),
            "jev_points": res["jev"][0], "jev_band": bands["jev"], "disputes": "; ".join(disputes),
            **{f"claude_{cid}": cl["levels"].get(cid, "") for cid in RUBRIC["criteria"]},
            **{f"jev_{cid}": recs["jev"]["levels"].get(cid) for cid in RUBRIC["criteria"]},
            "claude_failed_gates": ", ".join(res["claude"][2] + [f"cap:{x}" for x in res["claude"][3]]) if recs["claude"] else "",
            "jev_failed_gates": ", ".join(res["jev"][2] + [f"cap:{x}" for x in res["jev"][3]]),
            "claude_notes": cl.get("notes", ""),
            "evidence": " | ".join(f"{k2}: {v}" for k2, v in cl.get("evidence", {}).items()),
            "company_record": company_record(pack),
        })
    out = ROOT / "data" / "out"
    (out / f"scored_{which}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if rows:
        with (out / f"scored_{which}.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    dual = [r for r in rows if r["evaluators"] == "claude+jev"]
    agree = sum(1 for r in dual if not r["disputes"])
    bands_count = {}
    for r in rows:
        bands_count[r["final_band"]] = bands_count.get(r["final_band"], 0) + 1
    print(f"{len(rows)} scored ({len(dual)} by both: agree {agree}, disputes {len(dual) - agree}) | bands {bands_count}")


if __name__ == "__main__":
    cmd, which = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "pilot")
    {"dossier": cmd_dossier, "jev": cmd_jev, "compare": cmd_compare}[cmd](which)
