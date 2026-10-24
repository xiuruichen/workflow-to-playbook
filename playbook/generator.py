"""Playbook -> Markdown + a self-contained HTML viewer.

Both files are written next to the recording (sessions/<id>/), so links to the video and
keyframes are relative. Markdown timestamp links use the `#t=<seconds>` media fragment,
which browsers honour when opening the video file directly; most Markdown previewers
don't, which is why playbook.html exists: it plays the recording beside the steps and
every timestamp seeks the video.
"""

from __future__ import annotations

import html
from pathlib import Path

from .analyzer import fmt_ts
from .models import Playbook, Step


def review_reasons(step: Step, threshold: float) -> list[str]:
    """Why a step is flagged: low confidence and/or something that looks wrong."""
    reasons = []
    if step.confidence < threshold:
        reasons.append(f"Low confidence ({step.confidence:.2f}): {step.uncertainty_reason or 'the model was not sure about this step.'}")
    if step.review_note:
        reasons.append(f"Check: {step.review_note}")
    return reasons


def _badge(step: Step, threshold: float) -> str:
    if step.verified:
        return f"✅ verified (model {step.confidence:.2f})"
    if step.confidence < threshold:
        return f"⚠️ {step.confidence:.2f}"
    if step.review_note:
        return f"🔎 {step.confidence:.2f}"
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
        ("Recording", f"[{pb.video}]({pb.video}) ({fmt_ts(pb.duration)}) · [interactive viewer](playbook.html)" if pb.video else fmt_ts(pb.duration)),
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
        out += [f"⚠️ **{len(flagged)} of {len(pb.steps)} steps need human review:**", ""]
        for s in flagged:
            why = "; ".join(r.split(":")[0] for r in review_reasons(s, pb.threshold))
            out.append(f"- [Step {s.index}: {s.title}](#{_anchor(s)}) at {fmt_ts(s.t_start)} ({why})")
    else:
        out += [f"✅ No steps were flagged: all are at or above the {pb.threshold:.2f} confidence threshold and nothing looked inconsistent."]
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
        f"*Generated from a screen recording. ⚠️ marks steps below a confidence of {pb.threshold:.2f}; "
        "🔎 marks steps that were understood but look worth double-checking. Verify both against the "
        "recording before relying on this playbook.*",
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
        reasons = review_reasons(s, pb.threshold)
        out += [f"> ⚠️ **NEEDS REVIEW** ({s.confidence:.2f})"]
        out += [f"> - {r}" for r in reasons]
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


# --------------------------------------------------------------------------- HTML viewer
_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--accent:#2563eb;
--warn-bg:#fff6e5;--warn-line:#f0b429;--ok:#16a34a;--active:#eef4ff}
@media (prefers-color-scheme:dark){:root{--bg:#111214;--card:#1b1c1f;--fg:#ececee;--muted:#9a9aa2;
--line:#2c2d31;--accent:#60a5fa;--warn-bg:#2b2412;--warn-line:#b7861f;--ok:#4ade80;--active:#1c2638}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 24px 8px}h1{margin:0 0 4px;font-size:24px}.muted{color:var(--muted)}
.wrap{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px;padding:12px 24px 40px}
.player{position:sticky;top:12px;align-self:start}video{width:100%;border-radius:10px;background:#000}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-top:12px}
.step{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:10px;
padding:12px 14px;margin-bottom:10px;cursor:pointer}
.step.flag{border-left-color:var(--warn-line)}.step.active{background:var(--active);border-color:var(--accent)}
.step h3{margin:0;font-size:16px}.ts{font:600 13px ui-monospace,Consolas,monospace;color:var(--accent);
background:none;border:0;padding:0;cursor:pointer}
.meta{display:flex;gap:10px;align-items:center;margin-bottom:4px;font-size:13px}
.review{background:var(--warn-bg);border:1px solid var(--warn-line);border-radius:8px;padding:8px 10px;margin-top:8px;font-size:14px}
.review ul{margin:4px 0 0;padding-left:18px}.shots{display:flex;gap:8px;margin-top:8px}
.shots img{width:50%;border:1px solid var(--line);border-radius:6px}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:6px 0 0;font-size:14px}dt{color:var(--muted)}dd{margin:0}
.filter{margin:0 0 10px;font-size:14px}
@media (max-width:860px){.wrap{grid-template-columns:1fr;padding:12px 16px}.player{position:static}header{padding:16px}}
"""

_JS = """
const v=document.getElementById('video');const steps=[...document.querySelectorAll('.step')];
function seek(t){if(!v)return;v.currentTime=t;v.play().catch(()=>{});v.scrollIntoView({block:'nearest',behavior:'smooth'});}
steps.forEach(s=>s.addEventListener('click',e=>{if(e.target.closest('a,summary,input'))return;seek(+s.dataset.t);}));
if(v)v.addEventListener('timeupdate',()=>{let cur=null;for(const s of steps){if(+s.dataset.t<=v.currentTime+0.25)cur=s;}
steps.forEach(s=>s.classList.toggle('active',s===cur));});
const f=document.getElementById('onlyflag');if(f)f.addEventListener('change',()=>steps.forEach(s=>{
s.style.display=f.checked&&!s.classList.contains('flag')?'none':'';}));
"""


def render_html(pb: Playbook) -> str:
    """A single-file viewer: the recording on the left, steps on the right; click to seek."""
    pb.refresh_flags()
    e = html.escape
    flagged = pb.review_steps
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{e(pb.title)}</title><style>{_CSS}</style></head><body>",
        f"<header><h1>{e(pb.title)}</h1>",
        f"<div class='muted'>{e(pb.goal)}</div>" if pb.goal else "",
        f"<div class='muted' style='font-size:13px;margin-top:6px'>{fmt_ts(pb.duration)} · {len(pb.steps)} steps · "
        f"{len(flagged)} need review · {e(', '.join(pb.apps))} · {e(pb.model)}</div></header>",
        "<div class='wrap'><div class='player'>",
    ]
    if pb.video:
        parts.append(f"<video id='video' src='{e(pb.video)}' controls preload='metadata'></video>")
    if pb.summary:
        parts.append(f"<div class='panel'>{e(pb.summary)}</div>")
    for title, items in (("Inputs", [f"<code>{e(i.name)}</code> e.g. {e(i.example or '')}" for i in pb.inputs]),
                         ("Open questions", [e(q) for q in pb.open_questions]),
                         ("Notes", [e(n) for n in pb.notes])):
        if items:
            parts.append(f"<div class='panel'><b>{title}</b><ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul></div>")
    parts.append("</div><div>")
    if flagged:
        parts.append("<label class='filter'><input type='checkbox' id='onlyflag'> Show only steps that need review</label>")
    for s in pb.steps:
        flag = s.needs_review and not s.verified
        badge = "verified" if s.verified else f"{s.confidence:.2f}"
        parts.append(f"<div class='step{' flag' if flag else ''}' id='{_anchor(s)}' data-t='{int(s.t_start)}'>")
        parts.append(f"<div class='meta'><button class='ts' title='Play from here'>▶ {fmt_ts(s.t_start)}</button>"
                     f"<span class='muted'>Step {s.index} · {e(s.action)} · confidence {badge}</span></div>")
        parts.append(f"<h3>{e(s.title)}</h3>")
        if s.description and s.description != s.title:
            parts.append(f"<div>{e(s.description)}</div>")
        rows = [("App", s.app), ("Target", s.target), ("Value", s.value), ("Expected", s.expected_result)]
        if any(v for _, v in rows):
            parts.append("<dl>" + "".join(f"<dt>{k}</dt><dd>{e(v)}</dd>" for k, v in rows if v) + "</dl>")
        if flag:
            reasons = "".join(f"<li>{e(r)}</li>" for r in review_reasons(s, pb.threshold))
            ev = f"<div class='muted'>Evidence: {e(s.evidence)}</div>" if s.evidence else ""
            parts.append(f"<div class='review'><b>⚠️ Needs review</b><ul>{reasons}</ul>{ev}</div>")
        shots = [p for p in (s.keyframe_before, s.keyframe_after) if p]
        if shots:
            parts.append("<details><summary class='muted'>Screenshots (before / after)</summary><div class='shots'>"
                         + "".join(f"<img loading='lazy' src='{e(p)}' alt=''>" for p in shots) + "</div></details>")
        parts.append("</div>")
    parts.append(f"</div></div><script>{_JS}</script></body></html>")
    return "".join(parts)


def write_playbook(pb: Playbook, session_dir: Path) -> Path:
    """Write playbook.json, playbook.md and playbook.html; returns the Markdown path."""
    session_dir = Path(session_dir)
    pb.save(session_dir)
    (session_dir / "playbook.html").write_text(render_html(pb), encoding="utf-8")
    path = session_dir / "playbook.md"
    path.write_text(render_markdown(pb), encoding="utf-8")
    return path


def render_session(session_dir: Path) -> Path:
    """Re-render playbook.md / playbook.html from playbook.json (no API calls)."""
    return write_playbook(Playbook.load(Path(session_dir)), session_dir)
