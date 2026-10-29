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

Only fields already in playbook.json are exported: no screenshots, video or event log.
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
from .generator import review_reasons
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


def build_skill(pb: Playbook) -> dict:
    pb.refresh_flags()
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
            "requires_confirmation": bool(reasons),
            "confirmation_reason": " ".join(reasons) or None,
            "source": {"playbook_step": s.index, "t_start": round(s.t_start, 2), "t_end": round(s.t_end, 2)},
        })
    gated = sum(st["requires_confirmation"] for st in steps)
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
        "excluded_steps": [{"playbook_step": s.index, "title": s.title, "reason": "Marked wrong in review"}
                           for s in pb.steps if s.review == "wrong"],
        "open_questions": pb.open_questions,
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
    if sk["excluded_steps"]:
        out += ["## Left out", "", "A reviewer marked these recorded steps wrong; do not repeat them.", ""]
        out += [f"- {x['title']}" for x in sk["excluded_steps"]] + [""]
    if sk["open_questions"]:
        out += ["## Open questions", "", "Unresolved when the recording was analyzed; ask before relying on the answer.", ""]
        out += [f"- {q}" for q in sk["open_questions"]] + [""]
    return "\n".join(out)


def skill_files(pb: Playbook) -> dict[str, str]:
    """{filename: text}, e.g. for a download, without touching the disk."""
    sk = build_skill(pb)
    return {"SKILL.md": render_skill_md(pb, sk), "skill.json": json.dumps(sk, indent=2, ensure_ascii=False) + "\n"}


def write_skill(pb: Playbook, out_dir: Path) -> Path:
    """Write SKILL.md and skill.json into out_dir; returns the SKILL.md path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in skill_files(pb).items():
        (out_dir / name).write_text(text, encoding="utf-8")
    return out_dir / "SKILL.md"
