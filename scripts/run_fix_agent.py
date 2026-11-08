"""Amendment 10, H19: does giving the agent an executable evaluator fix the 4B model's weak use of the rules?

    python scripts/run_fix_agent.py --smoke       # one seed, one repeat, development seed 100
    python scripts/run_fix_agent.py               # test seeds 11-15, three domains, 3 repeats (resumable)
    python scripts/run_fix_agent.py --summarize   # verdict against the bar, written to docs/results/fix_agent.md

Arms: majority and rules (no model), "skill" (the model sees only the procedure), "skill+judgment" (the rules as text, as in
H5), and the new "skill+evaluator": the model reads the screen text into readouts, a tool applies the exported rules
(`replay.judge`, the same function `python -m playbook judge` runs), and the model gives the final choice, asking a human
when the tool says to.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from playbook import llama_runtime as lr  # noqa: E402
from playbook import replay, study  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.decisions import NONE  # noqa: E402
from playbook.skill import build_judgment  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"
OUT = RESULTS / "fix_agent"
TEST_SEEDS = (11, 12, 13, 14, 15)
PROCEDURE = {"service": "Check the service after deploys and decide whether to roll back, page on-call or leave it.",
             "dashboard": "Check a training run and decide whether to stop it.",
             "triage": "Review the top overdue invoice and decide what to do."}
ARMS = ["majority", "rules", "skill", "skill+judgment", "skill+evaluator", "skill+evaluator (code parses)"]


def parse_names(judgment: dict) -> tuple[list[str], list[str]]:
    """The readout and category names the rules need: those in the observed ranges, those behind changed_/delta_/ratio conditions."""
    nums = set(judgment["basis"]["observed_ranges"])
    cats = set()
    for rule in judgment["rules"]:
        for c in rule["when"]:
            f = c.split()[0]
            if f.startswith(("changed_", "delta_")):
                nums.add(f.split("_", 1)[1])
            elif "/" in f:
                nums.update(f.split("/"))
            elif "=" in f:
                cats.add(f.split("=")[0])
            elif f != "always":
                nums.add(f)
    return sorted(nums), sorted(cats)


def evaluator_decider(chat, skill_md: str, options: list[str], judgment: dict, previous: dict, stats: dict, parse: str = "model"):
    nums, cats = parse_names(judgment)
    props = {n: {"type": "number"} for n in nums} | {c: {"type": "string"} for c in cats}
    parse_fmt = {"type": "json_schema", "json_schema": {"name": "readouts", "schema": {"type": "object", "properties": props, "required": []}}}
    choices = [*options, replay.ASK]
    final_fmt = {"type": "json_schema", "json_schema": {"name": "choice", "schema": {"type": "object", "properties": {"choice": {"type": "string", "enum": choices}}, "required": ["choice"]}}}

    def decide(d):
        screen = replay._screen(d, [], [])
        if parse == "code":  # post hoc: the screen text is read by the decision log's own OCR parser, not by the model
            from playbook.decisions import parse_categories, parse_readouts

            pieces = [p.strip() for p in screen.split("shows:", 1)[-1].split(".")[0].split(",")] if "shows:" in screen else []
            got = {}
            for piece in pieces:
                got.update({k: v for k, v in parse_readouts([piece]).items() if k in nums})
                got.update({k: v for k, v in parse_categories([piece]).items() if k in cats})
        else:
            try:
                got = json.loads(chat([{"role": "system", "content": "Copy the values from the screen text into JSON, using exactly these names: "
                                        + ", ".join(nums + cats) + ". Numbers as numbers, words in lower case."}, {"role": "user", "content": screen}], parse_fmt))
            except Exception:
                got = {}
        readouts = {k: float(v) for k, v in got.items() if k in nums and isinstance(v, (int, float))}
        words = {k: str(v).lower() for k, v in got.items() if k in cats}
        stats["readouts_total"] += len(d.readouts)
        stats["readouts_right"] += sum(readouts.get(k) == v for k, v in d.readouts.items() if k in nums)
        tool = replay.judge(judgment, readouts, words, previous.get(id(d)))
        msgs = [{"role": "system", "content": "You act for a person using the skill below. The judge tool has applied the skill's rules to the screen; "
                 "follow its answer exactly, and choose to ask a human whenever it says so.\n\n" + skill_md},
                {"role": "user", "content": f"{screen}\nThe judge tool returned: {json.dumps(tool)}\nOptions: {', '.join(choices)}. ('{NONE}' means take no action.) Reply as JSON: {{\"choice\": ...}}"}]
        try:
            pick = json.loads(chat(msgs, final_fmt)).get("choice", replay.ASK)
        except (ValueError, AttributeError):
            return replay.ASK
        return pick if pick in choices else replay.ASK

    return decide


def summarize(rows: list[dict]) -> str:
    lines = ["# Amendment 10, H19: an executable judgment for the agent (Qwen3-VL 4B, text only, seeds 11-15, 40 visits, 3 repeats)", "",
             "Agreement with the person's later decisions: mean over seeds (min-max of the per-seed repeat means).", "",
             "| domain | arm | agreement | ask a human | wrong actions | missed actions |", "|---|---|---|---|---|---|"]
    mean = {}
    for dn in ("dashboard", "triage", "service"):
        for arm in ARMS:
            sel = [r for r in rows if r["domain"] == dn and r["arm"] == arm]
            if not sel:
                continue
            per = [st.fmean(r["agreement"] for r in sel if r["seed"] == s) for s in sorted({r["seed"] for r in sel})]
            mean[(dn, arm)] = st.fmean(per)
            lines.append(f"| {dn} | {arm} | {st.fmean(per):.2f} ({min(per):.2f}-{max(per):.2f}) | {sum(r['ask_human'] for r in sel)} | {sum(r['wrong_actions'] for r in sel)} | {sum(r['missed_actions'] for r in sel)} |")
    for arm, what in (("skill+evaluator", "the model copied"), ("skill+evaluator (code parses)", "the parser read")):
        ev = [r for r in rows if r["arm"] == arm and r.get("readouts_total")]
        if ev:
            lines += ["", f"Readouts {what} correctly from the screen text ({arm}): {sum(r['readouts_right'] for r in ev)}/{sum(r['readouts_total'] for r in ev)}."]
    lines += ["", "## Verdict against the bar (evaluator arm within 0.05 of the mechanical reader and at least 0.10 above procedure only)", ""]
    for dn in ("dashboard", "triage", "service"):
        if all(k in mean for k in ((dn, "skill+evaluator"), (dn, "rules"), (dn, "skill"))):
            e, r, p = mean[(dn, "skill+evaluator")], mean[(dn, "rules")], mean[(dn, "skill")]
            ok = r - e <= 0.05 and e - p >= 0.10
            lines.append(f"- {dn}: evaluator {e:.2f}, mechanical {r:.2f} (gap {r - e:+.2f}), procedure only {p:.2f} (gain {e - p:+.2f}) -> **{'holds' if ok else 'FAILS'}**")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("smoke.jsonl" if a.smoke else "results.jsonl")
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if a.summarize:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        text = summarize(rows) + f"\nCode at commit {commit}.\n"
        (RESULTS / "fix_agent.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    done = {(r["domain"], r["seed"], r["repeat"], r["arm"]) for r in rows}
    seeds = (100,) if a.smoke else TEST_SEEDS
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)
    doms = study.domains()
    with lr.serving(s, info, status=print):
        for dn in ("dashboard", "triage", "service"):
            for seed in seeds:
                decisions = study.build(doms[dn], 40, seed, ratios=dn == "service").decisions
                train, test = replay.split(decisions)
                judgment = build_judgment(train, None)
                options = sorted({d.outcome for d in train if d.outcome != NONE} | {NONE})
                context = sorted({c.split()[0] for r in judgment["rules"] for c in r["when"] if c.startswith(("changed_", "delta_")) or "/" in c.split()[0]})
                with_j = PROCEDURE[dn] + "\n\n" + replay._judgment_text(judgment)
                previous = {id(d): decisions[i - 1].readouts for i, d in enumerate(decisions) if i > 0}
                for rep in range(1 if a.smoke else a.repeats):
                    def chat(messages, fmt, _rep=rep, _seed=seed):
                        r = client.chat.completions.create(model="qwen3-vl-4b", messages=messages, temperature=0.3, seed=1000 * _seed + _rep, response_format=fmt, max_tokens=120)
                        return r.choices[0].message.content or ""

                    stats = {"readouts_total": 0, "readouts_right": 0}
                    stats_code = {"readouts_total": 0, "readouts_right": 0}
                    deciders = {"majority": replay.majority_decider(train), "rules": replay.rules_decider(judgment),
                                "skill": replay.model_decider(chat, PROCEDURE[dn], options),
                                "skill+judgment": replay.model_decider(chat, with_j, options, [], context),
                                "skill+evaluator": evaluator_decider(chat, with_j, options, judgment, previous, stats),
                                "skill+evaluator (code parses)": evaluator_decider(chat, with_j, options, judgment, previous, stats_code, "code")}
                    for arm, decide in deciders.items():
                        if (dn, seed, rep, arm) in done:
                            continue
                        t0 = time.time()
                        res = replay.score(decide, test)
                        row = {"domain": dn, "seed": seed, "repeat": rep, "arm": arm, "seconds": round(time.time() - t0, 1), **res}
                        if arm.startswith("skill+evaluator"):
                            row.update(stats if arm == "skill+evaluator" else stats_code)
                        with path.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(row) + "\n")
                        print(f"{dn} seed {seed} rep {rep} {arm:16} agree {res['agreement']:.2f} ask {res['ask_human']} wrong {res['wrong_actions']} missed {res['missed_actions']} ({row['seconds']}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
