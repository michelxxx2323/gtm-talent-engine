"""Human labels for calibration.

  python engine/labels.py sheet [pilot]     -> data/out/pilot_labels.xlsx (Michel fills the yellow columns)
  python engine/labels.py report [pilot]    -> agreement of Claude, Jev and the average with Michel

The sheet hides nothing Michel needs (links, notes, both evaluators) but
puts the yellow columns first so the decision is his, not an echo of the
models: he can fill them before reading the model columns.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
YELLOW = PatternFill("solid", fgColor="FFF2CC")
GREY = PatternFill("solid", fgColor="EDEDED")
HUMAN = ["michel_band", "michel_want_to_work_there", "michel_reason"]
BANDS = ["A", "B", "C", "Out"]


def sheet(which: str) -> None:
    rows = json.loads((ROOT / "data" / "out" / f"scored_{which}.json").read_text(encoding="utf-8"))
    cands = {c["name"]: c for c in json.loads((ROOT / "data" / "out" / f"{which}.json").read_text(encoding="utf-8"))}
    wb = Workbook()
    ws = wb.active
    ws.title = "labels"
    cols = ["name", *HUMAN, "website", "clay_profile", "gtm_daily_profile", "country", "clay_tier",
            "final_band", "avg_points", "claude_band", "claude_points", "jev_band", "jev_points", "disputes",
            "claude_failed_gates", "jev_failed_gates", "claude_notes", "evidence"]
    ws.append(cols)
    for r in sorted(rows, key=lambda x: -x["avg_points"]):
        c = cands.get(r["name"], {})
        ws.append([r["name"], "", "", "", f"https://{r['domain']}" if r["domain"] else c.get("linkedin", ""),
                   c.get("clay_profile", ""), c.get("gtm_daily_profile", ""), r["country"], r["clay_tier"],
                   r["final_band"], r["avg_points"], r["claude_band"], r["claude_points"], r["jev_band"], r["jev_points"],
                   r["disputes"], r["claude_failed_gates"], r["jev_failed_gates"], r["claude_notes"], r["evidence"]])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = YELLOW if cell.value in HUMAN else GREY
    widths = {"A": 30, "B": 12, "C": 14, "D": 40, "E": 28, "S": 70, "T": 70}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row[1:4]:
            cell.fill = YELLOW
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    dv = DataValidation(type="list", formula1='"' + ",".join(BANDS) + '"', allow_blank=True)
    dv2 = DataValidation(type="list", formula1='"yes,maybe,no"', allow_blank=True)
    ws.add_data_validation(dv)
    ws.add_data_validation(dv2)
    dv.add(f"B2:B{ws.max_row}")
    dv2.add(f"C2:C{ws.max_row}")
    ws.freeze_panes = "B2"

    guide = wb.create_sheet("how to label")
    for line in [
        "Fill the yellow columns BEFORE reading the model columns, so your label is yours.",
        "michel_band: A = contact in wave 1; B = wave 2; C = keep, do not contact; Out = not an employer for you.",
        "michel_want_to_work_there: your gut call (yes / maybe / no), separate from the band.",
        "michel_reason: one line, especially when you disagree with final_band. This is what tunes the rubric.",
        "Rubric: config/rubric.md. Gates: service business, has a team, active, not closed to Brazil.",
    ]:
        guide.append([line])
    guide.column_dimensions["A"].width = 120
    out = ROOT / "data" / "out" / f"{which}_labels.xlsx"
    wb.save(out)
    print(f"saved {out}")


def report(which: str) -> None:
    ws = load_workbook(ROOT / "data" / "out" / f"{which}_labels.xlsx").active
    head = [c.value for c in ws[1]]
    rows = [dict(zip(head, [c.value for c in r])) for r in ws.iter_rows(min_row=2)]
    # model columns come from the CURRENT scoring run, not from the sheet
    # (the sheet keeps the bands Michel saw when he labeled)
    current = {r["name"]: r for r in json.loads((ROOT / "data" / "out" / f"scored_{which}.json").read_text(encoding="utf-8"))}
    rows = [{**r, **{k: current[r["name"]][k] for k in ("claude_band", "jev_band", "final_band", "avg_points")}}
            for r in rows if r.get("michel_band") and r["name"] in current]
    if not rows:
        print("no labels yet")
        return

    def contact(b: str) -> bool:
        return b in ("A", "B")

    for ev in ("claude_band", "jev_band", "final_band"):
        exact = sum(1 for r in rows if r[ev] == r["michel_band"])
        same_call = sum(1 for r in rows if contact(r[ev] or "") == contact(r["michel_band"]))
        print(f"{ev:<12} exact band {exact}/{len(rows)} | contact-or-not {same_call}/{len(rows)}")
    print("\nDisagreements with Michel (final_band):")
    for r in rows:
        if r["final_band"] != r["michel_band"]:
            print(f"- {r['name']}: model {r['final_band']} ({r['avg_points']}) vs Michel {r['michel_band']} | {r.get('michel_reason') or ''}")


if __name__ == "__main__":
    cmd, which = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "pilot")
    {"sheet": sheet, "report": report}[cmd](which)
