"""Analyse a run of live_hidden_rule_test.py: did the pipeline capture the screens and choices, and what rule does it find?

    python scripts/analyze_hidden_rule_test.py OUT_DIR      # writes OUT_DIR/analysis.md; reads OUT_DIR/stated_rule.txt if present
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playbook import induce, pilot  # noqa: E402
from playbook.decisions import NONE, Decision, add_context, add_ratios, load_decisions  # noqa: E402

def main() -> None:
    OUT = Path(sys.argv[1])
    choices = json.loads((OUT / "choices.json").read_text(encoding="utf-8"))
    session = next((OUT / "sessions").iterdir())
    ds = load_decisions(session / "decisions.jsonl")
    lines = [f"# Analysis of {OUT.name}", "", "## Capture", ""]
    sq = lambda d: {k.replace("_", ""): v for k, v in d.items()}  # noqa: E731  (OCR may drop the space in a label)
    ok_read = ok_cat = ok_out = 0
    for d, c in zip(ds, choices):
        k, r = c["case"], sq(d.readouts)
        ok_read += (r.get("runid") == k["run_id"] and r.get("epoch") == k["epoch"] and r.get("trainloss") == k["train"]
                    and r.get("valloss") == k["val"] and r.get("gpuutil") == k["gpu"])
        ok_cat += d.cats.get("owner") == k["owner"].lower()
        ok_out += (d.outcome != NONE) == (c["choice"] == "Kill run")
    lines += [f"- {len(ds)} decisions found for {len(choices)} choices.",
              f"- Readouts exact: {ok_read}/{len(ds)}. Owner word: {ok_cat}/{len(ds)}. Outcome (kill vs not): {ok_out}/{len(ds)}."]
    add_context(ds)
    cut = int(len(ds) * 0.7)
    lines += ["", f"## Rule fit ({sum(d.outcome != NONE for d in ds)} kills of {len(ds)}; fitted on the first {cut}, tested on the last {len(ds) - cut})", ""]
    for label, kw, ratios in (("default tree", {}, False), ("default + ratios", {}, True), ("lookahead + ratios", {"lookahead": True}, True)):
        d2 = [Decision(**{**x.__dict__, "features": dict(x.features)}) for x in ds]
        if ratios:
            add_ratios(d2)
        t, h = induce.fit(d2, **kw), induce.holdout(d2, **kw)
        lines += [f"**{label}:** fits {induce.accuracy(t, d2):.0%} of all choices, predicts {h['test_accuracy']:.0%} of the last {len(ds) - cut}", ""]
        lines += [f"- `{r}`" for r in induce.rules(t)] + [""]
    stated_file = OUT / "stated_rule.txt"
    d3 = [Decision(**{**x.__dict__, "features": dict(x.features)}) for x in ds]
    add_ratios(d3)
    lines += ["## Report a person would get (ratios on)", "", pilot.report(d3, {"stated_rule": stated_file.read_text(encoding="utf-8") if stated_file.exists() else "", "cases": []})]
    (OUT / "analysis.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
