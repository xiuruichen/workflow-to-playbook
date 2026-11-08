"""Amendment 9 (and its addendum): automatic selection, stable misfits, window choice for drift, thin support. No model needed.

    python scripts/run_fix_induction.py            # seeds 11-15 and the untouched smoke-test recording; writes docs/results/fix_induction.md
"""

from __future__ import annotations

import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook import elicit, induce, pilot, study  # noqa: E402
from playbook.decisions import add_context, add_ratios, load_decisions  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"
SEEDS = (11, 12, 13, 14, 15)
doms = study.domains()


def cell(name: str, n: int):
    plain, ratios, auto = [], [], []
    for s in SEEDS:
        ds = study.build(doms[name], n, s).decisions
        cut = int(len(ds) * 0.7)
        train, test = ds[:cut], ds[cut:]
        plain.append(induce.accuracy(induce.fit(train), test))
        rs = study.build(doms[name], n, s, ratios=True).decisions
        ratios.append(induce.accuracy(induce.fit(rs[:cut]), rs[cut:]))
        auto.append(induce.fit_auto(train).accuracy(test))
    return plain, ratios, auto


def fmt(v):
    return f"{st.fmean(v):.3f} (worst {min(v):.2f})"


lines = ["# Amendment 9: induction, test seeds 11-15", "", "## H14: automatic selection (held-out agreement, mean over seeds)", "",
         "| domain | visits | plain tree (baseline) | plain tree + ratios | `fit_auto` |", "|---|---|---|---|---|"]
res = {}
for name in ("dashboard", "triage", "service"):
    for n in (40, 80):
        res[(name, n)] = cell(name, n)
        p, r, a = res[(name, n)]
        lines.append(f"| {name} | {n} | {fmt(p)} | {fmt(r)} | {fmt(a)} |")
t40 = res[("triage", 40)][2]
ok_t40 = st.fmean(t40) >= 0.90 and min(t40) >= 0.75
cost = [st.fmean(res[k][2]) - st.fmean(res[k][0]) for k in (("dashboard", 40), ("dashboard", 80), ("triage", 80))]
ok_cost = all(c >= -0.01 for c in cost)
svc = [st.fmean(res[("service", n)][2]) - st.fmean(res[("service", n)][1]) for n in (40, 80)]
ok_svc = all(c >= -0.02 for c in svc)
lines += ["", f"- triage at 40 visits: mean {st.fmean(t40):.3f}, worst {min(t40):.2f} (bar: mean >= 0.90 and worst >= 0.75): **{'holds' if ok_t40 else 'FAILS'}**",
          f"- no loss against the plain tree on dashboard 40 and 80 and triage 80 (bar: not more than 0.01 below): changes {', '.join(f'{c:+.3f}' for c in cost)}: **{'holds' if ok_cost else 'FAILS'}**",
          f"- service within 0.02 of the plain tree with ratios at 40 and 80 visits: changes {', '.join(f'{c:+.3f}' for c in svc)}: **{'holds' if ok_svc else 'FAILS'}**"]

smoke = add_context(load_decisions(RESULTS / "smoke_test" / "session" / "decisions.jsonl"))
auto = induce.fit_auto(smoke)
used_ratio = any("train_loss/val_loss" in line for line in auto.rules())
lines += ["", "## H15: untouched real-ish data (the smoke-test recording, no flags)", "", f"Chosen: {auto.choice}; cross-validated: {auto.cv}", ""]
lines += [f"    {r}" for r in auto.rules()]
lines += ["", f"**H15 (the rule uses `train_loss/val_loss`): {'holds' if used_ratio else 'FAILS'}.**"]

lines += ["", "## H16: stable misfits (triage, 80 visits, 10% label noise): share of flagged choices that were the noisy ones", "", "| method | precision | recall | flagged |", "|---|---|---|---|"]
stats = {}
for label, fn in (("one leave-one-out fit (baseline)", induce.disagreements), ("stable, threshold 0.7", lambda ds: induce.stable_disagreements(ds, threshold=0.7)),
                  ("stable, threshold 0.8 (the one judged)", lambda ds: induce.stable_disagreements(ds, threshold=0.8))):
    P, R, F = [], [], []
    for s in SEEDS:
        b = study.build(doms["triage"], 80, s, label_noise=0.1)
        flagged = {elicit.key(d) for d, _ in fn(b.decisions)}
        if flagged:
            P.append(len(flagged & b.flipped) / len(flagged))
        R.append(len(flagged & b.flipped) / max(1, len(b.flipped)))
        F.append(len(flagged))
    stats[label] = st.fmean(P) if P else float("nan")
    lines.append(f"| {label} | {stats[label]:.2f} | {st.fmean(R):.2f} | {st.fmean(F):.1f} |")
p8 = stats["stable, threshold 0.8 (the one judged)"]
lines += ["", f"**H16 (precision at threshold 0.8 >= 0.70): {p8:.2f} -> {'holds' if p8 >= 0.70 else 'FAILS'}.**"]

lines += ["", "## H17: drift at visit 40 of 80, tested on the last 20", "", "| domain | full history | last 20 only | window chosen by cross-validation | bar (better fixed window - 0.02) |", "|---|---|---|---|---|"]
ok17 = True
for dn in ("dashboard", "triage"):
    full, recent, win = [], [], []
    for s in SEEDS:
        ds = study.build(doms[dn], 80, s, drift_at=40).decisions
        train, test = ds[:60], ds[60:]
        full.append(induce.accuracy(induce.fit(train), test))
        recent.append(induce.accuracy(induce.fit(train[40:]), test))
        win.append(induce.accuracy(induce.fit_windowed(train)[0], test))
    bar = max(st.fmean(full), st.fmean(recent)) - 0.02
    ok17 &= st.fmean(win) >= bar
    lines.append(f"| {dn} | {st.fmean(full):.3f} | {st.fmean(recent):.3f} | {st.fmean(win):.3f} | {bar:.3f} |")
lines += ["", f"**H17: {'holds' if ok17 else 'FAILS'}.**"]

report = pilot.report(smoke, {"stated_rule": "", "cases": []})
thin = "gpu_util" in report.split("What these choices have in common")[-1] if "What these choices have in common" in report else False
lines += ["", "## H18: thin support (the smoke-test recording)", "", report[report.find("## The"):][:1500], "",
          f"**H18 (the report's hint about the unexplained choices involves `gpu_util`): {'holds' if thin else 'FAILS'}.**"]
commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
text = "\n".join(lines) + f"\n\nCode at commit {commit}.\n"
(RESULTS / "fix_induction.md").write_text(text, encoding="utf-8")
print(text)
