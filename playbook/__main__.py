"""Command-line interface.

    python -m playbook setup-local         # one-time: pick + download a local vision model (Ollama)
    python -m playbook run                 # record -> analyze -> playbook.md
    python -m playbook record              # record only
    python -m playbook import video.mp4    # build a playbook from an existing recording
    python -m playbook analyze [session]   # (re)analyze a session (default: latest)
    python -m playbook render [session]    # re-render playbook.md from playbook.json, no model calls
    python -m playbook list                # list sessions (🔒 = archived)
    python -m playbook compact [session]   # compress + encrypt sessions into .pbx archives
    python -m playbook restore <session>   # decrypt + restore an archived session
    python -m playbook migrate             # move old sessions out of the project (OneDrive) folder
    python -m playbook key --export        # back up the archive key
    python -m playbook check               # is the model reachable? (local: Ollama status)
    python -m playbook labels              # export your step reviews (correct/wrong) to labels.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PROJECT_ROOT, get_settings


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
    if get_settings().auto_compact == "after_analysis":
        _compact_one(session)
    return 0


def _compact_one(session: Path, video: str | None = None) -> int:
    from .archive import ArchiveError, compact

    try:
        res = compact(session, get_settings(), video=video, status=lambda m: print(f"  {m}"))
    except ArchiveError as exc:
        print(f"Could not archive {session.name}: {exc}", file=sys.stderr)
        return 1
    print(f"Archived {session.name} -> {res.archive}\n{res.report()}")
    return 0


def _auto_compact_idle() -> None:
    """AUTO_COMPACT=idle:<days>: archive sessions nobody has touched for a while."""
    from .archive import ArchiveError, compact_idle, idle_days

    s = get_settings()
    try:
        days = idle_days(s)
        if days is None:
            return
        for res in compact_idle(s, days, status=lambda m: print(m)):
            print(f"  archived {res.archive.name}: {res.before / 1e6:.1f} MB -> {res.after / 1e6:.1f} MB")
    except ArchiveError as exc:
        print(f"(Automatic archiving skipped: {exc})", file=sys.stderr)


def _list_line(path: Path) -> str:
    from .recorder import is_archived

    if not is_archived(path):
        status = "playbook" if (path / "playbook.md").exists() else "not analyzed"
        return f"   {path.name:<28} {status}"
    try:
        from .archive import summary

        info = summary(path)
        status = ("playbook" if info.get("analyzed") else "not analyzed") + (f" · {info['title']}" if info.get("title") else "")
    except Exception as exc:  # wrong key, damaged file
        status = f"(can't read: {exc})"
    return f"🔒 {path.stem:<28} {status}"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="python -m playbook", description="Turn screen recordings into Markdown playbooks.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sl = sub.add_parser("setup-local", help="pick and download a local vision model that fits this computer")
    sl.add_argument("--model", help="Ollama tag to use instead of the automatic choice, e.g. qwen3-vl:2b-instruct")
    sl.add_argument("--yes", action="store_true", help="don't ask before downloading")
    sub.add_parser("run", help="record, then analyze and write the playbook")
    sub.add_parser("record", help="record a session only")
    imp = sub.add_parser("import", help="create a playbook from an existing video file")
    imp.add_argument("video", type=Path)
    imp.add_argument("--no-analyze", action="store_true", help="only extract keyframes")
    for name in ("analyze", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("session", nargs="?", default="latest", help="session id, path, or 'latest'")
    sub.add_parser("list", help="list recorded sessions")
    cp = sub.add_parser("compact", help="compress + encrypt sessions into .pbx archives")
    cp.add_argument("session", nargs="?", help="session id or path")
    cp.add_argument("--all", action="store_true", help="every session that isn't archived yet")
    cp.add_argument("--idle-days", type=float, help="sessions not touched for this many days")
    cp.add_argument("--video", choices=["compress", "original", "drop"], help="how to store the video (default: ARCHIVE_VIDEO)")
    cp.add_argument("--bench", action="store_true", help="measure compression on a copy; the session is left as is")
    rs = sub.add_parser("restore", help="decrypt + restore an archived session")
    rs.add_argument("session", help="session id or path to the .pbx")
    mg = sub.add_parser("migrate", help="move sessions from the old project-folder location to the local data folder")
    mg.add_argument("--no-compact", action="store_true", help="move without archiving")
    ky = sub.add_parser("key", help="show, back up or import the archive encryption key")
    ky.add_argument("--export", action="store_true", help="print the key so you can store it somewhere safe")
    ky.add_argument("--import", dest="import_key", metavar="BACKUP", help="install a key printed by --export")
    sub.add_parser("check", help="test that the vision model is reachable")
    lab = sub.add_parser("labels", help="export reviewed steps (correct/wrong) as training data for calibration")
    lab.add_argument("--out", type=Path, default=Path("labels.csv"))
    args = p.parse_args(argv)

    from .recorder import import_video, is_archived, list_sessions, record_session, resolve_session

    settings = get_settings()
    if args.cmd == "setup-local":
        from .local_setup import setup

        return setup(settings, model=args.model, assume_yes=args.yes)
    if args.cmd in ("run", "record", "import", "analyze", "list"):
        _auto_compact_idle()
    if args.cmd in ("run", "record"):
        if args.cmd == "run":
            from .backend import resolve_backend
            from .security import SecurityError

            try:
                resolve_backend(settings)
            except SecurityError as exc:
                print(exc, file=sys.stderr)
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
    if args.cmd == "labels":
        from .labels import export_labels

        n = export_labels(list_sessions(settings), args.out)
        print(f"Wrote {n} reviewed step(s) to {args.out}")
        return 0
    if args.cmd == "compact":
        if args.bench:
            from .archive import bench

            target = resolve_session(args.session or "latest", settings)
            print(bench(target, settings, status=lambda m: print(f"  {m}")))
            return 0
        if args.idle_days is not None:
            from .archive import compact_idle

            n = len(compact_idle(settings, args.idle_days, status=print))
            print(f"Archived {n} session(s).")
            return 0
        targets = ([s for s in list_sessions(settings) if not is_archived(s)] if args.all
                   else [resolve_session(args.session or "latest", settings, restore=False)])
        if not targets:
            print("Nothing to archive.")
        rc = 0
        for t in targets:
            if is_archived(t):
                print(f"{t.stem} is already archived.")
                continue
            rc |= _compact_one(t, args.video)
        return rc
    if args.cmd == "restore":
        from .archive import ArchiveError

        try:
            print(f"Restored: {resolve_session(args.session, settings)}")
        except (ArchiveError, FileNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    if args.cmd == "migrate":
        from .archive import migrate

        old = [PROJECT_ROOT / "sessions"]
        n = migrate(settings, old, compact_after=not args.no_compact)
        old_cache = PROJECT_ROOT / ".cache"
        if old_cache.exists() and old_cache.resolve() != settings.cache_dir.resolve():
            import shutil

            settings.cache_dir.mkdir(parents=True, exist_ok=True)
            for f in old_cache.glob("*.json"):
                if not (settings.cache_dir / f.name).exists():
                    shutil.move(str(f), str(settings.cache_dir / f.name))
            print(f"Moved the response cache to {settings.cache_dir}")
        print(f"Moved {n} session(s) to {settings.sessions_dir}.")
        print("If the old folder was in OneDrive/Dropbox, the cloud service may still keep copies in its "
              "recycle bin / version history: empty those too.")
        return 0
    if args.cmd == "key":
        from .archive import ArchiveError, default_key, import_key

        try:
            if args.import_key:
                k = import_key(args.import_key)
                print(f"Imported archive key {k.key_id}.")
                return 0
            k = default_key(settings, create=args.export)
        except ArchiveError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"Archive key {k.key_id} ({'OS keyring' if k.kind == 'keyring' else 'ARCHIVE_PASSPHRASE'})")
        if args.export and k.kind == "keyring":
            print("Backup (anyone with this can decrypt your archives; store it like a password):")
            print(k.export())
        return 0
    if args.cmd == "check":
        from .analyzer import AnalysisError, check_models
        from .backend import resolve_backend
        from .security import SecurityError

        try:
            backend = resolve_backend(settings)
        except SecurityError as exc:
            print(exc, file=sys.stderr)
            return 1
        if backend.local:
            from .local_setup import status

            lines = status(settings)
            print("\n".join(lines))
            return 0 if all(not ln.startswith("FAIL") for ln in lines) else 1
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
        print(f"Sessions in {settings.sessions_dir}:")
        for s in list_sessions(settings):
            print(_list_line(s))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
