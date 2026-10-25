"""Streamlit UI: capture -> analyze -> review/edit the playbook.

    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from playbook.analyzer import AnalysisError, analyze_session, check_models, fmt_ts
from playbook.archive import ArchiveError, compact, compact_idle, idle_days
from playbook.backend import resolve_backend
from playbook.config import get_settings
from playbook.generator import render_markdown, review_reasons, write_playbook
from playbook.models import Manifest, Playbook
from playbook.recorder import Recorder, ensure_hot, import_video, is_archived, list_sessions
from playbook.security import SecurityError

st.set_page_config(page_title="Workflow → Playbook", page_icon="📘", layout="wide")
settings = get_settings()
ss = st.session_state
ss.setdefault("rec", None)
ss.setdefault("session", None)
ss.setdefault("seek", 0)


def select_session(path: Path) -> None:
    ss.session = str(path)
    ss.seek = 0


@st.cache_resource(show_spinner="Archiving sessions you haven't used for a while…")
def auto_archive() -> str:
    """AUTO_COMPACT=idle:<days>, once per app start."""
    try:
        days = idle_days(settings)
        done = compact_idle(settings, days) if days is not None else []
    except ArchiveError as exc:
        return f"Automatic archiving skipped: {exc}"
    return f"Archived {len(done)} idle session(s)." if done else ""


try:
    backend = resolve_backend(settings)
    backend_error = None
except SecurityError as exc:
    backend, backend_error = None, str(exc)
archive_note = auto_archive()


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("📘 Workflow → Playbook")
    st.caption("Record how you do a task; get a step-by-step playbook with timestamps and review flags.")
    if backend_error:
        st.error(backend_error)
    elif backend.local:
        st.success(f"🔒 Local analysis · `{backend.model}`" + (f" ({backend.tier.name} tier)" if backend.tier else ""))
        st.caption("Screenshots never leave this computer.")
    elif settings.gemini_api_key:
        st.warning(f"☁️ Cloud analysis (ALLOW_CLOUD) · `{settings.gemini_model}`. Screenshots are sent to Google.")
    else:
        st.error("PROVIDER=gemini but no GEMINI_API_KEY is set.")
    st.caption(f"Review threshold: confidence < {settings.confidence_threshold:.2f}")
    if archive_note:
        st.caption(archive_note)
    if backend and st.button("Check model", help="Local: is the local model installed and ready? Cloud: which models have quota"):
        with st.spinner("Checking…"):
            if backend.local:
                from playbook.local_setup import status

                for line in status(settings):
                    (st.error if line.startswith("FAIL") else st.caption)(line)
            else:
                try:
                    for model, ok, detail in check_models(settings):
                        (st.success if ok else st.caption)(f"{'✅' if ok else '❌'} `{model}`: {detail}")
                except AnalysisError as exc:
                    st.error(str(exc))

    sessions = {p.name: p for p in list_sessions(settings)}
    if sessions:
        names = list(sessions)
        current = Path(ss.session).name if ss.session else names[0]
        idx = names.index(current) if current in names else 0

        def label(n: str) -> str:
            p = sessions[n]
            return f"🔒 {p.stem}" if is_archived(p) else n + (" ✓" if (p / "playbook.json").exists() else "")

        choice = st.selectbox("Session", names, index=idx, format_func=label)
        if choice != current or not ss.session:
            select_session(sessions[choice])
        chosen = sessions[choice]
        if is_archived(chosen):
            st.caption("Archived: compressed and encrypted on disk.")
            if st.button("🔓 Restore session", type="primary"):
                with st.spinner("Decrypting and restoring…"):
                    try:
                        select_session(ensure_hot(chosen, settings))
                    except ArchiveError as exc:
                        st.error(str(exc))
                st.rerun()
        elif ss.rec is None and st.button("🔒 Archive session", help="Compress + encrypt it now; restore any time"):
            with st.spinner("Compressing and encrypting…"):
                try:
                    res = compact(chosen, settings)
                    select_session(res.archive)
                    st.toast(f"Archived: {res.before / 1e6:.1f} MB → {res.after / 1e6:.1f} MB")
                except ArchiveError as exc:
                    st.error(str(exc))
            st.rerun()
    else:
        st.info("No sessions yet. Record or import one.")

tab_capture, tab_analyze, tab_review = st.tabs(["1 · Capture", "2 · Analyze", "3 · Review playbook"])

# ---------------------------------------------------------------- capture
with tab_capture:
    left, right = st.columns(2)
    with left:
        st.subheader("Record your screen")
        st.markdown(
            "1. Click **Start recording**, then switch to the app you want to document.\n"
            "2. Work normally. Narrating isn't needed, but deliberate, unhurried actions give better results.\n"
            "3. Press **Ctrl+Shift+Q** anywhere (or **Stop** here) to finish. **Ctrl+Shift+P** pauses for sensitive moments."
        )
        st.caption(f"Monitor {settings.monitor} · {settings.capture_fps:g} fps · typed text {'masked' if settings.mask_typed_text else 'recorded'}")

        @st.fragment(run_every="2s")
        def recorder_panel():
            rec: Recorder | None = ss.rec
            if rec is None:
                if st.button("⏺ Start recording", type="primary"):
                    rec = Recorder(settings)
                    rec.start()
                    ss.rec = rec
                    st.rerun(scope="fragment")
                return
            if rec.stop_requested:
                try:
                    session = rec.stop()
                    select_session(session)
                    st.success(f"Saved session `{session.name}`. Go to **2 · Analyze**.")
                except RuntimeError as exc:
                    st.error(str(exc))
                ss.rec = None
                st.rerun()
                return
            st.warning(("⏸ PAUSED · " if rec.paused else "🔴 Recording · ") + (rec.status or "starting..."))
            c1, c2 = st.columns(2)
            if c1.button("⏸ Pause / resume"):
                rec.toggle_pause()
            if c2.button("⏹ Stop", type="primary"):
                rec.request_stop()
                st.rerun(scope="fragment")

        recorder_panel()

    with right:
        st.subheader("…or import an existing recording")
        up = st.file_uploader("Screen recording", type=["mp4", "mov", "mkv", "webm", "avi"])
        st.caption("Imported videos have no mouse/keyboard data, so expect more steps to be flagged.")
        if up is not None and st.button("Import video"):
            bar = st.progress(0.0, "Extracting keyframes…")
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / up.name
                src.write_bytes(up.getbuffer())
                session = import_video(src, settings, progress=lambda f, m: bar.progress(min(f, 1.0), m))
            m = Manifest.load(session)
            bar.progress(1.0, f"{len(m.keyframes)} keyframes extracted")
            select_session(session)
            st.success(f"Imported as `{session.name}`. Go to **2 · Analyze**.")

session_dir = Path(ss.session) if ss.session else None
archived = bool(session_dir and is_archived(session_dir))
ARCHIVED_MSG = "This session is archived (compressed + encrypted). Click **🔓 Restore session** in the sidebar to open it."

# ---------------------------------------------------------------- analyze
with tab_analyze:
    if archived:
        st.info(ARCHIVED_MSG)
    elif not session_dir or not (session_dir / "manifest.json").exists():
        st.info("Record or import a session first.")
    else:
        m = Manifest.load(session_dir)
        c = st.columns(4)
        c[0].metric("Duration", fmt_ts(m.duration))
        c[1].metric("Keyframes", len(m.keyframes))
        c[2].metric("Input events", len(m.events))
        c[3].metric("Source", m.source)
        window = backend.window_size if backend else 10
        n_calls = max(1, -(-(len(m.keyframes) - 1) // max(window - 1, 1))) + 1
        if backend and backend.local:
            st.caption(f"Analysis will make about {n_calls} request(s) to the local model `{backend.model}`. On a laptop "
                       "CPU each can take a few minutes. Responses are cached, so re-runs are instant.")
        elif backend:
            st.caption(f"Analysis will make about {n_calls} vision API call(s); at {backend.rpm}/min that takes ≈{n_calls / max(backend.rpm, 1):.1f} min. Responses are cached, so re-runs are free.")
        label = "🔍 Analyze locally" if backend and backend.local else "🔍 Analyze with Gemini"
        if st.button(label, type="primary", disabled=backend is None or (not backend.local and not settings.gemini_api_key)):
            bar = st.progress(0.0, "Starting…")
            log = st.empty()
            switches: list[str] = []

            def on_progress(frac: float, msg: str) -> None:
                bar.progress(min(frac, 1.0), msg)
                if "switched to" in msg and msg not in switches:
                    switches.append(msg)
                    log.info("\n\n".join(switches))

            try:
                pb = analyze_session(session_dir, settings, progress=on_progress)
                write_playbook(pb, session_dir)
                st.success(f"Playbook ready: {len(pb.steps)} steps, {len(pb.review_steps)} flagged. Open **3 · Review playbook**.")
            except AnalysisError as exc:
                st.error(str(exc))
        with st.expander(f"Keyframes ({len(m.keyframes)})"):
            cols = st.columns(4)
            for i, kf in enumerate(m.keyframes):
                cols[i % 4].image(str(session_dir / kf.path), caption=f"#{kf.id} · {fmt_ts(kf.t)} · {kf.trigger}")

# ---------------------------------------------------------------- review
with tab_review:
    if archived:
        st.info(ARCHIVED_MSG)
    elif not session_dir or not (session_dir / "playbook.json").exists():
        st.info("Analyze a session to see its playbook.")
    else:
        pb = Playbook.load(session_dir)
        # Widget keys include the analysis time, so re-analyzing a session never shows
        # (or saves) edits made to the previous version of its playbook.
        sid = f"{pb.session_id}-{pb.generated_at}"
        pb.title = st.text_input("Title", pb.title, key=f"{sid}-title")
        pb.goal = st.text_area("Goal", pb.goal, key=f"{sid}-goal", height=70)
        flagged = [s for s in pb.steps if s.needs_review]
        c = st.columns(4)
        c[0].metric("Steps", len(pb.steps))
        c[1].metric("Need review", len(flagged), help=f"Confidence below {pb.threshold:.2f}, or something looked inconsistent")
        c[2].metric("Reviewed", sum(s.review != "unreviewed" for s in pb.steps),
                    help="Steps you marked correct or wrong. These labels can later train confidence calibration.")
        c[3].metric("Model", pb.model)
        for note in pb.notes:
            st.info(note)

        video_col, steps_col = st.columns([2, 3])
        with video_col:
            if pb.video and (session_dir / pb.video).exists():
                st.video(str(session_dir / pb.video), start_time=int(ss.seek))
                st.caption(f"Jumped to {fmt_ts(ss.seek)}. Use the ▶ buttons to seek.")
            if pb.open_questions:
                st.markdown("**Open questions**\n" + "\n".join(f"- {q}" for q in pb.open_questions))
            if pb.inputs:
                st.markdown("**Inputs**\n" + "\n".join(f"- `{i.name}` (e.g. {i.example})" for i in pb.inputs))

        with steps_col:
            only_flagged = st.toggle("Show only steps needing review", value=False)
            for s in pb.steps:
                if only_flagged and not s.needs_review:
                    continue
                with st.container(border=True):
                    head, btn = st.columns([5, 1])
                    badge = {"correct": "✅", "wrong": "❌"}.get(s.review) or ("⚠️" if s.confidence < pb.threshold else "🔎" if s.review_note else "🟢")
                    head.markdown(f"**Step {s.index}** · {badge} {s.confidence:.2f} · `{s.action}`")
                    if btn.button(f"▶ {fmt_ts(s.t_start)}", key=f"{sid}-seek-{s.index}"):
                        ss.seek = int(s.t_start)
                        st.rerun()
                    if s.review == "wrong" or (s.needs_review and s.review != "correct"):
                        reasons = "\n".join(f"- {r}" for r in review_reasons(s, pb.threshold))
                        st.warning(f"**Needs review**\n{reasons}\n\n*Evidence:* {s.evidence or '—'}"
                                   + (f"\n\n*Adjustments:* {'; '.join(s.calibration_notes)}" if s.calibration_notes else ""))
                    img_col, txt_col = st.columns([2, 3])
                    shot = s.keyframe_after or s.keyframe_before
                    if shot and (session_dir / shot).exists():
                        img_col.image(str(session_dir / shot))
                    s.title = txt_col.text_input("Title", s.title, key=f"{sid}-t-{s.index}")
                    s.description = txt_col.text_area("Instruction", s.description, key=f"{sid}-d-{s.index}", height=90)
                    labels = {"unreviewed": "Not reviewed", "correct": "✅ Correct", "wrong": "❌ Wrong"}
                    s.review = txt_col.radio("Your review", list(labels), index=list(labels).index(s.review),
                                             format_func=labels.get, horizontal=True, key=f"{sid}-v-{s.index}")

        md = render_markdown(pb)
        a, b = st.columns(2)
        if a.button("💾 Save edits", type="primary"):
            write_playbook(pb, session_dir)
            st.success(f"Saved {session_dir / 'playbook.md'}")
        b.download_button("⬇ Download playbook.md", md, file_name=f"{pb.session_id}-playbook.md", mime="text/markdown")
        st.caption(f"Interactive viewer (video + clickable steps): `{session_dir / 'playbook.html'}`. Open it in a browser.")
        with st.expander("Markdown preview (source)"):
            st.code(md, language="markdown")
