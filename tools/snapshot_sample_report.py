"""Freeze a dataset's report as the public sample (home page tabs and /sample).

    PYTHONPATH=. .venv/bin/python tools/snapshot_sample_report.py <dataset_id>

Writes frontend/public/sample/report.json with exactly what a share link returns for that dataset's latest
report (app.api_sharing.public_report -> app.api_report._render_report): chart fragments built from
aggregates plus the quotes and phrases blocks, never the answer drill-down. `sample_extras` adds the
latest Look inside Other result and the answer map's dot positions (no answer text), for the Inside Other
section. The file is public, so only snapshot a dataset whose comments may be published (user's decision, 2026-10-26: the 10k workplace survey).
Refuses a stale report, and prints anything that looks like an email address or a link so it can be
checked by hand before committing.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "sample" / "report.json"


def main(dataset_id: int) -> None:
    load_dotenv()
    from sqlalchemy import select

    from app import db as _db
    from app.api_report import _render_report
    from app.api_themes import answer_map_data
    from app.models import Dataset, Job, Report

    with _db.SessionLocal() as s:
        ds = s.get(Dataset, dataset_id)
        if ds is None:
            sys.exit(f"No dataset {dataset_id}.")
        report = s.scalars(select(Report).where(Report.dataset_id == dataset_id).order_by(Report.id.desc())).first()
        if report is None or not isinstance(report.content, dict):
            sys.exit(f"Dataset {dataset_id} has no report.")
        column = report.content["column"]
        out = _render_report(s, ds, column, report)
        # The report page's "Inside Other" section and its answer map, which the app fetches with sign-in:
        # the latest finished Look inside Other result (counts, labels, tones) and the dot positions.
        look = s.scalars(select(Job).where(Job.dataset_id == dataset_id, Job.column_name == column,
                                           Job.kind == "look_inside_other", Job.status == "done")
                         .order_by(Job.id.desc())).first()
        out["sample_extras"] = {
            "look_inside_other": look.result if look is not None else None,
            "answer_map": answer_map_data(s, dataset_id, column),
        }
    if out.get("stale"):
        sys.exit("That report is out of date. Rebuild it first.")
    out["dataset_id"] = 0  # the sample is not a real dataset of the viewer's

    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", json.dumps(out, ensure_ascii=False))).split())
    for label, pattern in (("email", r"[\w.+-]+@[\w-]+\.[\w.]+"), ("link", r"https?://\S+")):
        hits = sorted(set(re.findall(pattern, text)))
        if hits:
            print(f"Check by hand, {label}: {hits[:10]}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB) from dataset {dataset_id}, column {out['column']!r}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(int(sys.argv[1]))
