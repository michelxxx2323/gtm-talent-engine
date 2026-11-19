"""Phase 4 → Attio: mark wave-1 companies as "Drafted" and attach the drafts as a note.

For each company in data/private/outreach_wave1.json:
  - the GTM Talent Pipeline entry moves to "Drafted", but only forward: an entry
    already at Drafted or later (Contacted, Replied, ...) is left where it is
  - a note "Wave 1 outreach drafts" is added to the company record, once (a note
    with that title already there is not duplicated)

The note holds the facts with sources, the four messages and the extra steps.
Attio is Michel's private CRM, where contacts are meant to live; nothing is sent.

Usage: python engine/attio_outreach.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import attio_sync as A  # noqa: E402  (reuses its HTTP client, dry-run log and list constants)

NOTE_TITLE = "Wave 1 outreach drafts"
SRC = ROOT / "data" / "private" / "outreach_wave1.json"


def note_text(c: dict) -> str:
    parts = [f"Primary: {c['primary']}", f"Backup: {c['backup'] or '-'}"]
    if c["also"]:
        parts.append(f"Also: {c['also']}")
    parts.append("Facts to check before sending:")
    parts += [f"- {f} ({src})" for f, src in c["facts"]]
    for title, key in [("1. Connection note", "connection_note"), ("2. Message after they accept", "dm"),
                       ("3. Follow-up after 5 business days", "follow_up"),
                       ("4. Note to the backup contact (after 10 days)", "backup_note")]:
        if c[key]:
            parts += ["", f"{title}:", c[key]]
    parts += ["", "Drafts from the GTM Talent Engine. Michel reviews and sends by hand. Replace [LOOM] before sending."]
    return "\n".join(parts)


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    slug = A.LIST["api_slug"]
    entries = A.attio("POST", f"lists/{slug}/entries/query", {"limit": 500}).get("data", [])
    by_parent = {e["parent_record_id"]: e for e in entries}
    order = {s: i for i, s in enumerate(A.STAGES)}
    moved = kept = notes_new = notes_kept = 0
    missing = []
    for c in d["companies"]:
        found = A.attio("POST", "objects/companies/records/query",
                        {"filter": {"domains": {"domain": {"$eq": c["domain"]}}}, "limit": 1}).get("data", [])
        if not found:
            missing.append(c["company"])
            continue
        rid = found[0]["id"]["record_id"]
        entry = by_parent.get(rid)
        if not entry:
            missing.append(c["company"] + " (not in the list)")
            continue
        current = ((entry["entry_values"].get("stage") or [{}])[0].get("status") or {}).get("title", "Qualified")
        if order.get(current, 0) < order["Drafted"]:
            A.attio("PATCH", f"lists/{slug}/entries/{entry['id']['entry_id']}", {"data": {"entry_values": {"stage": "Drafted"}}})
            moved += 1
        else:
            kept += 1
        notes = A.attio("GET", f"notes?parent_object=companies&parent_record_id={rid}&limit=50").get("data", [])
        # dated updates (keys like "update_2026_11_19"): one short note each, posted once,
        # with the full rewritten drafts so the Attio record stays the place to send from
        for key in sorted(k for k in c if k.startswith("update_")):
            title = f"Wave 1 drafts: update {key[7:].replace('_', '-')}"
            if not any(n.get("title") == title for n in notes):
                A.attio("POST", "notes", {"data": {"parent_object": "companies", "parent_record_id": rid, "title": title,
                                                   "format": "plaintext", "content": c[key] + "\n\n" + note_text(c)}})
                notes_new += 1
        if any(n.get("title") == NOTE_TITLE for n in notes):
            notes_kept += 1
            continue
        A.attio("POST", "notes", {"data": {"parent_object": "companies", "parent_record_id": rid, "title": NOTE_TITLE,
                                           "format": "plaintext", "content": note_text(c)}})
        notes_new += 1
    print(json.dumps({"moved_to_drafted": moved, "already_drafted_or_later": kept, "notes_new": notes_new,
                      "notes_already_there": notes_kept, "missing": missing}))
    if A.DRY:
        print(f"{len(A.LOG)} write calls planned; first ones:")
        for line in A.LOG[:4]:
            print(" ", line[:200])


if __name__ == "__main__":
    main()
