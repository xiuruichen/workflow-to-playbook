"""Amendment 8, H12 and H13: ordering and grouping misfits, and the interview end to end, against the first version.

    python scripts/run_fix_interview.py --order-test                    # H12, no model: which ordering puts the hidden fact first (seeds 11-15)
    python scripts/run_fix_interview.py --dev --arms v0/time/single,gated/time/single,gated/time/group,gated/burst/group
    python scripts/run_fix_interview.py --test --arms v0/time/single,<the arm chosen on development seeds>
    python scripts/run_fix_interview.py --summarize --test --chosen gated/burst/group

An arm is extraction/order/group, for example `gated/surprise/group`; `v0/time/single` is the first version (tag freeze-5).
The scripted expert answers in the paraphrases of results/interview/paraphrases.json: the `dev` set on development seeds
(100-109), the fresh `test` set on seeds 11-15.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI  # noqa: E402
from run_interview import make_chat  # noqa: E402

from playbook import elicit, interview, llama_runtime as lr, study  # noqa: E402
from playbook.config import get_settings  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"
OUT = RESULTS / "interview"
TEST_SEEDS, DEV_SEEDS = (11, 12, 13, 14, 15), tuple(range(100, 110))


def expert_for(built: study.Built, seed: int, phrases: str) -> study.FreeTextExpert:
    p = json.loads((OUT / "paraphrases.json").read_text(encoding="utf-8"))[phrases]
    return study.FreeTextExpert(built.hidden, seed, clear=p["clear"], vague=p["vague"], irrelevant=p["irrelevant"])


def order_test(doms) -> str:
    """H12 (no model): the share of the first four asked misfits that were made during the hidden warmup, by ordering."""
    res = {o: {"dashboard": [], "triage": []} for o in ("time", "surprise", "burst", "cluster")}
    for dn in ("dashboard", "triage"):
        for seed in TEST_SEEDS:
            built = study.build(doms[dn], 80, seed, hidden_fact=True)
            train = built.decisions[:56]
            qs = elicit.build_questions(train)
            if len(qs) < 4:
                continue
            for o in res:
                first = interview.rank_misfits(train, qs, o)[:4]
                res[o][dn].append(sum(elicit.key(q.decision) in built.hidden for q in first) / 4)
    lines = ["# Amendment 8, H12: which misfits to ask first (seeds 11-15, 80 visits, no model)", "",
             "Share of the first four asked misfits that were made during the hidden warmup, mean over seeds.", "",
             "| order | dashboard | triage | mean |", "|---|---|---|---|"]
    means = {}
    for o, by in res.items():
        d, t = st.fmean(by["dashboard"]), st.fmean(by["triage"])
        means[o] = (d + t) / 2
        lines.append(f"| {o} | {d:.2f} | {t:.2f} | {means[o]:.2f} |")
    best = max(("surprise", "burst", "cluster"), key=lambda o: means[o])
    lines += ["", f"**H12 (at least +0.15 over time order): best is `{best}` at {means[best]:.2f} against {means['time']:.2f} "
                  f"({means[best] - means['time']:+.2f}) -> {'holds' if means[best] - means['time'] >= 0.15 else 'FAILS'}.**"]
    return "\n".join(lines) + "\n"


def summarize(rows: list[dict], chosen: str | None, kind: str) -> str:
    arms = sorted({r["arm"] for r in rows})
    lines = [f"# Amendment 8, interview end to end, {kind} seeds", "",
             "| arm (extraction/order/group) | interviews | gain | structured gain | share of structured gain | interviews that named a fact | questions |", "|---|---|---|---|---|---|---|"]
    stats = {}
    for arm in arms:
        sel = [r for r in rows if r["arm"] == arm]
        g, sg = st.fmean(r["gain"] for r in sel), st.fmean(r["structured_gain"] for r in sel)
        stats[arm] = (g, sg)
        lines.append(f"| {arm} | {len(sel)} | {g:+.3f} | {sg:+.3f} | {(g / sg if sg > 0 else float('nan')):.0%} | {sum(bool(r['facts']) for r in sel)} | {st.fmean(r['questions'] for r in sel):.1f} |")
    for dn in sorted({r["domain"] for r in rows}):
        lines += ["", f"{dn}: " + "; ".join(f"{arm} {st.fmean(r['gain'] for r in rows if r['arm'] == arm and r['domain'] == dn):+.3f}" for arm in arms)]
    if kind == "test" and chosen and chosen in stats:
        g, sg = stats[chosen]
        lines += ["", f"**H13 (`{chosen}`: gain at least 70% of the structured gain): {g:+.3f} against {sg:+.3f} = {(g / sg if sg > 0 else float('nan')):.0%} -> "
                      f"{'holds' if sg > 0 and g / sg >= 0.7 else 'FAILS'}.**"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order-test", action="store_true")
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--arms", default="v0/time/single")
    ap.add_argument("--chosen", default=None)
    ap.add_argument("--domains", default="dashboard,triage")
    ap.add_argument("--n-dev-seeds", type=int, default=5)
    a = ap.parse_args()
    doms = study.domains()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    if a.order_test:
        text = order_test(doms) + f"\nCode at commit {commit}.\n"
        (RESULTS / "fix_order.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    kind = "test" if a.test else "dev"
    path = OUT / f"fix_interview_{kind}.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if a.summarize:
        text = summarize(rows, a.chosen, kind) + f"\nCode at commit {commit}.\n"
        (RESULTS / f"fix_interview_{kind}.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    seeds = TEST_SEEDS if a.test else DEV_SEEDS[: a.n_dev_seeds]
    done = {(r["domain"], r["seed"], r["arm"]) for r in rows}
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)
    chat = make_chat(client)
    with lr.serving(s, info, status=print):
        for arm in a.arms.split(","):
            extraction, order, group = arm.split("/")
            for dn in a.domains.split(","):
                for seed in seeds:
                    if (dn, seed, arm) in done:
                        continue
                    built = study.build(doms[dn], 80, seed, hidden_fact=True)
                    expert = expert_for(built, seed, kind)
                    out = study.interview_experiment(doms[dn], seed, chat, "v0_open", expert=expert, extraction=extraction, order=order, group_first=group == "group")
                    out["arm"], out["expert"] = arm, "free"
                    with path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(out) + "\n")
                    print(f"{arm:24} {dn:9} seed {seed}: gain {out['gain']:+.3f} (structured {out['structured_gain']:+.3f}), {out['questions']} questions, facts {out['facts']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
