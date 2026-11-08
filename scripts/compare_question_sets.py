"""Compare question strategies on the same simulated experts and decisions, side by side.

    python scripts/compare_question_sets.py                                   # the v0 strategies and the fixed template, seeds 100-104
    python scripts/compare_question_sets.py --strategies v0_open,my_new_one   # a strategy you added to playbook/interview_prompts.py
    python scripts/compare_question_sets.py --expert llm --seeds 100,101      # an LLM persona whose answers depend on the wording

To try a new way of asking, add an entry to STRATEGIES in `playbook/interview_prompts.py`; nothing else changes. Uses
development seeds by default: the pre-registered test seeds (6-10) are for the final run only (docs/evaluation-protocol.md).
Needs the local 4B model (`python docs/results/fetch_model.py`); it is started and stopped by this script.
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI  # noqa: E402
from run_interview import llm_expert, make_chat  # noqa: E402

from playbook import llama_runtime as lr  # noqa: E402
from playbook import study  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.interview_prompts import STRATEGIES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default="template," + ",".join(STRATEGIES))
    ap.add_argument("--expert", default="free", choices=["free", "llm"])
    ap.add_argument("--seeds", default="100,101,102,103,104")
    ap.add_argument("--domains", default="dashboard,triage")
    a = ap.parse_args()
    seeds = [int(x) for x in a.seeds.split(",")]
    doms = study.domains()
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)
    chat = make_chat(client)
    rows = {}
    with lr.serving(s, info, status=print):
        for strategy in a.strategies.split(","):
            res = []
            for dn in a.domains.split(","):
                for seed in seeds:
                    built = study.build(doms[dn], 80, seed, hidden_fact=True)
                    expert = llm_expert(client, built.hidden) if a.expert == "llm" else None
                    out = study.interview_experiment(doms[dn], seed, chat, strategy, expert=expert)
                    res.append(out)
                    print(f"  {strategy:<18} {dn:<9} seed {seed}: gain {out['gain']:+.3f}, {out['questions']} questions", flush=True)
            rows[strategy] = res
    print(f"\nExpert: {a.expert}; seeds {seeds}; domains {a.domains}\n")
    print(f"{'strategy':<20}{'gain':>8}{'structured':>12}{'questions':>11}{'named a condition':>19}{'matches hidden fact':>21}{'mean self-rating':>18}")
    for strategy, res in rows.items():
        turns = [t for r in res for t in r["turns"]]
        named = [t for t in turns if t["condition"]]
        ratings = [t["rating"] for t in turns if t["rating"] is not None]
        print(f"{strategy:<20}{st.fmean(r['gain'] for r in res):>+8.3f}{st.fmean(r['structured_gain'] for r in res):>+12.3f}"
              f"{st.fmean(r['questions'] for r in res):>11.1f}{len(named):>10}/{len(turns):<8}"
              f"{sum(study.matches_hidden(t['condition']) for t in named):>13}/{len(named):<7}"
              f"{(st.fmean(ratings) if ratings else float('nan')):>18.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
