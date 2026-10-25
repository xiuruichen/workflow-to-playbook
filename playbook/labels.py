"""Export human step reviews as a dataset for learning confidence calibration.

Each row is one step a reviewer marked correct or wrong, with the features the current
rule-based calibration uses. Once a few hundred rows exist, a small model (e.g. logistic or
isotonic regression from these features to P(correct)) can replace the hand-set penalties in
analyzer.py. Until then this file is just the data collection side.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Playbook

COLUMNS = [
    "session", "step", "action", "source", "model", "model_confidence", "confidence", "threshold",
    "event_supported", "long_gap", "repaired", "merged_candidates", "duration_s", "has_review_note",
    "flagged", "label",
]


def step_rows(pb: Playbook) -> list[dict]:
    rows = []
    for s in pb.steps:
        if s.review == "unreviewed":
            continue
        notes = " ".join(s.calibration_notes)
        rows.append({
            "session": pb.session_id,
            "step": s.index,
            "action": s.action,
            "source": pb.source,
            "model": pb.model,
            "model_confidence": round(s.model_confidence, 3),
            "confidence": round(s.confidence, 3),
            "threshold": pb.threshold,
            "event_supported": int("No mouse/keyboard event" not in notes and "Imported video" not in notes),
            "long_gap": int("gap between screenshots" in notes),
            "repaired": int("repair" in notes),
            "merged_candidates": len(s.source_ids),
            "duration_s": round(s.t_end - s.t_start, 2),
            "has_review_note": int(bool(s.review_note)),
            "flagged": int(s.needs_review),
            "label": int(s.review == "correct"),
        })
    return rows


def export_labels(session_dirs: list[Path], out: Path) -> int:
    rows = []
    for d in session_dirs:
        if d.suffix == ".pbx":  # archived: read playbook.json straight from the archive
            from .archive import read_member

            data = read_member(d, "playbook.json")
            if data:
                rows += step_rows(Playbook.model_validate_json(data))
        elif (d / "playbook.json").exists():
            rows += step_rows(Playbook.load(d))
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
