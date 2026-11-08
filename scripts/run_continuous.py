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
from playbook.scenarios import simulate  # noqa: E402

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
    for thr in (8.0, 5.0, 3.0, 2.0):
        for nav in ((), ("Next run",)):
            found = build_decisions(session, dwell_min_s=thr, navigation=nav)
            # a decision is found if one of its pauses starts within the look of a visit; match by order of readouts
            truth = [(v.spikes, v.batch_size, v.stop) for v in visits]
            ok_reads = sum(any(d.readouts.get("spikes") == t[0] and d.readouts.get("batch_size") == t[1] for d in found) for t in truth)
            correct_out = sum(any(d.readouts.get("spikes") == t[0] and d.readouts.get("batch_size") == t[1] and ((d.outcome != NONE) == t[2]) for d in found) for t in truth)
            rows.append({"seed": seed, "threshold": thr, "navigation_ignored": bool(nav), "visits": N, "decisions_found": len(found),
                         "visits_with_readouts_found": ok_reads, "visits_with_right_outcome": correct_out,
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
