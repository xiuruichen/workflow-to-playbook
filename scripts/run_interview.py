"""Run the LLM-driven interview against the local Qwen3-VL 4B (docs/evaluation-protocol.md, amendment 7).

    python scripts/run_interview.py --dev                  # development seeds 100-109: the only place prompts may be tuned
    python scripts/run_interview.py --smoke                # development seed 100 only; prints every question and answer
    python scripts/run_interview.py                        # test seeds 6-10, both domains (resumable)
    python scripts/run_interview.py --expert llm --strategy template,v0_open    # exploratory: question quality
    python scripts/run_interview.py --summarize            # verdicts against the bars, written to docs/results/interview.md

Each (domain, seed, strategy, expert) result is appended to docs/results/interview/<file>.jsonl as it finishes.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from playbook import elicit, interview, llama_runtime as lr, study  # noqa: E402
from playbook.config import get_settings  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"
OUT = RESULTS / "interview"
TEST_SEEDS, DEV_SEEDS = (6, 7, 8, 9, 10), tuple(range(100, 110))
PERSONA = ("You are an ML engineer. You never stop a training run during its first hours after a restart (its warmup); "
           "at other times you use your usual judgment. You are being interviewed about one check you made. Answer in one "
           "or two sentences, in your own words, and only what the question asks. Do not mention that you are following a rule.")


def make_chat(client, temperature: float = 0.2):
    def chat(messages, fmt):
        r = client.chat.completions.create(model="qwen3-vl-4b", messages=messages, temperature=temperature, seed=7,
                                           response_format=fmt, max_tokens=140)
        return r.choices[0].message.content or ""
    return chat


def llm_expert(client, hidden: set[str]):
    """The 4B as the person: told the hidden rule, answers in its own words, so the wording of the question matters."""
    scripted = study.FreeTextExpert(hidden, 0, vague_rate=0.0)
    log: list[dict] = []

    def ask(text: str, ctx: dict) -> str:
        if ctx.get("followup"):
            return scripted(text, ctx)
        situation = ("In this case the run was in the first hours after a restart." if ctx["key"] in hidden
                     else "In this case the run had not been restarted recently.")
        r = client.chat.completions.create(model="qwen3-vl-4b", temperature=0.3, seed=11, max_tokens=90, messages=[
            {"role": "system", "content": PERSONA}, {"role": "user", "content": f"{situation}\nInterviewer: {text}"}])
        answer = (r.choices[0].message.content or "").strip()
        log.append({"key": ctx["key"], "kind": "clear" if ctx["key"] in hidden else "irrelevant", "answer": answer})
        return answer

    ask.log = log
    return ask


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    a, b = ranks(xs), ranks(ys)
    ma, mb = st.fmean(a), st.fmean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return num / den if den else None


def summarize(rows: list[dict], file: str) -> str:
    free = [r for r in rows if r["expert"] == "free" and r["strategy"] == "v0_open"]
    clear = ext_ok = vague = vague_ok = leaks = qs = 0
    ratings, deltas = [], []
    for r in free:
        for t, e in zip(r["turns"], r["expert_log"]):
            if t["by_model"]:
                qs += 1
                leaks += any(w in t["question"].lower() for w in study.HIDDEN_TERMS)
            if e["kind"] == "clear":
                clear += 1
                ext_ok += study.matches_hidden(t["condition"])
            else:
                vague += 1
                vague_ok += t["condition"] is None
            if t["rating"] is not None:
                ratings.append(t["rating"])
                deltas.append(t["delta"])
    gains = [r["gain"] for r in free]
    sgains = [r["structured_gain"] for r in free]
    h9 = (st.fmean(gains) / st.fmean(sgains)) if sgains and st.fmean(sgains) > 0 else None
    rho = spearman(ratings, deltas)
    pct = lambda a, b: f"{a}/{b} = {a / b:.0%}" if b else "n/a"  # noqa: E731
    lines = [f"# LLM-driven interview, test seeds (amendment 7; {len(free)} interviews; file `{file}`)", "",
             "| bar | measured | verdict |", "|---|---|---|",
             f"| H8 extraction on clear answers >= 80% | {pct(ext_ok, clear)} | {'holds' if clear and ext_ok / clear >= 0.8 else 'FAILS'} |",
             f"| H8 no condition for vague/irrelevant >= 80% | {pct(vague_ok, vague)} | {'holds' if vague and vague_ok / vague >= 0.8 else 'FAILS'} |",
             f"| H9 interview gain >= 70% of structured gain | {st.fmean(gains):+.3f} vs {st.fmean(sgains):+.3f} ({h9:.0%}) | {'holds' if h9 is not None and h9 >= 0.7 else 'FAILS'} |" if sgains else "| H9 | n/a | n/a |",
             f"| Leakage: 0 questions with the hidden terms | {leaks} of {qs} model-written questions | {'holds' if leaks == 0 else 'FAILS'} |",
             f"| H10 (exploratory) Spearman rating vs measured effect >= 0.3 | {'n/a' if rho is None else f'{rho:.2f}'} over {len(ratings)} answers | {'holds' if rho is not None and rho >= 0.3 else 'does not hold'} |",
             "", "Per domain (mean over seeds):", "", "| domain | before | after (interview) | gain | structured gain | questions |", "|---|---|---|---|---|---|"]
    for dn in sorted({r["domain"] for r in free}):
        sel = [r for r in free if r["domain"] == dn]
        lines.append(f"| {dn} | {st.fmean(r['before'] for r in sel):.3f} | {st.fmean(r['after'] for r in sel):.3f} | {st.fmean(r['gain'] for r in sel):+.3f} | "
                     f"{st.fmean(r['structured_gain'] for r in sel):+.3f} | {st.fmean(r['questions'] for r in sel):.1f} |")
    llm = [r for r in rows if r["expert"] == "llm"]
    if llm:
        lines += ["", "Question quality with an LLM persona as the expert (exploratory):", "", "| strategy | interviews | gain | questions | first matching condition at question |", "|---|---|---|---|---|"]
        for strat in sorted({r["strategy"] for r in llm}):
            sel = [r for r in llm if r["strategy"] == strat]
            first = []
            for r in sel:
                idx = next((i + 1 for i, t in enumerate(r["turns"]) if study.matches_hidden(t["condition"])), None)
                first.append(idx)
            got = [f for f in first if f]
            lines.append(f"| {strat} | {len(sel)} | {st.fmean(r['gain'] for r in sel):+.3f} | {st.fmean(r['questions'] for r in sel):.1f} | "
                         f"{(st.fmean(got) if got else float('nan')):.1f} (found in {len(got)} of {len(sel)}) |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--summarize", action="store_true")
    ap.add_argument("--domains", default="dashboard,triage")
    ap.add_argument("--strategy", default="v0_open")
    ap.add_argument("--expert", default="free", choices=["free", "llm"])
    ap.add_argument("--patience", type=int, default=4, help="stop after this many answers in a row that explain nothing")
    ap.add_argument("--file", default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fname = a.file or ("dev.jsonl" if a.dev else "smoke.jsonl" if a.smoke else "test.jsonl")
    path = OUT / fname
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if a.summarize:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
        text = summarize(rows, fname) + f"\nCode at commit {commit}.\n"
        (RESULTS / "interview.md").write_text(text, encoding="utf-8")
        print(text)
        return 0
    done = {(r["domain"], r["seed"], r["strategy"], r["expert"]) for r in rows}
    seeds = DEV_SEEDS if a.dev else ((DEV_SEEDS[0],) if a.smoke else TEST_SEEDS)  # a smoke run never touches a test seed
    doms = study.domains()
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)
    chat = make_chat(client)
    with lr.serving(s, info, status=print):
        for dn in a.domains.split(","):
            for seed in seeds:
                for strategy in a.strategy.split(","):
                    if (dn, seed, strategy, a.expert) in done:
                        continue
                    built = study.build(doms[dn], 80, seed, hidden_fact=True)
                    expert = llm_expert(client, built.hidden) if a.expert == "llm" else None
                    out = study.interview_experiment(doms[dn], seed, chat, strategy, expert=expert, patience=a.patience)
                    out["expert"] = a.expert
                    if a.expert == "llm":
                        out["expert_log"] = expert.log
                    with path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(out) + "\n")
                    print(f"{dn} seed {seed} {strategy}/{a.expert}: gain {out['gain']:+.3f} (structured {out['structured_gain']:+.3f}), "
                          f"{out['questions']} questions, stopped: {out['stopped']}, facts {out['facts']}", flush=True)
                    if a.smoke:
                        for t in out["turns"]:
                            print(f"  Q: {t['question']}\n  A: {t['answer']}\n  -> {t['condition']} (rating {t['rating']}, delta {t['delta']}, held_for {len(t['held_for'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
