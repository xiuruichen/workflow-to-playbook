"""Amendment 4: the elicitation guard (elicit.vet) against no guard, fresh seeds 6-10."""
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import study  # noqa: E402

SEEDS = (6, 7, 8, 9, 10)
OUT = Path(__file__).resolve().parent.parent / "docs" / "results"
CELLS = {"(a) perfect expert": (1.0, False), "(b) right 60%, otherwise tags wrong decisions": (0.6, True), "(c) always tags wrong decisions": (0.0, True)}
doms = study.domains()
md = ["| domain | expert | before | after, no guard | after, guard |", "|---|---|---|---|---|"]
agg = {k: {"plain": [], "guard": []} for k in CELLS}
rows = []
for dn in ("dashboard", "triage"):
    for label, (acc, wrong) in CELLS.items():
        b, p, g = [], [], []
        for s in SEEDS:
            built = study.build(doms[dn], 80, s, hidden_fact=True)
            x = study.elicitation(built, s, accuracy=acc, wrong_fact=wrong)
            y = study.elicitation(built, s, accuracy=acc, wrong_fact=wrong, guard=True)
            b.append(x["test_before"]); p.append(x["test_after"]); g.append(y["test_after"])
        agg[label]["plain"].append(st.mean(p)); agg[label]["guard"].append(st.mean(g))
        rows.append({"domain": dn, "expert": label, "before": b, "plain": p, "guard": g})
        md.append(f"| {dn} | {label} | {st.mean(b):.3f} | {st.mean(p):.3f} | {st.mean(g):.3f} |")
a_diff = st.mean(agg["(a) perfect expert"]["guard"]) - st.mean(agg["(a) perfect expert"]["plain"])
bc = [st.mean(agg[k]["guard"]) - st.mean(agg[k]["plain"]) for k in list(CELLS)[1:]]
adopt = a_diff >= -0.01 and st.mean(bc) >= 0.01
verdict = f"perfect expert: guard minus no guard {a_diff:+.3f} (bar: not below -0.01); wrong-tag cells: {st.mean(bc):+.3f} (bar: at least +0.01) -> guard is {'ADOPTED' if adopt else 'NOT adopted'}."
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
text = f"# Amendment 4: elicitation guard, seeds {list(SEEDS)} (commit {commit})\n\nHeld-out agreement after one round, mean over seeds.\n\n" + "\n".join(md) + f"\n\n**{verdict}**\n"
(OUT / "confirmatory4.md").write_text(text, encoding="utf-8")
(OUT / "confirmatory4.json").write_text(json.dumps({"commit": commit, "rows": rows, "verdict": verdict}, indent=1), encoding="utf-8")
print(text)
