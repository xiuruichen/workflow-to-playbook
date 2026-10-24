"""Command-line interface.

    python -m playbook run                 # record -> analyze -> playbook.md
    python -m playbook record              # record only
    python -m playbook import video.mp4    # build a playbook from an existing recording
    python -m playbook analyze [session]   # (re)analyze a session (default: latest)
    python -m playbook render [session]    # re-render playbook.md from playbook.json, no API calls
    python -m playbook list                # list sessions
    python -m playbook check               # test the API key and which models have free quota
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import get_settings


def _progress(frac: float, msg: str) -> None:
    bar = "#" * int(frac * 30)
    print(f"\r[{bar:<30}] {frac * 100:5.1f}%  {msg[:70]:<70}", end="", flush=True)
    if frac >= 1.0:
        print()


def _analyze_and_render(session: Path) -> int:
    from .analyzer import AnalysisError, analyze_session
    from .generator import write_playbook

    try:
        pb = analyze_session(session, progress=_progress)
    except AnalysisError as exc:
        print(f"\nAnalysis failed: {exc}", file=sys.stderr)
        return 1
    path = write_playbook(pb, session)
    print(f"\nPlaybook: {path}")
    print(f"  {len(pb.steps)} steps, {len(pb.review_steps)} need review")
    for s in pb.review_steps:
        why = "low confidence" if s.confidence < pb.threshold else "check"
        print(f"   ⚠ Step {s.index} @ {s.t_start:.0f}s ({why}, {s.confidence:.2f}): {s.title}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="python -m playbook", description="Turn screen recordings into Markdown playbooks.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="record, then analyze and write the playbook")
    sub.add_parser("record", help="record a session only")
    imp = sub.add_parser("import", help="create a playbook from an existing video file")
    imp.add_argument("video", type=Path)
    imp.add_argument("--no-analyze", action="store_true", help="only extract keyframes")
    for name in ("analyze", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("session", nargs="?", default="latest", help="session id, path, or 'latest'")
    sub.add_parser("list", help="list recorded sessions")
    sub.add_parser("check", help="test the API key and which models currently work")
    args = p.parse_args(argv)

    from .recorder import import_video, list_sessions, record_session, resolve_session

    settings = get_settings()
    if args.cmd in ("run", "record"):
        if args.cmd == "run" and not settings.gemini_api_key:
            print("GEMINI_API_KEY is not set (see .env.example). Use `record` to capture without analyzing.", file=sys.stderr)
            return 1
        session = record_session(settings)
        print(f"Session saved: {session}")
        return _analyze_and_render(session) if args.cmd == "run" else 0
    if args.cmd == "import":
        if not args.video.is_file():
            print(f"No such file: {args.video}", file=sys.stderr)
            return 1
        session = import_video(args.video, settings, progress=_progress)
        print(f"\nSession created: {session}")
        return 0 if args.no_analyze else _analyze_and_render(session)
    if args.cmd == "analyze":
        return _analyze_and_render(resolve_session(args.session, settings))
    if args.cmd == "render":
        from .generator import render_session

        print(render_session(resolve_session(args.session, settings)))
        return 0
    if args.cmd == "check":
        from .analyzer import AnalysisError, check_models

        try:
            results = check_models(settings)
        except AnalysisError as exc:
            print(exc, file=sys.stderr)
            return 1
        for model, ok, detail in results:
            mark = "OK  " if ok else "FAIL"
            star = "  <- GEMINI_MODEL" if model == settings.gemini_model else ""
            print(f"{mark} {model:<28} {detail}{star}")
        working = [m for m, ok, _ in results if ok]
        if not working:
            print("\nNo model works right now. Free-tier quotas reset daily (midnight Pacific).")
            return 1
        if settings.gemini_model not in working:
            print(f"\nTip: set GEMINI_MODEL={working[0]} in .env (the analyzer also falls back automatically).")
        return 0
    if args.cmd == "list":
        for s in list_sessions(settings):
            status = "playbook" if (s / "playbook.md").exists() else "not analyzed"
            print(f"{s.name:<28} {status}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
