"""Exploratory studies E1-E6 (docs/evaluation-protocol.md, amendment 1). Seeds 1-5, both domains.

    python scripts/run_exploratory.py             # writes docs/results/exploratory.json and exploratory.md

Exploratory: reported as found, not tested against a pre-set criterion.
"""

from __future__ import annotations

import json
import statistics as st
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook import induce, study  # noqa: E402
from playbook.elicit import key  # noqa: E402
from playbook.knowledge import classify_decision  # noqa: E402

SEEDS = (1, 2, 3, 4, 5)
DOMAINS = ("dashboard", "triage")
ARMS = (("greedy", False), ("lookahead", True))
OUT = Path(__file__).resolve().parent.parent / "docs" / "results"


def agreement(ds, la: bool) -> float:
    return induce.holdout(ds, lookahead=la)["test_accuracy"]


def cell(vals) -> str:
    return f"{st.mean(vals):.2f} ({min(vals):.2f}-{max(vals):.2f})"


def sweep(doms, name: str, grid: list, make) -> list[dict]:
    """For every domain and grid value, the held-out agreement of each arm over the seeds."""
    rows = []
    for dn in DOMAINS:
        for g in grid:
            per = defaultdict(list)
            extra = defaultdict(list)
            for seed in SEEDS:
                built = make(doms[dn], g, seed)
                for arm, la in ARMS:
                    per[arm].append(agreement(built.decisions, la))
                if hasattr(built, "flipped") and built.flipped:
                    flagged = {key(d) for d, _ in induce.disagreements(built.decisions)}
                    extra["flag_precision"].append(len(flagged & built.flipped) / len(flagged) if flagged else 1.0)
                    extra["flag_recall"].append(len(flagged & built.flipped) / len(built.flipped))
            rows.append({"study": name, "domain": dn, "value": g, **{a: v for a, v in per.items()}, **{k: v for k, v in extra.items()}})
    return rows


def e1(doms):
    return sweep(doms, "E1 learning curve (visits)", [10, 20, 30, 40, 60, 80, 120], lambda d, g, s: study.build(d, g, s))


def e2(doms):
    return sweep(doms, "E2 label noise", [0.0, 0.05, 0.1, 0.2], lambda d, g, s: study.build(d, 60, s, label_noise=g))


def e3(doms):
    return sweep(doms, "E3 OCR misreads", [0.0, 0.02, 0.05, 0.1], lambda d, g, s: study.build(d, 60, s, misread=g))


def e4a(doms):
    return sweep(doms, "E4a distractor readouts", [0, 2, 4, 8], lambda d, g, s: study.build(d, 60, s, distractors=g))


def e4b(doms):
    """The rule changes at visit 40 of 80. Fit on visits 0-59 or only on 40-59; test on 60-79."""
    rows = []
    for dn in DOMAINS:
        per = defaultdict(list)
        for seed in SEEDS:
            ds = study.build(doms[dn], 80, seed, drift_at=40).decisions
            test = ds[60:]
            for arm, la in ARMS:
                per[f"{arm}: all earlier visits"].append(induce.accuracy(induce.fit(ds[:60], lookahead=la), test))
                per[f"{arm}: only visits after the change"].append(induce.accuracy(induce.fit(ds[40:60], lookahead=la), test))
        rows.append({"study": "E4b rule drift", "domain": dn, "value": "change at visit 40 of 80", **per})
    return rows


def e5(doms):
    rows = []
    for dn in DOMAINS:
        for acc, wrong in ((1.0, False), (0.8, False), (0.6, False), (0.0, False), (0.6, True), (0.0, True)):
            before, after = [], []
            for seed in SEEDS:
                built = study.build(doms[dn], 80, seed, hidden_fact=True)
                e = study.elicitation(built, seed, accuracy=acc, wrong_fact=wrong)
                before.append(e["test_before"])
                after.append(e["test_after"])
            rows.append({"study": "E5 imperfect expert", "domain": dn,
                         "value": f"names the right fact {acc:.0%} of the time" + (", otherwise tags the wrong decisions" if wrong else ", otherwise says nothing useful"),
                         "before": before, "after": after})
    return rows


def e6(doms):
    """knowledge.classify_decision against ground truth, 40 visits, seeds 1-5."""
    out = []
    for dn in DOMAINS:
        conf = Counter()
        for seed in SEEDS:
            domain = doms[dn]
            visits = domain.make_visits(40, seed)
            built = study.build(domain, 40, seed)
            used = induce.features_used(induce.fit(built.decisions))
            for v, d in zip(visits, built.decisions):
                truth = "O5" if domain.depends_on_history(v) else ("O4" if built.clean[key(d)] == "none" else "O3")
                conf[(truth, classify_decision(d, used).observability)] += 1
        out.append({"study": "E6 classifier vs ground truth", "domain": dn, "confusion": {f"{t}->{p}": n for (t, p), n in sorted(conf.items())}})
    return out


def main() -> int:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    doms = study.domains()
    results = {"E1": e1(doms), "E2": e2(doms), "E3": e3(doms), "E4a": e4a(doms), "E4b": e4b(doms), "E5": e5(doms), "E6": e6(doms)}
    (OUT / "exploratory.json").write_text(json.dumps({"commit": commit, "seeds": SEEDS, "results": results}, indent=1), encoding="utf-8")
    md = [f"# Exploratory studies E1-E6 (seeds {list(SEEDS)}; commit {commit})", "",
          "Exploratory: no pre-set pass/fail criterion. Held-out agreement, mean (min-max) over 5 seeds, chronological 70/30 split.", ""]
    for key_ in ("E1", "E2", "E3", "E4a"):
        rows = results[key_]
        md += [f"## {rows[0]['study']}", "", "| domain | value | greedy | lookahead |" + (" flagged are noisy (precision) | noisy flagged (recall) |" if "flag_precision" in rows[0] or key_ == "E2" else ""),
               "|---|---|---|---|" + ("---|---|" if key_ == "E2" else "")]
        for r in rows:
            line = f"| {r['domain']} | {r['value']} | {cell(r['greedy'])} | {cell(r['lookahead'])} |"
            if key_ == "E2":
                line += (f" {cell(r['flag_precision'])} | {cell(r['flag_recall'])} |" if "flag_precision" in r else " - | - |")
            md.append(line)
        md.append("")
    md += ["## E4b rule drift (held-out = the last 20 of 80 visits)", "", "| domain | fitted on | agreement |", "|---|---|---|"]
    for r in results["E4b"]:
        for k, v in r.items():
            if ":" in k:
                md.append(f"| {r['domain']} | {k} | {cell(v)} |")
    md += ["", "## E5 imperfect expert (80 visits, hidden warmup fact, one elicitation round, greedy)", "",
           "| domain | expert | held-out before | after |", "|---|---|---|---|"]
    for r in results["E5"]:
        md.append(f"| {r['domain']} | {r['value']} | {cell(r['before'])} | {cell(r['after'])} |")
    md += ["", "## E6 observability class of each decision vs ground truth (40 visits x 5 seeds)", "",
           "Truth: O5 if the planted outcome depends on an earlier visit, else O4 if the person did nothing, else O3.", ""]
    for r in results["E6"]:
        md.append(f"- {r['domain']}: " + ", ".join(f"{k}: {n}" for k, n in r["confusion"].items()))
    (OUT / "exploratory.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
