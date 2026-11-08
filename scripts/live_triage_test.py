"""Live test, second domain: record real sessions of a real window with real mouse input (invoice triage).

Same idea as live_dashboard_test.py, with the rule of playbook/triage.py: three outcomes (Escalate,
Approve, leave alone), a word on screen (vendor Known/New) and a cross-session exception. The "person"
is a script following the planted rule, so this tests capture and the decision pipeline on real screens.

It takes over the mouse for several minutes. Press Esc in the window to abort. Recordings go to a
temporary folder; delete it when done. Run:  python scripts/live_triage_test.py [visits] [seed]
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_dashboard_test import Abort, bring_to_front, stop_while_pumping  # noqa: E402

from playbook import induce, replay  # noqa: E402
from playbook.config import get_settings  # noqa: E402
from playbook.decisions import NONE, pool  # noqa: E402
from playbook.recorder import Recorder, _enable_dpi_awareness, foreground_window  # noqa: E402
from playbook.triage import TITLE, Visit, make_visits  # noqa: E402

DWELL_S = 11.5


class App:
    def __init__(self) -> None:
        _enable_dpi_awareness()
        from pynput import mouse

        self.mouse = mouse.Controller()
        self.Button = mouse.Button
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg="white")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.aborted = False
        self.pressed: str | None = None
        self.root.bind("<Escape>", lambda e: setattr(self, "aborted", True))
        tk.Label(self.root, text="AP / overdue / top of queue", font=("Segoe UI", -70), bg="white").place(relx=0.04, rely=0.04)
        self.labels = {}
        for i, name in enumerate(["Amount", "Days overdue", "Vendor"]):
            lab = tk.Label(self.root, text="", font=("Segoe UI", -110, "bold"), bg="white", anchor="w")
            lab.place(relx=0.04, rely=0.20 + 0.20 * i)
            self.labels[name] = lab
        self.status = tk.Label(self.root, text="", font=("Segoe UI", -80, "bold"), bg="white", fg="#b02020")
        self.status.place(relx=0.04, rely=0.82)
        self.buttons = {}
        for name, color, relx in (("Escalate", "#3c3cc8", 0.40), ("Approve", "#3c963c", 0.70)):
            self.buttons[name] = tk.Button(self.root, text=name, font=("Segoe UI", -80, "bold"), bg=color, fg="white",
                                           command=lambda n=name: self._press(n))
            self.buttons[name].place(relx=relx, rely=0.76, relwidth=0.26, relheight=0.14)
        self.pump(1.0)

    def _press(self, name: str) -> None:
        self.pressed = name
        self.status.config(text=f"{name} recorded")

    def show(self, v: Visit) -> None:
        self.pressed = None
        self.status.config(text="")
        for name, value in [("Amount", str(v.amount)), ("Days overdue", str(v.days_overdue)), ("Vendor", v.vendor)]:
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

    def center(self, name: str) -> tuple[int, int]:
        b = self.buttons[name]
        return b.winfo_rootx() + b.winfo_width() // 2, b.winfo_rooty() + b.winfo_height() // 2


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # window titles can hold any character
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    root = Path(tempfile.mkdtemp(prefix="live_triage_"))
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
            app.pump(DWELL_S)  # reads the invoice
            if v.outcome != "none":
                app.click(*app.center(v.outcome))
                app.pump(1.5)
            else:
                app.pump(2.5)
            stop_while_pumping(app, rec)
            sessions.append(session)
            log.append({"visit": i, "truth": vars(v) | {"outcome": v.outcome}, "pressed": app.pressed})
            print(f"visit {i + 1}/{n}: amount={v.amount} days={v.days_overdue} vendor={v.vendor} -> {v.outcome} (pressed: {app.pressed})", flush=True)
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

    def norm(o: str) -> str:
        return NONE if o == NONE else o.lower().replace(" ", "")

    for d in decisions:
        entry = by_session[d.session]
        t = entry["truth"]
        good_read = (d.readouts.get("amount") == t["amount"] and d.readouts.get("days_overdue") == t["days_overdue"]
                     and d.cats.get("vendor") == t["vendor"].lower())
        good_out = norm(d.outcome) == t["outcome"].lower()
        ok_readouts += good_read
        ok_outcome += good_out
        rows.append({"visit": entry["visit"], "truth": t, "readouts": d.readouts, "cats": d.cats, "outcome": d.outcome,
                     "dwell_s": round(d.dwell_s, 1), "readouts_ok": good_read, "outcome_ok": good_out})
    summary = {"visits_recorded": len(sessions), "decisions": len(decisions), "decisions_per_recording": sorted(set(per_session.values())),
               "readouts_correct": f"{ok_readouts}/{len(decisions)}", "outcomes_correct": f"{ok_outcome}/{len(decisions)}"}
    if len(decisions) >= 10:
        cut = int(len(decisions) * 0.7)
        for name, la in (("greedy", False), ("lookahead", True)):
            tree = induce.fit(decisions[:cut], lookahead=la)
            summary[f"rule_{name}_fitted_on_earliest_70pct"] = induce.rules(tree)
            summary[f"test_accuracy_{name}"] = induce.accuracy(tree, decisions[cut:])
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
