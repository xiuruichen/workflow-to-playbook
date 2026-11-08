"""Live test: record real sessions of a real window with real mouse input, then run the pipeline.

Unlike `python -m playbook.dashboard` (drawn frames fed through the recorder's logic), this opens
a real full-screen window, records it with the real screen capture and OS input hooks, and drives
it with real mouse clicks. The "person" is still a script that follows the planted rule, so it
tests capture and the decision pipeline on real screens, not on a human's behaviour.

It takes over the mouse for several minutes. Press Esc in the window to abort. Recordings go to a
temporary folder; delete it when done. Run:  python scripts/live_dashboard_test.py [visits] [seed]
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook import induce, replay  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.dashboard import Visit, make_visits  # noqa: E402
from playbook.decisions import NONE, pool  # noqa: E402
from playbook.recorder import Recorder, _enable_dpi_awareness, foreground_window  # noqa: E402

TITLE = "Run 7 - Training dashboard"
DWELL_S = 11.5


class Abort(Exception):
    pass


def bring_to_front(root: tk.Tk) -> None:
    """Windows refuses to let a background process take the foreground (our window stayed behind the terminal
    that started this script, and the guard in `click` then, rightly, stopped the run). A synthetic Alt key
    press first makes the process eligible, which is the usual workaround."""
    import ctypes

    u = ctypes.windll.user32
    u.keybd_event(0x12, 0, 0, 0)
    u.keybd_event(0x12, 0, 2, 0)
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)


class App:
    def __init__(self) -> None:
        _enable_dpi_awareness()  # same physical-pixel coordinates as the recorder and the mouse
        from pynput import mouse

        self.mouse = mouse.Controller()
        self.Button = mouse.Button
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg="white")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.bind("<Escape>", lambda e: setattr(self, "aborted", True))
        self.aborted = False
        self.stopped = False
        font = ("Segoe UI", -110, "bold")
        self.title = tk.Label(self.root, text="pretrain-sweep / run-7", font=("Segoe UI", -70), bg="white", anchor="w")
        self.title.place(relx=0.04, rely=0.04)
        self.labels = {}
        for i, name in enumerate(["Spikes", "Batch size", "Loss"]):
            lab = tk.Label(self.root, text="", font=font, bg="white", anchor="w")
            lab.place(relx=0.04, rely=0.20 + 0.20 * i)
            self.labels[name] = lab
        self.status = tk.Label(self.root, text="", font=("Segoe UI", -80, "bold"), bg="white", fg="#b02020")
        self.status.place(relx=0.04, rely=0.82)
        self.button = tk.Button(self.root, text="Stop run", font=("Segoe UI", -80, "bold"), bg="#3c3cc8", fg="white",
                                command=self._stop)
        self.button.place(relx=0.62, rely=0.76, relwidth=0.30, relheight=0.14)
        self.pump(1.0)

    def _stop(self) -> None:
        self.stopped = True
        self.status.config(text="Run stopped")

    def show(self, v: Visit) -> None:
        self.stopped = False
        self.status.config(text="")
        for name, value in [("Spikes", str(v.spikes)), ("Batch size", str(v.batch_size)), ("Loss", f"{v.loss:.2f}")]:
            self.labels[name].config(text=f"{name}: {value}")
        self.root.lift()
        self.root.focus_force()
        bring_to_front(self.root)
        self.pump(0.8)

    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            if self.aborted:
                raise Abort()
            time.sleep(0.03)

    def click(self, x: int, y: int) -> None:
        """A real click, but only while our window is the foreground one: never click into another app."""
        fg = foreground_window()
        if fg is None or TITLE not in (fg[2] or ""):
            raise Abort(f"our window is not in front ({fg}); stopping so no click lands elsewhere")
        self.mouse.position = (x, y)
        self.pump(0.3)
        self.mouse.press(self.Button.left)
        self.pump(0.08)
        self.mouse.release(self.Button.left)
        self.pump(0.3)

    def button_center(self) -> tuple[int, int]:
        b = self.button
        return b.winfo_rootx() + b.winfo_width() // 2, b.winfo_rooty() + b.winfo_height() // 2


def stop_while_pumping(app: App, rec: Recorder) -> None:
    """Stop the recorder without freezing our own window: the recorder reads the foreground window's title,
    and asking a window of this same process while its thread is blocked would stall the capture loop."""
    import threading

    t = threading.Thread(target=rec.stop)
    t.start()
    while t.is_alive():
        app.pump(0.1)
    t.join()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # window titles can hold any character
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    root = Path(tempfile.mkdtemp(prefix="live_dashboard_"))
    settings = get_settings().model_copy(update={"sessions_dir": root / "sessions", "cache_dir": root / "cache"})
    visits = make_visits(n, seed)
    print(f"{n} live visits (seed {seed}); recordings in {root}. Hands off the mouse. Esc in the window aborts.", flush=True)
    app = App()
    sessions: list[Path] = []
    log = []
    try:
        for i, v in enumerate(visits):
            app.show(v)
            rec = Recorder(settings)
            session = rec.start()
            app.pump(1.5)
            app.click(app.root.winfo_rootx() + 300, app.root.winfo_rooty() + 120)  # an ordinary click: the visit starts
            app.pump(DWELL_S)  # looks at the numbers
            if v.stop:
                app.click(*app.button_center())
                app.pump(1.5)
            else:
                app.pump(2.5)
            stop_while_pumping(app, rec)
            sessions.append(session)
            log.append({"visit": i, "truth": vars(v) | {"stop": v.stop}, "clicked_stop": app.stopped})
            print(f"visit {i + 1}/{n}: spikes={v.spikes} batch={v.batch_size} -> {'stop' if v.stop else 'leave'} "
                  f"(button pressed: {app.stopped})", flush=True)
    except Abort as exc:
        print(f"ABORTED: {exc}", flush=True)
    finally:
        app.root.destroy()
    if not sessions:
        return 1

    print("\nReading decisions from the real recordings (local OCR)...", flush=True)
    t0 = time.time()
    decisions = pool(sessions)
    print(f"{len(decisions)} decisions from {len(sessions)} recordings in {time.time() - t0:.0f}s", flush=True)
    rows, ok_readouts, ok_outcome = [], 0, 0
    per_session = {s.name: sum(d.session == s.name for d in decisions) for s in sessions}
    by_session = {s.name: entry for s, entry in zip(sessions, log)}
    for d in decisions:
        entry = by_session[d.session]
        t = entry["truth"]
        good_read = (d.readouts.get("spikes") == t["spikes"] and d.readouts.get("batch_size") == t["batch_size"])
        good_out = (d.outcome != NONE) == t["stop"]
        ok_readouts += good_read
        ok_outcome += good_out
        rows.append({"visit": entry["visit"], "truth": t, "readouts": d.readouts, "outcome": d.outcome,
                     "dwell_s": round(d.dwell_s, 1), "readouts_ok": good_read, "outcome_ok": good_out})
    summary = {"visits_recorded": len(sessions), "decisions": len(decisions), "decisions_per_recording": sorted(set(per_session.values())),
               "readouts_correct": f"{ok_readouts}/{len(decisions)}", "outcomes_correct": f"{ok_outcome}/{len(decisions)}",
               "events_per_session": [sum(1 for _ in open(x / "events.jsonl", encoding="utf-8")) for x in sessions][:5]}
    if len(decisions) >= 10:
        tree = induce.fit(decisions[: int(len(decisions) * 0.7)])
        summary["rule_fitted_on_earliest_70pct"] = induce.rules(tree)
        summary["replay"] = replay.run(decisions)["arms"]
    (root / "live_results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    for r in rows:
        if not (r["readouts_ok"] and r["outcome_ok"]):
            print("MISMATCH", json.dumps(r), flush=True)
    print(f"\nFull results: {root / 'live_results.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
