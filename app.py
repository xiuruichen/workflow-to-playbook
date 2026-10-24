"""Streamlit UI: capture -> analyze -> review/edit the playbook.

    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from playbook.analyzer import AnalysisError, analyze_session, check_models, fmt_ts
from playbook.config import get_settings
from playbook.generator import render_markdown, review_reasons, write_playbook
from playbook.models import Manifest, Playbook
from playbook.recorder import Recorder, import_video, list_sessions

st.set_page_config(page_title="Workflow → Playbook", page_icon="📘", layout="wide")
settings = get_settings()
ss = st.session_state
ss.setdefault("rec", None)
ss.setdefault("session", None)
ss.setdefault("seek", 0)


def select_session(path: Path) -> None:
    ss.session = str(path)
    ss.seek = 0


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("📘 Workflow → Playbook")
    st.caption("Record how you do a task; get a step-by-step playbook with timestamps and review flags.")
    if settings.gemini_api_key:
        st.success(f"Gemini key loaded · `{settings.gemini_model}`")
    else:
        st.error("No GEMINI_API_KEY. Copy `.env.example` to `.env` and add a free key from aistudio.google.com/apikey.")
    st.caption(f"Review threshold: confidence < {settings.confidence_threshold:.2f} · {settings.rpm_limit} req/min")
    if settings.gemini_api_key and st.button("Test API connection", help="Sends a tiny request to each model to see which have free quota right now"):
        with st.spinner("Checking models…"):
            try:
                for model, ok, detail in check_models(settings):
                    (st.success if ok else st.caption)(f"{'✅' if ok else '❌'} `{model}`: {detail}")
            except AnalysisError as exc:
                st.error(str(exc))

    sessions = list_sessions(settings)
    if sessions:
        names = [p.name for p in sessions]
        current = Path(ss.session).name if ss.session else names[0]
        idx = names.index(current) if current in names else 0
        choice = st.selectbox("Session", names, index=idx, format_func=lambda n: n + (" ✓" if (settings.sessions_dir / n / "playbook.json").exists() else ""))
        if choice != current or not ss.session:
            select_session(settings.sessions_dir / choice)
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

# ---------------------------------------------------------------- analyze
with tab_analyze:
    if not session_dir or not (session_dir / "manifest.json").exists():
        st.info("Record or import a session first.")
    else:
        m = Manifest.load(session_dir)
        c = st.columns(4)
        c[0].metric("Duration", fmt_ts(m.duration))
        c[1].metric("Keyframes", len(m.keyframes))
        c[2].metric("Input events", len(m.events))
        c[3].metric("Source", m.source)
        n_calls = max(1, -(-(len(m.keyframes) - 1) // max(settings.window_size - 1, 1))) + 1
        st.caption(f"Analysis will make about {n_calls} vision API call(s); at {settings.rpm_limit}/min that takes ≈{n_calls / settings.rpm_limit:.1f} min. Responses are cached, so re-runs are free.")
        if st.button("🔍 Analyze with Gemini", type="primary", disabled=not settings.gemini_api_key):
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
    if not session_dir or not (session_dir / "playbook.json").exists():
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
        c[2].metric("Verified", sum(s.verified for s in pb.steps))
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
                    badge = "✅" if s.verified else ("⚠️" if s.confidence < pb.threshold else "🔎" if s.review_note else "🟢")
                    head.markdown(f"**Step {s.index}** · {badge} {s.confidence:.2f} · `{s.action}`")
                    if btn.button(f"▶ {fmt_ts(s.t_start)}", key=f"{sid}-seek-{s.index}"):
                        ss.seek = int(s.t_start)
                        st.rerun()
                    if s.needs_review and not s.verified:
                        reasons = "\n".join(f"- {r}" for r in review_reasons(s, pb.threshold))
                        st.warning(f"**Needs review**\n{reasons}\n\n*Evidence:* {s.evidence or '—'}"
                                   + (f"\n\n*Adjustments:* {'; '.join(s.calibration_notes)}" if s.calibration_notes else ""))
                    img_col, txt_col = st.columns([2, 3])
                    shot = s.keyframe_after or s.keyframe_before
                    if shot and (session_dir / shot).exists():
                        img_col.image(str(session_dir / shot))
                    s.title = txt_col.text_input("Title", s.title, key=f"{sid}-t-{s.index}")
                    s.description = txt_col.text_area("Instruction", s.description, key=f"{sid}-d-{s.index}", height=90)
                    s.verified = txt_col.checkbox("Verified by me", s.verified, key=f"{sid}-v-{s.index}")

        md = render_markdown(pb)
        a, b = st.columns(2)
        if a.button("💾 Save edits", type="primary"):
            write_playbook(pb, session_dir)
            st.success(f"Saved {session_dir / 'playbook.md'}")
        b.download_button("⬇ Download playbook.md", md, file_name=f"{pb.session_id}-playbook.md", mime="text/markdown")
        st.caption(f"Interactive viewer (video + clickable steps): `{session_dir / 'playbook.html'}`. Open it in a browser.")
        with st.expander("Markdown preview (source)"):
            st.code(md, language="markdown")
