"""Phase 4: render the wave-1 outreach drafts for Michel to review and send by hand.

Input : data/private/outreach_wave1.json (drafts written in a Claude Code session from
        each company's dossier, Clay geography and decision makers; every claim has a source)
Output: data/private/outreach_wave1.md (private: contains people's names)

Checks LinkedIn limits: connection note <= 300 characters; DMs kept short (warns over 120 words).
Nothing is sent by the engine.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "private" / "outreach_wave1.json"
OUT = ROOT / "data" / "private" / "outreach_wave1.md"


def block(title: str, text: str, limit: str = "") -> list[str]:
    if not text:
        return []
    return [f"**{title}** ({len(text)} characters{', ' + limit if limit else ''})", "", "```text", text, "```", ""]


def main() -> None:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    lines = ["# Wave 1 outreach drafts (private)", "", d["_how_to_use"], ""]
    warnings = []
    for c in d["companies"]:
        if len(c["connection_note"]) > 300 or len(c["backup_note"]) > 300:
            warnings.append(f"{c['company']}: a note is over 300 characters")
        if len(c["dm"].split()) > 120:
            warnings.append(f"{c['company']}: DM has {len(c['dm'].split())} words")
        lines += [f"## {c['rank']}. {c['company']} ({c['domain']})", "",
                  f"- **Primary:** {c['primary']}", f"- **Backup:** {c['backup'] or '-'}"]
        if c["also"]:
            lines.append(f"- **Also:** {c['also']}")
        lines += ["- **Facts to check before sending:**", *[f"  - {f} ({src})" for f, src in c["facts"]], ""]
        lines += block("1. Connection note", c["connection_note"], "limit 300")
        lines += block("2. Message after they accept", c["dm"], f"{len(c['dm'].split())} words")
        lines += block("3. Follow-up after 5 business days", c["follow_up"])
        lines += block("4. Note to the backup contact (after 10 days)", c["backup_note"], "limit 300")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(d['companies'])} companies -> {OUT}" + (f" | warnings: {warnings}" if warnings else " | all within limits"))


if __name__ == "__main__":
    main()
