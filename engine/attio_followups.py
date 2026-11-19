"""Phase 4 cadence: Attio tasks for every company Michel moves to "Contacted".

Nothing is sent. When an entry in the GTM Talent Pipeline is at "Contacted"
(Michel sent the LinkedIn connection note and moved the card), this creates
tasks assigned to him, counted in business days from the day the card moved:

  day 3   Check if <primary> accepted; if so, send the message (text included)
  day 8   Follow-up to <primary> (text included)
  day 13  Note to the backup contact (text included), when there is a backup

When the entry reaches "Replied" or any later stage, the open tasks this
script created for that company are marked complete ("they answered, stop
chasing"). Tasks are found again by a marker in their text, so runs are
idempotent: run it after moving cards, or once a day.

Message texts come from data/private/outreach_wave1.json; companies without
drafts get the same tasks without text.

Usage: python engine/attio_followups.py [--dry-run] [--pretend-contacted DOMAIN]
  --pretend-contacted treats DOMAIN as moved to Contacted today (with --dry-run: a preview, no writes)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import attio_sync as A  # noqa: E402  (HTTP client, dry-run log, list constants)

MARKER = "[GTM Talent Engine · {domain} · {step}]"
STEPS = [  # (step id, business days after Contacted, title, draft key)
    ("dm", 3, "Check if {primary} accepted the connection; if yes, send the message", "dm"),
    ("follow_up", 8, "Follow-up to {primary} (no reply yet)", "follow_up"),
    ("backup", 13, "Note to the backup contact: {backup}", "backup_note"),
]
DONE_STAGES = {"Replied", "Call", "Trial project", "Offer", "Closed"}
DRAFTS = ROOT / "data" / "private" / "outreach_wave1.json"
OWNER = A.env("ATTIO_OWNER_MEMBER_ID")  # Attio workspace member who gets the tasks


def add_business_days(start: dt.date, days: int) -> dt.date:
    d = start
    while days:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            days -= 1
    return d


def stage_of(entry: dict) -> tuple[str, str]:
    v = (entry["entry_values"].get("stage") or [{}])[0]
    return (v.get("status") or {}).get("title", ""), v.get("active_from", "")


def main() -> None:
    pretend = sys.argv[sys.argv.index("--pretend-contacted") + 1] if "--pretend-contacted" in sys.argv else None
    drafts = {c["domain"]: c for c in json.loads(DRAFTS.read_text(encoding="utf-8"))["companies"]} if DRAFTS.exists() else {}
    slug = A.LIST["api_slug"]
    entries = A.attio("POST", f"lists/{slug}/entries/query", {"limit": 500}).get("data", [])
    made = closed = 0
    for e in entries:
        rid = e["parent_record_id"]
        stage, since = stage_of(e)
        rec = A.attio("GET", f"objects/companies/records/{rid}")["data"]
        domain = (rec["values"].get("domains") or [{}])[0].get("domain", "")
        if pretend and domain == pretend:
            stage, since = "Contacted", dt.datetime.now(dt.timezone.utc).isoformat()
        if stage not in {"Contacted"} | DONE_STAGES:
            continue
        tasks = A.attio("GET", f"tasks?linked_object=companies&linked_record_id={rid}&limit=100").get("data", [])
        mine = {t["content_plaintext"].split("]")[0] + "]": t for t in tasks
                if t.get("content_plaintext", "").startswith("[GTM Talent Engine")}
        if stage in DONE_STAGES:
            for t in mine.values():
                if not t.get("is_completed"):
                    A.attio("PATCH", f"tasks/{t['id']['task_id']}", {"data": {"is_completed": True}})
                    closed += 1
            continue
        d = drafts.get(domain, {})
        primary = (d.get("primary") or "the primary contact").split(" (")[0]
        backup = (d.get("backup") or "").split(" (")[0]
        start = dt.datetime.fromisoformat(since.replace("Z", "+00:00")[:26] + "+00:00" if "+" not in since else since).date() \
            if since else dt.date.today()
        for step, days, title, key in STEPS:
            if step == "backup" and not backup:
                continue
            marker = MARKER.format(domain=domain, step=step)
            if marker in mine:
                continue
            text = d.get(key, "")
            content = f"{marker} {title.format(primary=primary, backup=backup)}." + (f"\n\nDraft (review before sending):\n{text}" if text else "")
            due = add_business_days(start, days)
            A.attio("POST", "tasks", {"data": {
                "content": content, "format": "plaintext", "is_completed": False,
                "deadline_at": f"{due.isoformat()}T15:00:00.000Z",  # noon in São Paulo
                "linked_records": [{"target_object": "companies", "target_record_id": rid}],
                "assignees": [{"referenced_actor_type": "workspace-member", "referenced_actor_id": OWNER}]}})
            made += 1
            if A.DRY:
                print(f"  {domain}: {step} due {due} · {content[:110]!r}")
    print(json.dumps({"tasks_created": made, "tasks_closed": closed}))


if __name__ == "__main__":
    main()
