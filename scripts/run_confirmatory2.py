"""Amendment 2: variant C (lookahead, min_leaf 3) against the default A (greedy, min_leaf 2) on fresh seeds 6-10."""
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import induce, study  # noqa: E402

SEEDS = (6, 7, 8, 9, 10)
CELLS = [(40, 0.0), (80, 0.0), (60, 0.1)]
OUT = Path(__file__).resolve().parent.parent / "docs" / "results"
VARIANTS = {"A greedy leaf2": {}, "C lookahead leaf3": {"lookahead": True, "min_leaf": 3}}

doms = study.domains()
rows, md = [], ["| domain | visits | label noise | " + " | ".join(VARIANTS) + " |", "|---|---|---|---|---|"]
cell_means = {v: [] for v in VARIANTS}
for dn in ("dashboard", "triage"):
    for n, noise in CELLS:
        res = {}
        for v, kw in VARIANTS.items():
            per = [induce.holdout(study.build(doms[dn], n, s, label_noise=noise).decisions, **kw)["test_accuracy"] for s in SEEDS]
            res[v] = per
            cell_means[v].append(st.mean(per))
            rows.append({"domain": dn, "n": n, "noise": noise, "variant": v, "per_seed": per})
        md.append(f"| {dn} | {n} | {noise} | " + " | ".join(f"{st.mean(res[v]):.2f} ({min(res[v]):.2f}-{max(res[v]):.2f})" for v in VARIANTS) + " |")
a, c = cell_means["A greedy leaf2"], cell_means["C lookahead leaf3"]
every = all(x >= y - 1e-9 for x, y in zip(c, a))
gain = st.mean(c) - st.mean(a)
verdict = f"C at least A in every cell: {every}; mean gain {gain:+.3f} -> C is {'ADOPTED' if every and gain >= 0.05 else 'NOT adopted'} as the default."
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
text = f"# Amendment 2: variant C vs default A, seeds {list(SEEDS)} (commit {commit})\n\nHeld-out agreement, mean (min-max) over seeds.\n\n" + "\n".join(md) + f"\n\n**{verdict}**\n"
(OUT / "confirmatory2.md").write_text(text, encoding="utf-8")
(OUT / "confirmatory2.json").write_text(json.dumps({"commit": commit, "rows": rows, "verdict": verdict}, indent=1), encoding="utf-8")
print(text)
