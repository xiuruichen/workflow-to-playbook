"""Playbook -> Markdown.

The Markdown is written next to the recording (sessions/<id>/playbook.md), so links to the
video and keyframes are relative. Timestamp links use the `#t=<seconds>` media fragment,
which browsers honour when opening the video file.
"""

from __future__ import annotations

from pathlib import Path

from .analyzer import fmt_ts
from .models import Playbook, Step


def _badge(step: Step, threshold: float) -> str:
    if step.verified:
        return f"✅ verified (model {step.confidence:.2f})"
    if step.confidence < threshold:
        return f"⚠️ {step.confidence:.2f}"
    return f"🟢 {step.confidence:.2f}"


def _anchor(step: Step) -> str:
    return f"step-{step.index}"


def _ts_link(pb: Playbook, t: float) -> str:
    label = fmt_ts(t)
    return f"[{label}]({pb.video}#t={int(t)})" if pb.video else label


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(pb: Playbook) -> str:
    pb.refresh_flags()
    flagged = pb.review_steps
    out: list[str] = [f"# {pb.title}", ""]
    if pb.goal:
        out += [f"**Goal:** {pb.goal}", ""]
    if pb.summary:
        out += [pb.summary, ""]

    meta = [
        ("Recording", f"[{pb.video}]({pb.video}) ({fmt_ts(pb.duration)})" if pb.video else fmt_ts(pb.duration)),
        ("Source", "live capture (screen + input events)" if pb.source == "live" else "imported video (visual only)"),
        ("Apps / sites", ", ".join(pb.apps) or "—"),
        ("Steps", str(len(pb.steps))),
        ("Model", pb.model),
        ("Generated", pb.generated_at),
    ]
    out += ["| | |", "|---|---|"] + [f"| **{k}** | {_cell(v)} |" for k, v in meta] + [""]

    # Review summary
    out += ["## Review summary", ""]
    if flagged:
        out += [
            f"⚠️ **{len(flagged)} of {len(pb.steps)} steps need human review** (confidence below {pb.threshold:.2f}):",
            "",
        ]
        out += [f"- [Step {s.index}: {s.title}](#{_anchor(s)}) at {fmt_ts(s.t_start)} ({s.confidence:.2f})" for s in flagged]
    else:
        out += [f"✅ All steps are at or above the {pb.threshold:.2f} confidence threshold."]
    for note in pb.notes:
        out += ["", f"> ℹ️ {note}"]
    out.append("")

    if pb.prerequisites:
        out += ["## Prerequisites", ""] + [f"- {p}" for p in pb.prerequisites] + [""]

    if pb.inputs:
        out += ["## Inputs", "", "Values that will likely change each time this playbook is used:", ""]
        out += ["| Input | Example from recording | Description |", "|---|---|---|"]
        out += [f"| `{_cell(i.name)}` | {_cell(i.example or '')} | {_cell(i.description or '')} |" for i in pb.inputs]
        out.append("")

    out += ["## Steps", ""]
    for s in pb.steps:
        out += _render_step(pb, s)

    if pb.open_questions:
        out += ["## Open questions", "", "Things the system could not infer from the recording:", ""]
        out += [f"- {q}" for q in pb.open_questions] + [""]

    out += [
        "---",
        f"*Generated from a screen recording. Steps marked ⚠️ fell below a confidence of {pb.threshold:.2f} "
        "and should be checked against the recording before this playbook is used.*",
        "",
    ]
    return "\n".join(out)


def _render_step(pb: Playbook, s: Step) -> list[str]:
    span = _ts_link(pb, s.t_start)
    if s.t_end - s.t_start >= 2:
        span += f" – {fmt_ts(s.t_end)}"
    out = [f'<a id="{_anchor(s)}"></a>', f"### Step {s.index}: {s.title}", "", f"{span} · {_badge(s, pb.threshold)}", ""]
    if s.description and s.description != s.title:
        out += [s.description, ""]
    details = [
        ("App", s.app),
        ("Action", s.action),
        ("Target", s.target),
        ("Value", s.value),
        ("Expected result", s.expected_result),
    ]
    out += [f"- **{k}:** {v}" for k, v in details if v]
    out.append("")

    if s.needs_review and not s.verified:
        reason = s.uncertainty_reason or "The model was not confident about this step."
        out += [f"> ⚠️ **NEEDS REVIEW ({s.confidence:.2f})**: {reason}"]
        if s.evidence:
            out += [">", f"> *Evidence:* {s.evidence}"]
        if s.calibration_notes:
            out += [">", "> *Confidence adjustments:* " + "; ".join(s.calibration_notes)]
        out += [">", f"> - [ ] Verified by a human against the recording at {_ts_link(pb, s.t_start)}", ""]

    shots = [(label, p) for label, p in (("Before", s.keyframe_before), ("After", s.keyframe_after)) if p]
    if shots:
        out += ["<details><summary>Screenshots</summary>", ""]
        out += [f'<b>{label}</b><br><img src="{p}" width="560" alt="{label} step {s.index}"><br>' for label, p in shots]
        out += ["", "</details>", ""]
    return out


def write_playbook(pb: Playbook, session_dir: Path) -> Path:
    session_dir = Path(session_dir)
    pb.save(session_dir)
    path = session_dir / "playbook.md"
    path.write_text(render_markdown(pb), encoding="utf-8")
    return path


def render_session(session_dir: Path) -> Path:
    """Re-render playbook.md from playbook.json (no API calls)."""
    return write_playbook(Playbook.load(Path(session_dir)), session_dir)
