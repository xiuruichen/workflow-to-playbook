"""Amendment 11, H20: amounts drawn with thousands separators ("7,200"), read through real OCR, before and after the repair.

    python scripts/run_fix_capture.py            # 40 triage visits, seed 11, writes docs/results/fix_capture.md

The baseline reading is each number as OCR wrote it, parsed the old way (separators dropped); the repaired reading is what
`decisions.pool` produces now.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import triage  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.decisions import pool  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"
settings = get_settings().model_copy(update={"use_ocr": True})
visits = triage.make_visits(40, 11)
root = Path(tempfile.mkdtemp(prefix="capture_sep_"))
decisions = pool(triage.build_sessions(settings, root, visits, separators=True))
n = len(visits)
assert len(decisions) == n, f"{len(decisions)} decisions for {n} visits"
baseline = sum(float(d.raw["amount"].replace(",", "")) == float(v.amount) for d, v in zip(decisions, visits) if "amount" in d.raw)
after = sum(d.readouts.get("amount") == float(v.amount) for d, v in zip(decisions, visits))
misread = [d.raw.get("amount") for d, v in zip(decisions, visits) if d.raw.get("amount") and "," not in d.raw["amount"] and "." in d.raw["amount"]]
text = (f"# Amendment 11, H20: thousands separators through OCR (40 triage visits, seed 11)\n\n"
        f"| reading | amounts exact |\n|---|---|\n| before the repair (old parsing) | {baseline}/{n} |\n| after the repair | {after}/{n} |\n\n"
        f"Readings OCR gave with a full stop where the comma was drawn: {len(misread)} ({', '.join(misread[:8])}).\n\n"
        f"**H20 (40 of 40 exact after the repair): {'holds' if after == n else 'FAILS'}.**\n")
(RESULTS / "fix_capture.md").write_text(text, encoding="utf-8")
print(text)
