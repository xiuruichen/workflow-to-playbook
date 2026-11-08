"""A pilot with a real person: they judge a run of cases by their own rule, and we try to recover it.

Everything else in this project was checked against scripted "people" who follow a rule we planted.
The roadmap's success statement needs the opposite: a person whose rule is not known to us, who
recognizes (or disputes) the rule we fitted. This module is the minimum to run that:

* `make_cases` draws a reproducible sequence of cases in a theme the person picks (a training run,
  an overdue invoice, a support ticket). Nothing on screen hints at a rule. Items come back now and
  then with one value changed, so a "since last time" cue exists for the person to use.
* `render_html` writes a single offline page: one case at a time, "act" or "leave it alone", an
  optional one-line reason, and at the end a box for the person to state their rule in their own
  words. The page logs the choices and offers the log as a download.
* `load_log` turns that log into the decision log the rest of the pipeline uses, and `report`
  writes a plain-language report: the rule we found, how well it predicts later choices, the
  choices it cannot explain, and the person's own statement set against the fitted rule.

The page logs the decisions itself, so the pilot does not depend on screen capture or OCR; recording
the screen alongside it (`python -m playbook record`) additionally tests the capture path on a human.
"""

from __future__ import annotations

import html
import json
import random
import re
from collections import Counter
from pathlib import Path

from . import elicit, induce
from .decisions import NONE, Decision, add_context, slug
from .knowledge import classify_decision

THEMES = {
    "run": {"title": "Training run check", "item": "run", "act": "Stop the run", "leave": "Leave it running",
            "fields": [("Spikes", "choice", [0, 1, 2, 3], [2, 2, 3, 2]), ("Batch size", "double", 256, 0.3),
                       ("Loss", "falling", 3.0, 0.1), ("Hours since last check", "range", 4, 30)],
            "cats": [("Dataset", ["clean", "new"])]},
    "invoice": {"title": "Overdue invoice", "item": "invoice", "act": "Escalate", "leave": "Leave it",
                "fields": [("Amount", "choice", [450, 1200, 2300, 3400, 5200, 6100, 7400, 9800], None),
                           ("Days overdue", "range", 5, 60), ("Reminders sent", "range", 0, 4)],
                "cats": [("Vendor", ["known", "new"])]},
    "ticket": {"title": "Support ticket", "item": "ticket", "act": "Escalate", "leave": "Leave it",
               "fields": [("Hours open", "range", 1, 72), ("Severity", "choice", [1, 2, 3, 4, 5], None),
                          ("Earlier contacts", "range", 0, 6)],
               "cats": [("Tier", ["standard", "gold"])]},
}
REPEAT = 0.3  # chance that the next case is the previous item again with one value updated


def make_cases(theme: str, n: int, seed: int) -> list[dict]:
    """A reproducible run of cases: [{"readouts": {"Spikes": 2, ...}, "cats": {"Dataset": "new"}}, ...]."""
    spec = THEMES[theme]
    rng = random.Random(f"pilot-{theme}-{seed}")
    cases: list[dict] = []
    state: dict = {}
    for i in range(n):
        prev = cases[-1] if cases else None
        again = prev is not None and rng.random() < REPEAT
        reads: dict[str, float] = {}
        for name, kind, a, b in spec["fields"]:
            if again and kind in ("double", "falling"):
                reads[name] = prev["readouts"][name]  # the same item: its settings have not moved on
                continue
            if kind == "choice":
                reads[name] = rng.choices(a, weights=b)[0] if b else rng.choice(a)
            elif kind == "range":
                reads[name] = rng.randrange(a, b + 1)
            elif kind == "double":  # a setting that is raised now and then and otherwise stays
                cur = state.get(name, a)
                if i and rng.random() < b:  # raised now and then; after four doublings it is reset, so changes keep happening
                    cur = a if cur >= a * 16 else cur * 2
                state[name] = cur
                reads[name] = state[name]
            else:  # "falling": drifts down
                state[name] = round(max(0.5, state.get(name, a) - rng.random() * b), 2)
                reads[name] = state[name]
        cats = {name: rng.choice(words) for name, words in spec["cats"]}
        if again:  # same item as last time with one number moved
            reads = dict(prev["readouts"])
            name = rng.choice([f[0] for f in spec["fields"] if f[1] in ("choice", "range")])
            kind, a, b = next((f[1], f[2], f[3]) for f in spec["fields"] if f[0] == name)
            reads[name] = rng.choices(a, weights=b)[0] if kind == "choice" and b else (rng.choice(a) if kind == "choice" else rng.randrange(a, b + 1))
            cats = dict(prev["cats"])
        cases.append({"readouts": reads, "cats": cats})
    return cases


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#f6f7f9;--fg:#1c1f24;--card:#fff;--line:#d9dde3;--act:#2f5fd0;--leave:#4a4f57}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#eceff3;--card:#1e2127;--line:#323741;--act:#6d93f0;--leave:#9aa0aa}}
body{margin:0;font:20px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:720px;margin:0 auto;padding:32px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px 28px;margin:16px 0}
.row{font-size:34px;font-weight:600;margin:6px 0}
button{font:inherit;font-size:24px;padding:14px 26px;border-radius:10px;border:0;color:#fff;cursor:pointer;margin:6px 10px 6px 0}
#act{background:var(--act)}#leave{background:var(--leave)}
input,textarea{font:inherit;width:100%;box-sizing:border-box;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
.muted{color:var(--leave);font-size:16px}
</style></head><body><main>
<h1>__TITLE__</h1>
<div id="intro" class="card"><p>You will see __N__ __ITEM__s, one at a time. For each, decide what you would really do:
<b>__ACT__</b> or <b>__LEAVE__</b>. There is no right answer and nothing is graded. Go at your own pace; keys: <b>A</b> = __ACT__, <b>L</b> = __LEAVE__.
A one-line reason is optional.</p><button id="start" style="background:var(--act)">Start</button></div>
<div id="case" class="card" hidden><div class="muted" id="count"></div><div id="rows"></div>
<p><input id="why" placeholder="Why? (optional, one line)"></p>
<button id="act">__ACT__ (A)</button><button id="leave">__LEAVE__ (L)</button></div>
<div id="end" class="card" hidden><p>Done. In your own words, <b>when do you __ACT_LOWER__?</b> Write the rule as you would explain it to a colleague (it is fine if you are unsure).</p>
<textarea id="rule" rows="5"></textarea><p><button id="save" style="background:var(--act)">Download the log</button></p>
<p class="muted">The log is a small file with the cases, your choices and your words. It stays on this computer until you share it.</p></div>
<script>
const CASES=__CASES__, META=__META__;
let i=0,shown=0,log=[];
const $=id=>document.getElementById(id);
function show(){const c=CASES[i];$("count").textContent=(i+1)+" of "+CASES.length;
 $("rows").innerHTML=Object.entries(c.readouts).map(([k,v])=>'<div class="row">'+k+': '+v+'</div>').join("")+
  Object.entries(c.cats).map(([k,v])=>'<div class="row">'+k+': '+v[0].toUpperCase()+v.slice(1)+'</div>').join("");
 $("why").value="";shown=performance.now();}
function choose(a){if($("case").hidden)return;const c=CASES[i];
 log.push({index:i,readouts:c.readouts,cats:c.cats,choice:a?"act":"leave",dwell_s:(performance.now()-shown)/1000,reason:$("why").value.trim()});
 i++;if(i>=CASES.length){$("case").hidden=true;$("end").hidden=false;}else show();}
$("start").onclick=()=>{$("intro").hidden=true;$("case").hidden=false;show();};
$("act").onclick=()=>choose(true);$("leave").onclick=()=>choose(false);
document.addEventListener("keydown",e=>{if(e.target.tagName==="INPUT"||e.ctrlKey||e.metaKey||e.altKey||e.repeat)return;if(e.key==="a"||e.key==="A")choose(true);if(e.key==="l"||e.key==="L")choose(false);});
$("save").onclick=()=>{const out={meta:META,stated_rule:$("rule").value,cases:log};
 const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:"application/json"}));
 a.download="pilot_log.json";a.click();};
</script></main></body></html>"""


def render_html(cases: list[dict], theme: str, seed: int) -> str:
    spec = THEMES[theme]
    meta = {"theme": theme, "seed": seed, "act": spec["act"], "leave": spec["leave"]}
    page = _PAGE
    for k, v in {"__TITLE__": html.escape(spec["title"]), "__N__": str(len(cases)), "__ITEM__": spec["item"],
                 "__ACT__": html.escape(spec["act"]), "__ACT_LOWER__": html.escape(spec["act"].lower()),
                 "__LEAVE__": html.escape(spec["leave"])}.items():
        page = page.replace(k, v)
    return page.replace("__CASES__", json.dumps(cases)).replace("__META__", json.dumps(meta))


def load_log(path: Path) -> tuple[list[Decision], dict]:
    """The page's download -> decisions in the pipeline's form (one session per case, in order) and the raw log."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    act = raw.get("meta", {}).get("act", "act")
    out = []
    for c in raw["cases"]:
        t = float(c["index"]) * 30.0
        out.append(Decision(f"case{c['index']:03d}", t, t + float(c.get("dwell_s", 10.0)), "pilot",
                            {slug(k): float(v) for k, v in c["readouts"].items()}, act if c["choice"] == "act" else NONE,
                            cats={slug(k): str(v).lower() for k, v in c.get("cats", {}).items()}))
    return add_context(out), raw


def _mentioned(feature: str, text: str) -> bool:
    """Does the person's own statement mention this feature (any word of its name)?"""
    words = [w for w in re.split(r"[=_/]", re.sub(r"^(changed|delta)_", "", feature)) if len(w) > 2]
    return any(w in text.lower() for w in words)


def report(decisions: list[Decision], raw: dict | None = None) -> str:
    raw = raw or {}
    n = len(decisions)
    acted = sum(d.outcome != NONE for d in decisions)
    out = ["# Pilot report", "",
           f"{n} cases; you acted on {acted} and left {n - acted} alone.", ""]
    if n < 12:
        return "\n".join(out + ["Too few cases to fit a rule (about 30-40 are needed)."])
    auto = induce.fit_auto(decisions)  # also tries ratios of readouts, a lookahead tree and a rule list, and says what it kept
    tree, prepared = auto.model, auto.prepare(decisions)
    cut = max(1, int(n * 0.7))
    held_acc = induce.fit_auto(decisions[:cut]).accuracy(decisions[cut:])
    major = Counter(d.outcome for d in decisions[:cut]).most_common(1)[0][0]
    base = sum(d.outcome == major for d in decisions[cut:]) / max(1, n - cut)
    out += ["## The rule we found", "",
            "Read it as a hypothesis about your habits, not as a fact. 'changed_x' means x differs from the previous case.", ""]
    out += [f"- {line}" for line in auto.rules()]
    plain_cv = auto.cv.get("plain/tree")
    kept = f"{auto.cv.get(('ratios' if auto.ratios else 'plain') + '/' + auto.kind)}" if auto.cv else "n/a"
    out += ["", f"It fits {auto.accuracy(decisions):.0%} of your {n} choices. Fitted on your first {cut}, it predicts "
            f"{held_acc:.0%} of your last {n - cut} (always doing the most common thing would get {base:.0%}).",
            f"We also tried ratios of readouts, a lookahead tree and a rule list; kept: {auto.choice} (cross-validated accuracy {kept}, "
            f"against {plain_cv} for the plain tree).", ""]
    odd = induce.disagreements(prepared)
    out += [f"## The {len(odd)} choice(s) it cannot explain", ""]
    if odd:
        out += ["For each: what the rule expected, what you did, and what was on screen. These are the places to explain why.", ""]
        for d, guess in odd:
            c = classify_decision(d, induce.path_features(tree, d), rule_gets_it_right=False)
            shown = ", ".join([f"{k} = {v:g}" for k, v in d.readouts.items()] + [f"{k} = {v}" for k, v in d.cats.items()])
            where = d.session if len({x.session for x in decisions}) > 1 else f"at {d.t1:.0f}s"  # one long recording: say when
            out.append(f"- {where}: you chose {d.outcome}; the rule expected {guess}. Saw: {shown}. [{c.observability}, tacit {c.tacit_score}/4]")
        common = induce.shared_conditions([d for d, _ in odd], prepared)
        if common:
            out += ["", "What these choices have in common (a hint at a factor too rare for the rule to learn; check it with the person):", ""]
            out += [f"- `{c['condition']}` holds for {c['covers']} of the {c['of']}, and for {c['also_true_of']} other case(s) where the rule was right" for c in common]
    else:
        out.append("None: the rule explains every choice.")
    out += ["", "## Your own words against the fitted rule", ""]
    stated = (raw.get("stated_rule") or "").strip()
    if stated:
        used = sorted(induce.features_used(tree))
        out += [f"You wrote: \"{stated}\"", ""]
        out += [f"- The fit uses `{f}`: " + ("you mention it." if _mentioned(f, stated) else "**you did not mention it.**") for f in used]
        readouts = sorted({k for d in decisions for k in d.readouts} | {k for d in decisions for k in d.cats})
        unused = [k for k in readouts if _mentioned(k, stated) and not any(k in f for f in used)]
        out += [f"- You mention `{k}`, but the fit does not use it." for k in unused]
        out += ["", "Judge for yourself: is the fitted rule partly right? What would you correct?"]
    else:
        out.append("No statement was written; add one to compare.")
    reasons = [(d.session, c.get("reason")) for d, c in zip(decisions, raw.get("cases", [])) if c.get("reason")]
    if reasons:
        out += ["", "## Reasons you wrote while deciding", ""] + [f"- {s}: {r}" for s, r in reasons]
    out += ["", "## Next", "", "Answer the questions about the unexplained choices (`python -m playbook pilot elicit pilot_log.json`), "
            "which refits the rule with what you tell it. Then judge: is the new rule closer to how you decide?"]
    return "\n".join(out) + "\n"


def ask_loop(decisions: list[Decision], store: Path, ask=None, say=print, chat=None, strategy: str = "v0_open") -> dict:
    """The interview: one question per unexplained choice (as `python -m playbook elicit`, on the pilot log).

    The answers (verbatim, with an optional named condition and the other cases it held for) are saved to
    `store`; the named condition becomes a 0/1 feature and the rule is refitted. Returns elicit.effect().
    """
    ask = ask or input  # looked up when called, so a replaced `input` is honoured
    answers = elicit.load_answers(store)
    elicit.apply_answers(decisions, answers)
    if chat is not None:  # a model writes the questions and reads the answers (playbook/interview.py)
        from . import interview

        saved = list(answers)
        say(f"{len(decisions)} cases; a model will ask about the choices the rule cannot explain. Press Enter to skip.\n")

        def keep(turn, ans):
            saved.append(ans)
            elicit.save_answers(saved, store)

        try:
            interview.run_interview(decisions, lambda text, ctx: ask("> "), chat, strategy, say=say, on_turn=keep)
        except (EOFError, KeyboardInterrupt):
            say("\nStopped; answers so far are saved.")
        return interview.effect(decisions, saved)
    questions = elicit.build_questions(decisions)
    say(f"{len(decisions)} cases; the rule cannot explain {len(questions)}. Press Enter to skip a question.\n")
    try:
        for q in questions:
            if any(a.key == elicit.key(q.decision) for a in answers):
                continue
            say(q.text())
            reason = ask("> ").strip()
            if not reason:
                say("")
                continue
            fact = ask("Name the condition in a few words (optional): ").strip() or None
            also: list[str] = []
            if fact:
                cands = elicit.tag_candidates(q, questions)
                for i, c in enumerate(cands, 1):
                    say(f"  {i}. {c.session} you chose {c.outcome}, saw {c.readouts} {c.cats}")
                picks = ask("Did it also hold for any of these? Numbers separated by commas: ").strip()
                also = [elicit.key(cands[int(n) - 1]) for n in picks.replace(" ", "").split(",") if n.isdigit() and 0 < int(n) <= len(cands)]
            answers.append(elicit.Answer(q.decision.session, q.decision.t1, reason, fact, also))
            elicit.save_answers(answers, store)
            say("")
    except (EOFError, KeyboardInterrupt):
        say("\nStopped; answers so far are saved.")
    return elicit.effect(decisions, answers)
