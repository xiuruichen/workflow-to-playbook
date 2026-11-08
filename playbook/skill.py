"""Playbook -> an agent-ready skill: SKILL.md (Agent Skills format) + skill.json.

The playbook is written for people. An agent needs the same procedure in a form it can
follow for *new* inputs, and it must know where the recording alone is not enough. So:

- input examples seen in the recording become `{{placeholders}}` in every step;
- a value typed after being read on screen (copied from a page into a sheet, say) is
  recorded as data flowing from that earlier step, not as a constant: next time the page
  will show something else. Near-misses count too, so a demonstrated typo isn't replayed;
- a step the system was unsure about, or that looks wrong, and that no reviewer confirmed,
  becomes a "confirm with a human" gate carrying the same reasons the viewer shows;
- steps a reviewer marked wrong are left out, so a demonstrated mistake is never replayed.

With `judgment` (see build_judgment), the skill also says when to act: the rules fitted to the
person's pooled decisions, their own stated reasons, the value ranges seen, and the cases the
rules could not explain, with a "ask a human first" boundary.

Only fields already in playbook.json (plus the decision summaries passed in: on-screen numbers,
session ids and the person's own words) are exported: no screenshots, video or event log.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .consistency import (
    SOURCE_ACTIONS,
    TYPING_ACTIONS,
    _norm,
    _tokens,
    is_misread_number,
    is_near_miss,
)
from . import induce
from .decisions import Decision, slug
from .elicit import Answer, apply_answers
from .generator import review_reasons
from .knowledge import annotate_playbook
from .models import InputVariable, Playbook, Step

MAX_NAME = 64  # Agent Skills frontmatter limits
MAX_DESCRIPTION = 1024


def skill_name(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (slug[:MAX_NAME].rstrip("-") or "recorded-workflow")


def _inputs(pb: Playbook) -> list[InputVariable]:
    """The model's inputs or, when it listed none (small models in low-power mode), what the
    user typed: typed text is what usually changes between runs. Values copied from an
    earlier read are left out; they flow between steps instead."""
    if pb.inputs:
        return pb.inputs
    out: list[InputVariable] = []
    reads: list[tuple[str, str]] = []
    for s in pb.steps:
        if s.review == "wrong" or not s.value:
            continue
        if _actions(s) & SOURCE_ACTIONS:
            reads.append((str(s.index), s.value))
        elif _actions(s) & TYPING_ACTIONS and not _copied_from(s.value, reads):
            if any(i.example == s.value for i in out):
                continue
            base = re.sub(r"[^a-z0-9]+", "_", (s.target or "text").lower()).strip("_") or "text"
            name, n = base, 2
            while any(i.name == name for i in out):
                name, n = f"{base}_{n}", n + 1
            where = f" into {s.target}" if s.target else ""
            out.append(InputVariable(name=name, example=s.value,
                                     description=f"Typed{where} in the recording; change it if it should differ."))
    return out


def _placeholders(inputs: list[InputVariable]) -> list[tuple[re.Pattern, str]]:
    """(pattern, "{{name}}") per input example, longest example first so overlaps don't clash."""
    inputs = sorted((i for i in inputs if i.example and len(i.example.strip()) >= 2),
                    key=lambda i: len(i.example), reverse=True)
    # Not inside a longer word or number: "B2" must not match in "B23".
    return [(re.compile(rf"(?<![\w]){re.escape(i.example.strip())}(?![\w])"), "{{" + i.name + "}}") for i in inputs]


def _fill(text: str | None, subs: list[tuple[re.Pattern, str]]) -> str | None:
    if not text:
        return text
    for rx, ph in subs:
        text = rx.sub(ph, text)
    return text


def _gate(step: Step, threshold: float) -> list[str]:
    """Why a human must confirm this step first (empty: the agent may go ahead)."""
    if step.review == "correct" or not step.needs_review:
        return []
    return review_reasons(step, threshold)


def _actions(step: Step) -> set[str]:
    return set(step.action.split(" + "))  # merged steps: "click + type"


def _copied_from(value: str, earlier: list[tuple[str, str]]) -> tuple[str, str] | None:
    """(step id, source value) of the latest earlier read whose value this typed value copies."""
    for sid, source in reversed(earlier):
        for tok in _tokens(source):
            if _norm(tok) == _norm(value) or is_near_miss(value, tok) or is_misread_number(value, tok):
                return sid, tok
    return None


THIN_SUPPORT = 5  # a rule backed by fewer decisions than this is a hint, not a habit


def build_judgment(decisions: list[Decision], answers: list[Answer] | None = None, lookahead: bool | None = None) -> dict | None:
    """What was learned about *when to do what*, from pooled decisions (see decisions.py, induce.py).

    The rules are a fitted hypothesis about one person's habits, so each carries its support, the
    value ranges seen, and the cases it could not explain. The person's own words are kept.
    """
    if len(decisions) < 6:
        return None
    answers = answers or []
    apply_answers(decisions, answers)
    tree = induce.fit(decisions, lookahead=lookahead)
    odd = induce.disagreements(decisions, lookahead=lookahead)
    used = {p for f in induce.features_used(tree) if not f.startswith(("changed_", "delta_")) for p in f.split("/")}
    names = sorted({f for d in decisions for f in d.readouts} & used)  # a value the rules ignore can drift freely
    train, test = induce.holdout_accuracy(decisions, lookahead=lookahead)
    tagged = {slug(a.fact): len({a.key, *a.also}) for a in answers if a.fact}
    return {
        "basis": {
            "decisions": len(decisions), "sessions": len({d.session for d in decisions}),
            "fits_observed_decisions": round(induce.accuracy(tree, decisions), 3),
            "accuracy_on_later_decisions": round(test, 3) if len(decisions) >= 10 else None,
            "observed_ranges": {n: [min(d.readouts[n] for d in decisions if n in d.readouts),
                                    max(d.readouts[n] for d in decisions if n in d.readouts)] for n in names},
        },
        "rules": [{"when": list(conds) or ["always"], "then": leaf.label, "support": f"{leaf.correct}/{leaf.n}",
                   "thin_evidence": leaf.n < THIN_SUPPORT} for conds, leaf in induce.leaves(tree)],
        "stated_by_person": [{"fact": a.fact, "reason": a.reason, "decisions_tagged": tagged.get(slug(a.fact), 0),
                              "asked_at": a.asked_at} for a in answers if a.fact or a.reason],
        "unexplained": [{"session": d.session, "at_s": round(d.t1, 1), "did": d.outcome, "rule_expected": guess,
                         "saw": d.readouts} for d, guess in odd],
    }


def build_skill(pb: Playbook, judgment: dict | None = None) -> dict:
    pb.refresh_flags()
    annotate_playbook(pb)
    inputs = _inputs(pb)
    subs = _placeholders(inputs)
    kept = [s for s in pb.steps if s.review != "wrong"]
    steps = []
    reads: list[tuple[str, str]] = []  # (step id, value read on screen)
    for n, s in enumerate(kept, start=1):
        reasons = _gate(s, pb.threshold)
        sid = f"step-{n}"
        value, kind, value_from = _fill(s.value, subs), "literal", None
        if s.value and _actions(s) & SOURCE_ACTIONS:
            kind = "observed"  # what the screen showed in the recording; it will differ next time
            reads.append((sid, s.value))
        elif s.value and _actions(s) & TYPING_ACTIONS and value == s.value and (src := _copied_from(s.value, reads)):
            kind, value_from = "from_step", {"step": src[0], "recorded_source": src[1], "recorded_value": s.value}
            value = "{{" + src[0] + "}}"
        elif value != s.value:
            kind = "input"
        steps.append({
            "id": sid,
            "title": _fill(s.title, subs),
            "instruction": _fill(s.description, subs),
            "action": s.action,
            "app": s.app,
            "target": _fill(s.target, subs),
            "value": value,
            "value_kind": kind,
            "value_from": value_from,
            "expect": _fill(s.expected_result, subs),
            "confidence": round(s.confidence, 2),
            "observability": s.observability,
            "requires_confirmation": bool(reasons),
            "confirmation_reason": " ".join(reasons) or None,
            "source": {"playbook_step": s.index, "t_start": round(s.t_start, 2), "t_end": round(s.t_end, 2)},
        })
    gated = sum(st["requires_confirmation"] for st in steps)
    for st in steps:  # a step needs the step whose value it types
        st["depends_on"] = [st["value_from"]["step"]] if st["value_from"] else []
    return {
        "name": skill_name(pb.title),
        "title": pb.title,
        "description": _description(pb, gated),
        "goal": pb.goal,
        "apps": pb.apps,
        "prerequisites": [_fill(x, subs) for x in pb.prerequisites],
        "parameters": {
            "type": "object",
            "properties": {i.name: {"type": "string", "description": i.description or "", **({"examples": [i.example]} if i.example else {})}
                           for i in inputs},
            "required": [i.name for i in inputs],
        },
        "steps": steps,
        "completion_checks": _completion_checks(steps, pb.goal),
        "excluded_steps": [{"playbook_step": s.index, "title": s.title, "reason": "Marked wrong in review"}
                           for s in pb.steps if s.review == "wrong"],
        "open_questions": pb.open_questions,
        **({"judgment": judgment} if judgment else {}),
        "provenance": {
            "session_id": pb.session_id,
            "source": pb.source,
            "duration_s": round(pb.duration, 1),
            "model": pb.model,
            "generated_at": pb.generated_at,
            "steps_reviewed": sum(s.review != "unreviewed" for s in pb.steps),
            "steps_needing_confirmation": gated,
        },
    }


def _completion_checks(steps: list[dict], goal: str | None) -> list[dict]:
    """How an agent (or a replay) can tell the task was done, from what the recording already holds.

    value_matches: a value typed from an earlier read must equal what was read this time (not what was
    read in the recording). end_state: the last step's expected result, else the goal. Nothing is invented:
    a skill whose steps carry no expected result and no goal has no end-state check.
    """
    checks = [{"kind": "value_matches", "step": st["id"], "equals_value_read_in": st["value_from"]["step"],
               "check": f"The value typed in {st['id']} equals the value read in {st['value_from']['step']} on this run."}
              for st in steps if st["value_from"]]
    last = steps[-1] if steps else None
    text = (last["expect"] if last and last["expect"] else None) or goal
    if text:
        checks.append({"kind": "end_state", "step": last["id"] if last else None, "check": text})
    return checks


def _description(pb: Playbook, gated: int) -> str:
    what = pb.goal or pb.summary or pb.title
    text = f"{what.rstrip('.')}. Learned from a recorded demonstration ({', '.join(pb.apps) or 'desktop apps'})."
    if gated:
        text += f" {gated} step(s) must be confirmed by a human before running."
    return text[:MAX_DESCRIPTION]


def _do(st: dict, number: dict[str, int]) -> str:
    """The step as one action line, e.g. `type` the value read in step 3 into `Cell B2` (Sheets)."""
    parts = [f"`{st['action']}`"]
    if st["value_kind"] == "from_step":
        src = st["value_from"]
        parts.append(f"the value read in step {number[src['step']]} (recorded: `{src['recorded_value']}`)")
    elif st["value_kind"] == "observed":
        parts.append(f"and note the value (it was `{st['value']}` in the recording)")
    elif st["value"] and set(st["action"].split(" + ")) & TYPING_ACTIONS:
        parts.append(f"`{st['value']}`" + (f" into `{st['target']}`" if st["target"] else ""))
        st = {**st, "target": None}
    if st["target"]:
        parts.append(f"{'from' if st['value_kind'] == 'observed' else 'on'} `{st['target']}`")
    if st["value"] and st["value_kind"] in ("literal", "input") and not set(st["action"].split(" + ")) & TYPING_ACTIONS             and st["value"] != st["target"]:
        parts.append(f"(value `{st['value']}`)")
    if st["app"]:
        parts.append(f"({st['app']})")
    return " ".join(parts)


def _judgment_md(j: dict) -> list[str]:
    b = j["basis"]
    out = ["## Judgment calls", "",
           (f"When to act, learned from {b['decisions']} of this person's decisions across {b['sessions']} recording(s), "
            f"including the times they chose to do nothing. The rules below fit {b['fits_observed_decisions']:.0%} of those "
            "decisions. They are a hypothesis about one person's habits, not a policy."), ""]
    changed = sorted({c.split()[0] for r in j["rules"] for c in r["when"] if c.startswith("changed_")})
    if changed:
        out += ["In the rules, `changed_x` means: the value of x differs from what it was at the previous check "
                "(1 = changed, 0 = not). It is not shown on the current screen; compare with the earlier check "
                "or ask.", ""]
    words = sorted({c.split()[0] for r in j["rules"] for c in r["when"] if "=" in c.split()[0]})
    if words:
        out += [f"`label=word > 0.5` means the screen shows that word for that label (here: {', '.join(f'`{w}`' for w in words)}); "
                "`label=word <= 0.5` means it shows a different word or none.", ""]
    if any("/" in c.split()[0] for r in j["rules"] for c in r["when"]):
        out += ["`a/b` in a condition is the on-screen value of a divided by the on-screen value of b (a rate), not a label on the screen.", ""]
    stated = {slug(s["fact"]) for s in j["stated_by_person"] if s["fact"]}
    for r in j["rules"]:
        thin = " (few examples: treat as a hint)" if r["thin_evidence"] else ""
        then = "leave it alone (take no action)" if r["then"] == "none" else r["then"]
        hidden = sorted(f for f in stated if any(c.startswith(f + " ") for c in r["when"]))
        ask = f" Not visible on screen: ask whether {', '.join(hidden)} applies." if hidden else ""
        out.append(f"- If {' and '.join(f'`{c}`' for c in r['when'])}: **{then}** (seen {r['support']}){thin}.{ask}")
    out.append("")
    if j["stated_by_person"]:
        out += ["What the person said about their own reasons:", ""]
        out += [f"- {s['fact'] or 'Reason'}: \"{s['reason']}\"" for s in j["stated_by_person"]] + [""]
    ranges = ", ".join(f"{n} {lo:g}–{hi:g}" for n, (lo, hi) in b["observed_ranges"].items())
    out += ["**Ask a human first** when:", "",
            f"- a value is outside what was observed ({ranges}), or the situation involves something not listed above;",
            "- the rule that applies has few examples, or it would take an action that is hard to undo;"]
    if j["unexplained"]:
        out.append(f"- the situation resembles one of the {len(j['unexplained'])} decision(s) the rules could not explain: "
                   + "; ".join(f"{u['session']} (did {u['did']}, rules expected {u['rule_expected']})" for u in j["unexplained"][:5]))
    return out + [""]


def render_skill_md(pb: Playbook, skill: dict | None = None) -> str:
    sk = skill or build_skill(pb)
    # JSON strings are valid YAML scalars, so the frontmatter needs no YAML library.
    out = ["---", f"name: {sk['name']}", f"description: {json.dumps(sk['description'], ensure_ascii=False)}", "---", "",
           f"# {sk['title']}", ""]
    if sk["goal"]:
        out += [f"**Goal:** {sk['goal']}", ""]
    out += [(f"Learned from a {sk['provenance']['duration_s']:.0f}-second screen recording. Follow the steps in order; "
             "after each one, check the expected result before moving on. Where a step says **Ask a human first**, "
             "stop and get confirmation: the recording alone was not enough to be sure."), ""]
    props = sk["parameters"]["properties"]
    if props:
        out += ["## Inputs", "", "Ask for these if they were not given, and use them wherever `{{name}}` appears.", ""]
        for name, p in props.items():
            ex = f" (example: {p['examples'][0]})" if p.get("examples") else ""
            out.append(f"- `{{{{{name}}}}}`: {p['description'] or name}{ex}")
        out.append("")
    if sk["prerequisites"]:
        out += ["## Before you start", ""] + [f"- {x}" for x in sk["prerequisites"]] + [""]
    out += ["## Steps", ""]
    for i, st in enumerate(sk["steps"], start=1):
        title, text = st["title"].rstrip(". "), st["instruction"]
        # Small models often repeat the instruction (cut short) as the title.
        out.append(f"{i}. {text}" if _norm(text).startswith(_norm(title)) else f"{i}. **{title}**: {text}")
        out.append(f"   - Do: {_do(st, {x['id']: j for j, x in enumerate(sk['steps'], start=1)})}")
        if st["expect"]:
            out.append(f"   - Check: {st['expect']}")
        if st["requires_confirmation"]:
            out.append(f"   - **Ask a human first.** {st['confirmation_reason']}")
    out.append("")
    if sk.get("completion_checks"):
        out += ["## Done when", ""] + [f"- {c['check']}" for c in sk["completion_checks"]] + [""]
    if sk.get("judgment"):
        out += _judgment_md(sk["judgment"])
    if sk["excluded_steps"]:
        out += ["## Left out", "", "A reviewer marked these recorded steps wrong; do not repeat them.", ""]
        out += [f"- {x['title']}" for x in sk["excluded_steps"]] + [""]
    if sk["open_questions"]:
        out += ["## Open questions", "", "Unresolved when the recording was analyzed; ask before relying on the answer.", ""]
        out += [f"- {q}" for q in sk["open_questions"]] + [""]
    return "\n".join(out)


def skill_files(pb: Playbook, judgment: dict | None = None) -> dict[str, str]:
    """{filename: text}, e.g. for a download, without touching the disk."""
    sk = build_skill(pb, judgment)
    return {"SKILL.md": render_skill_md(pb, sk), "skill.json": json.dumps(sk, indent=2, ensure_ascii=False) + "\n"}


def write_skill(pb: Playbook, out_dir: Path, judgment: dict | None = None) -> Path:
    """Write SKILL.md and skill.json into out_dir; returns the SKILL.md path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in skill_files(pb, judgment).items():
        (out_dir / name).write_text(text, encoding="utf-8")
    return out_dir / "SKILL.md"
