"""H5: does the exported judgment help an agent? (docs/evaluation-protocol.md, amendment 1)

Seeds 1-5 x both domains x R repeats. Arms: majority and rules (no model), the model given only the procedure
("skill"), the model given the procedure plus the judgment section ("skill+judgment", prompt variant A) and the
same with the one-sentence strict instruction ("skill+judgment strict", variant B). Local Qwen3-VL 4B (text only).

    python scripts/run_h5.py --smoke        # one seed, one repeat: measures speed
    python scripts/run_h5.py                # the full run; resumes from docs/results/h5/calls.jsonl

Every (domain, seed, repeat, arm) result is appended to docs/results/h5/results.jsonl as it finishes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from playbook import llama_runtime as lr  # noqa: E402
from playbook import replay, study  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.decisions import NONE, slug  # noqa: E402
from playbook.skill import build_judgment  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "results" / "h5"
SEEDS = (1, 2, 3, 4, 5)
PROCEDURE = {"service": "Check the service after deploys and decide whether to roll back, page on-call or leave it.",
             "dashboard": "Check a training run and decide whether to stop it.",
             "triage": "Review the top overdue invoice and decide what to do."}
TEMPERATURE = 0.3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--visits", type=int, default=40)
    ap.add_argument("--domains", default="dashboard,triage")
    ap.add_argument("--ratios", action="store_true", help="add ratio features (amendment 3) so rules may use errors/requests")
    ap.add_argument("--results", default=None, help="results file name inside docs/results/h5 (default results.jsonl)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")  # already downloaded: only verifies
    model_file = Path(info["model"])
    digest = hashlib.sha256(model_file.read_bytes()[:1 << 24]).hexdigest()[:16]  # first 16 MB: identifies the file cheaply
    meta = {"model": model_file.name, "sha256_first16MB": digest, "temperature": TEMPERATURE, "visits": a.visits,
            "repeats": 1 if a.smoke else a.repeats, "num_ctx": info["num_ctx"], "strict_sentence": replay.STRICT}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    done_path = OUT / ("smoke.jsonl" if a.smoke else (a.results or "results.jsonl"))
    done = set()
    if done_path.exists():
        for line in done_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["domain"], r["seed"], r["repeat"], r["arm"]))
    doms = study.domains()
    seeds = SEEDS[:1] if a.smoke else SEEDS
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)

    with lr.serving(s, info, status=print):
        for dn in a.domains.split(","):
            for seed in seeds:
                decisions = study.build(doms[dn], a.visits, seed, ratios=a.ratios).decisions
                train, test = replay.split(decisions)
                judgment = build_judgment(train, None)
                options = sorted({d.outcome for d in train if d.outcome != NONE} | {NONE})
                context = sorted({c.split()[0] for r in judgment["rules"] for c in r["when"] if c.startswith(("changed_", "delta_")) or "/" in c.split()[0]})
                with_j = PROCEDURE[dn] + "\n\n" + replay._judgment_text(judgment)
                for rep in range(meta["repeats"]):
                    def chat(messages, fmt, _rep=rep, _seed=seed):
                        r = client.chat.completions.create(model="qwen3-vl-4b", messages=messages, temperature=TEMPERATURE,
                                                           seed=1000 * _seed + _rep, response_format=fmt, max_tokens=40)
                        return r.choices[0].message.content or ""

                    arms = {"majority": replay.majority_decider(train), "rules": replay.rules_decider(judgment),
                            "skill": replay.model_decider(chat, PROCEDURE[dn], options),
                            "skill+judgment": replay.model_decider(chat, with_j, options, [], context),
                            "skill+judgment strict": replay.model_decider(chat, with_j, options, [], context, strict=True)}
                    for arm, decide in arms.items():
                        if (dn, seed, rep, arm) in done:
                            continue
                        t0 = time.time()
                        res = replay.score(decide, test)
                        row = {"domain": dn, "seed": seed, "repeat": rep, "arm": arm, "seconds": round(time.time() - t0, 1), **res}
                        with done_path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(row) + "\n")
                        print(f"{dn} seed {seed} rep {rep} {arm:<22} agree {res['agreement']:.2f} ask {res['ask_human']} "
                              f"wrong {res['wrong_actions']} missed {res['missed_actions']} ({row['seconds']}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
