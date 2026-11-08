"""Confirmatory runs H1-H4 (docs/evaluation-protocol.md, amendment 1). Seeds 1-5 only, code at tag freeze-1.

    python scripts/run_confirmatory.py            # writes docs/results/confirmatory.json and confirmatory.md

No tuning happens here: the grid, seeds, criteria and arms are those of the protocol.
"""

from __future__ import annotations

import json
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook import induce, study  # noqa: E402
from playbook.elicit import key  # noqa: E402

SEEDS = (1, 2, 3, 4, 5)
SIZES = (40, 80)
OUT = Path(__file__).resolve().parent.parent / "docs" / "results"


def one(domain: study.Domain, n: int, seed: int) -> dict:
    built = study.build(domain, n, seed)
    ds = built.decisions
    cut = max(1, int(len(ds) * 0.7))
    row = {"domain": domain.name, "n": n, "seed": seed, "test_size": len(ds) - cut,
           "majority": study.majority_accuracy(ds[:cut], ds[cut:])}
    for arm, la in (("greedy", False), ("lookahead", True)):
        tree = induce.fit(ds, lookahead=la)
        row[f"{arm}_agreement"] = induce.holdout(ds, lookahead=la)["test_accuracy"]
        row[f"{arm}_without_context"] = induce.holdout(ds, without="context", lookahead=la)["test_accuracy"]
        row[f"{arm}_without_none"] = induce.holdout(ds, without="none", lookahead=la)["test_accuracy"]
        row[f"{arm}_recovery"] = sum(induce.predict(tree, d) == built.clean[key(d)] for d in ds) / len(ds)
        row[f"{arm}_rule"] = induce.rules(tree)
    hidden = study.build(domain, 80, seed, hidden_fact=True)
    if n == 80:
        e = study.elicitation(hidden, seed)
        row["h4"] = {k: e[k] for k in ("questions", "answers", "test_before", "test_after", "unexplained_before", "unexplained_after")}
    return row


def table(rows: list[dict], domain: str, n: int, arm: str, label: str) -> str:
    sel = [r for r in rows if r["domain"] == domain and r["n"] == n]
    vals = lambda k: [r[k] for r in sel]  # noqa: E731
    f = lambda k: f"{st.mean(vals(k)):.2f} ({min(vals(k)):.2f}-{max(vals(k)):.2f})"  # noqa: E731
    return (f"| {domain} | {n} | {label} | {f(arm + '_agreement')} | {f(arm + '_without_context')} | "
            f"{f(arm + '_without_none')} | {f('majority')} | {f(arm + '_recovery')} |")


def main() -> int:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    tag = subprocess.run(["git", "describe", "--tags", "--always"], capture_output=True, text=True).stdout.strip()
    doms = study.domains()
    rows = [one(doms[name], n, seed) for name in ("dashboard", "triage") for n in SIZES for seed in SEEDS]
    (OUT / "confirmatory.json").write_text(json.dumps({"commit": commit, "describe": tag, "seeds": SEEDS, "rows": rows}, indent=1), encoding="utf-8")

    md = [f"# Confirmatory runs H1-H4 (seeds {list(SEEDS)}; commit {commit}, `{tag}`)", "",
          "Mean (min-max) over 5 seeds. Held-out = chronological 30% (12 visits at n=40, 24 at n=80).", "",
          "| domain | visits | induction | held-out agreement | without context | without non-actions | majority | recovery of planted rule |",
          "|---|---|---|---|---|---|---|---|"]
    for name in ("dashboard", "triage"):
        for n in SIZES:
            for arm, label in (("greedy", "greedy"), ("lookahead", "lookahead")):
                md.append(table(rows, name, n, arm, label))
    md += ["", "## Verdicts against the protocol (criteria fixed in advance)", ""]
    for name in ("dashboard", "triage"):
        for n in SIZES:
            for arm in ("greedy", "lookahead"):
                sel = [r for r in rows if r["domain"] == name and r["n"] == n]
                a = [r[f"{arm}_agreement"] for r in sel]
                h1 = st.mean(a) >= 0.90 and min(a) >= 0.80
                h2 = st.mean(r[f"{arm}_agreement"] for r in sel) > st.mean(r[f"{arm}_without_context"] for r in sel)
                md.append(f"- {name}, {n} visits, {arm}: **H1 {'holds' if h1 else 'FAILS'}** (mean {st.mean(a):.2f}, min {min(a):.2f}); "
                          f"H2 {'holds' if h2 else 'does not hold'} (context {st.mean(a):.2f} vs without "
                          f"{st.mean(r[f'{arm}_without_context'] for r in sel):.2f}); H3 (descriptive): with non-actions {st.mean(a):.2f}, "
                          f"without {st.mean(r[f'{arm}_without_none'] for r in sel):.2f}.")
    md += ["", "## H4: one elicitation round, simulated expert who always names the hidden fact (80 visits, hidden warmup, greedy)", "",
           "| domain | seed | questions | answers | held-out before | after | unexplained before | after |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "h4" in r:
            h = r["h4"]
            md.append(f"| {r['domain']} | {r['seed']} | {h['questions']} | {h['answers']} | {h['test_before']:.2f} | {h['test_after']:.2f} | "
                      f"{h['unexplained_before']} | {h['unexplained_after']} |")
    for name in ("dashboard", "triage"):
        hs = [r["h4"] for r in rows if r["domain"] == name and "h4" in r]
        better = st.mean(h["test_after"] for h in hs) > st.mean(h["test_before"] for h in hs)
        md.append(f"\n- {name}: H4 **{'holds' if better else 'does not hold'}** (mean {st.mean(h['test_before'] for h in hs):.2f} -> "
                  f"{st.mean(h['test_after'] for h in hs):.2f}).")
    (OUT / "confirmatory.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
