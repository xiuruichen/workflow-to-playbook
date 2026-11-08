"""E7: one continuous recording of many checks. How many of the person's decisions does the pipeline find, as a
function of how fast they decide and of the dwell threshold? (docs/evaluation-protocol.md, amendment 6)"""
import json
import random
import statistics as st
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import dashboard  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.decisions import NONE, build_decisions  # noqa: E402
from playbook.models import Manifest  # noqa: E402
from playbook.scenarios import simulate  # noqa: E402

def _batch(d):  # OCR may spell "Batch size" without the space
    return next((v for k, v in d.readouts.items() if k.replace("_", "") == "batchsize"), None)


OUT = Path(__file__).resolve().parent.parent / "docs" / "results"
SEEDS, N = (1, 2, 3), 15
settings = get_settings().model_copy(update={"use_ocr": True})
rows = []
for seed in SEEDS:
    visits = dashboard.make_visits(N, seed)
    rng = random.Random(seed)
    dwells = [rng.uniform(2.0, 12.0) for _ in visits]
    root = Path(tempfile.mkdtemp(prefix="continuous_"))
    session = simulate(dashboard.continuous_scenario(visits, dwells, f"cont{seed}"), settings, root / "s")
    m = Manifest.load(session)
    owners = [-1] + [i for i, v in enumerate(visits) for _ in range(2 if v.stop else 1)]  # which visit each click ends
    times = [e.t for e in m.events if e.kind == "click"]
    for thr in (8.0, 5.0, 3.0, 2.0):
        for nav in ((), ("Next run",)):
            found = build_decisions(session, dwell_min_s=thr, navigation=nav)
            by_visit = {}
            for d in found:  # the pause that ends at a click belongs to the visit that click closes
                j = min(range(len(times)), key=lambda k: abs(times[k] - d.t1))
                if abs(times[j] - d.t1) < 0.2 and owners[j] >= 0:
                    by_visit.setdefault(owners[j], []).append(d)
            read_ok = right_ok = 0
            for i, v in enumerate(visits):
                ds = by_visit.get(i)
                if not ds:
                    continue
                d = ds[0]  # the look before the visit's first click
                if d.readouts.get("spikes") == v.spikes and _batch(d) == v.batch_size:
                    read_ok += 1
                    right_ok += (d.outcome != NONE) == v.stop
            rows.append({"seed": seed, "threshold": thr, "navigation_ignored": bool(nav), "visits": N, "decisions_found": len(found),
                         "visits_with_readouts_found": read_ok, "visits_with_right_outcome": right_ok,
                         "short_looks": sum(d < thr for d in dwells)})
md = ["# E7: one continuous recording of 15 checks (3 seeds; each look 2-12 s, uniform)", "",
      "| dwell threshold (s) | 'Next run' counted as an action? | decisions found (of 15) | visits whose readouts were found | visits with the right outcome |", "|---|---|---|---|---|"]
for thr in (8.0, 5.0, 3.0, 2.0):
    for nav in (False, True):
        sel = [r for r in rows if r["threshold"] == thr and r["navigation_ignored"] == nav]
        md.append(f"| {thr:g} | {'no (ignored)' if nav else 'yes'} | {st.mean(r['decisions_found'] for r in sel):.1f} | {st.mean(r['visits_with_readouts_found'] for r in sel):.1f} | {st.mean(r['visits_with_right_outcome'] for r in sel):.1f} |")
(OUT / "e7_continuous.md").write_text("\n".join(md) + "\n", encoding="utf-8")
(OUT / "e7_continuous.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print("\n".join(md))
