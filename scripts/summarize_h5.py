"""Summarise docs/results/h5/results.jsonl into docs/results/h5/h5.md (mean and range over seeds; repeats averaged first)."""
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "docs" / "results" / "h5"
rows = [json.loads(x) for x in (D / "results.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
by = defaultdict(lambda: defaultdict(list))  # (domain, arm) -> seed -> [rows]
for r in rows:
    by[(r["domain"], r["arm"])][r["seed"]].append(r)
arms = ["majority", "rules", "skill", "skill+judgment", "skill+judgment strict"]
md = ["# H5: does the exported judgment help an agent? (Qwen3-VL 4B, text only, 40 visits, 12 held-out per seed, 3 repeats)", "",
      "Agreement with the person's later decisions: mean over seeds 1-5 (min-max of the per-seed repeat means). ask = asked a human; wrong = acted when the person did not; missed = did nothing when the person acted. Sums over seeds and repeats.", "",
      "| domain | arm | agreement | ask a human | wrong actions | missed actions |", "|---|---|---|---|---|---|"]
verdict = {}
for dn in ("dashboard", "triage"):
    for arm in arms:
        seeds = by[(dn, arm)]
        if not seeds:
            continue
        per = [st.mean(r["agreement"] for r in rs) for rs in seeds.values()]
        verdict[(dn, arm)] = st.mean(per)
        tot = lambda k: sum(r[k] for rs in seeds.values() for r in rs)  # noqa: E731
        md.append(f"| {dn} | {arm} | {st.mean(per):.2f} ({min(per):.2f}-{max(per):.2f}) | {tot('ask_human')} | {tot('wrong_actions')} | {tot('missed_actions')} |")
md += ["", "## Verdict against the protocol", ""]
for dn in ("dashboard", "triage"):
    if (dn, "skill") in verdict:
        for arm in ("skill+judgment", "skill+judgment strict"):
            if (dn, arm) in verdict:
                gap = verdict[(dn, arm)] - verdict[(dn, "skill")]
                better = gap > 0.02  # a gap under two points (a quarter of one decision per seed) is a tie
                md.append(f"- {dn}, {arm}: {verdict[(dn, arm)]:.2f} vs procedure only {verdict[(dn, 'skill')]:.2f} -> H5 **{'holds' if better else 'does not hold (no clear gain)'}** for this variant "
                          f"(rules read mechanically: {verdict[(dn, 'rules')]:.2f}).")
(D / "h5.md").write_text("\n".join(md) + "\n", encoding="utf-8")
print("\n".join(md))
