"""Amendment 3: ratio features (R) against the default (A) on the service domain, seeds 6-10, plus a cost check."""
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import induce, study  # noqa: E402

SEEDS = (6, 7, 8, 9, 10)
OUT = Path(__file__).resolve().parent.parent / "docs" / "results"
doms = study.domains()


def cell(dn, n, noise, ratios):
    return [induce.holdout(study.build(doms[dn], n, s, label_noise=noise, ratios=ratios).decisions)["test_accuracy"] for s in SEEDS]


md = ["| domain | visits | label noise | A (default) | R (+ ratio features) |", "|---|---|---|---|---|"]
gains, cost, rows = [], [], []
every = True
for dn, cells in (("service", [(40, 0.0), (80, 0.0), (60, 0.1)]), ("dashboard", [(40, 0.0), (80, 0.0)]), ("triage", [(40, 0.0), (80, 0.0)])):
    for n, noise in cells:
        a, r = cell(dn, n, noise, False), cell(dn, n, noise, True)
        rows.append({"domain": dn, "n": n, "noise": noise, "A": a, "R": r})
        md.append(f"| {dn} | {n} | {noise} | {st.mean(a):.2f} ({min(a):.2f}-{max(a):.2f}) | {st.mean(r):.2f} ({min(r):.2f}-{max(r):.2f}) |")
        if dn == "service":
            gains.append(st.mean(r) - st.mean(a))
            every &= st.mean(r) >= st.mean(a) - 1e-9
        else:
            cost.append(st.mean(r) - st.mean(a))
svc80 = next(x for x in rows if x["domain"] == "service" and x["n"] == 80)
adopt = every and st.mean(gains) >= 0.10 and st.mean(cost) >= -0.03
verdict = (f"service: R at least A in every cell: {every}; mean gain {st.mean(gains):+.3f} (bar +0.10). Cost check (dashboard, triage): mean change {st.mean(cost):+.3f} (bar -0.03). "
           f"R at 80 visits on service: {st.mean(svc80['R']):.2f} (predicted below 0.90); A: {st.mean(svc80['A']):.2f} (predicted below 0.90). -> R is {'ADOPTED as an option' if adopt else 'NOT adopted'}.")
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
text = f"# Amendment 3: ratio features, seeds {list(SEEDS)} (commit {commit})\n\nHeld-out agreement, mean (min-max).\n\n" + "\n".join(md) + f"\n\n**{verdict}**\n"
(OUT / "confirmatory3.md").write_text(text, encoding="utf-8")
(OUT / "confirmatory3.json").write_text(json.dumps({"commit": commit, "rows": rows, "verdict": verdict}, indent=1), encoding="utf-8")
print(text)
