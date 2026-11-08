"""Amendment 8, H11: does the gated extraction read answers better than the first version?

    python scripts/run_fix_extraction.py --set dev     # development paraphrases: prompts may be tuned against these
    python scripts/run_fix_extraction.py --set test    # fresh test paraphrases: run once, after the code is tagged

Scores both methods ("v0" = one free extraction, "gated" = yes/no vote, quoted phrase, majority of three prompts)
on the same answers with the local 4B model. A condition counts as extracted if it is non-empty and grounded in the
answer (a near-substring); for clear answers that is the target, for vague and irrelevant answers the target is none.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openai import OpenAI  # noqa: E402
from run_interview import make_chat  # noqa: E402

from playbook import interview, llama_runtime as lr  # noqa: E402
from playbook.config import get_settings  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "docs" / "results"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dev", "test"], required=True)
    a = ap.parse_args()
    para = json.loads((RESULTS / "interview" / "paraphrases.json").read_text(encoding="utf-8"))[a.set]
    s = get_settings()
    info = lr.install(s, "qwen3-vl-4b")
    client = OpenAI(base_url=info["base_url"], api_key=lr.api_key(s), timeout=900, max_retries=0)
    chat = make_chat(client)
    rows = []
    with lr.serving(s, info, status=print):
        for kind, answers in para.items():
            for text in answers:
                row = {"kind": kind, "answer": text}
                for method in ("v0", "gated"):
                    t0 = time.time()
                    out = interview.interpret(text, [], chat, method=method)
                    cond = out["condition"]
                    row[method] = {"condition": cond, "extracted": bool(cond) and interview.grounded(cond, text) if method == "gated" else bool(cond),
                                   "seconds": round(time.time() - t0, 1)}
                rows.append(row)
                print(f"{kind:10} | v0 {str(row['v0']['condition'])[:28]:28} | gated {str(row['gated']['condition'])[:28]:28} | {text[:46]}", flush=True)
    lines = [f"# Extraction on the `{a.set}` paraphrases (amendment 8, H11)", "", "| method | clear answers read | vague answers left empty | irrelevant answers left empty | seconds per answer |", "|---|---|---|---|---|"]
    summary = {}
    for method in ("v0", "gated"):
        by = {k: [r for r in rows if r["kind"] == k] for k in ("clear", "vague", "irrelevant")}
        clear = sum(r[method]["extracted"] for r in by["clear"])
        vague = sum(not r[method]["extracted"] for r in by["vague"])
        irr = sum(not r[method]["extracted"] for r in by["irrelevant"])
        secs = st.fmean(r[method]["seconds"] for r in rows)
        summary[method] = {"clear": clear, "n_clear": len(by["clear"]), "vague_null": vague, "n_vague": len(by["vague"]), "irrelevant_null": irr, "n_irrelevant": len(by["irrelevant"])}
        lines.append(f"| {method} | {clear}/{len(by['clear'])} | {vague}/{len(by['vague'])} | {irr}/{len(by['irrelevant'])} | {secs:.1f} |")
    if a.set == "test":
        g = summary["gated"]
        ok_clear = g["clear"] >= 0.8 * g["n_clear"]
        ok_none = (g["vague_null"] + g["irrelevant_null"]) >= 0.8 * (g["n_vague"] + g["n_irrelevant"])
        lines += ["", f"**H11 (gated): clear answers >= 80%: {'holds' if ok_clear else 'FAILS'} ({g['clear']}/{g['n_clear']}); vague and irrelevant left empty >= 80%: "
                      f"{'holds' if ok_none else 'FAILS'} ({g['vague_null'] + g['irrelevant_null']}/{g['n_vague'] + g['n_irrelevant']}).**"]
    (RESULTS / f"fix_extraction_{a.set}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / "interview" / f"extraction_{a.set}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
