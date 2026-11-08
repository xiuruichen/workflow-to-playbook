"""Interactive end-to-end smoke test: a real window, the real recorder, real mouse clicks, one long recording.

A "person" (a human, or an AI reading `current.json`) judges cases one at a time by their own hidden rule. They
write 'A' (kill) or 'L' (keep) into `decision.txt`; this script then clicks the matching button with the real mouse,
exactly as a person would, while the recorder captures the screen and input. Afterwards the whole pipeline runs on
the one recording: decision log (dwell + navigation), rule fit, report. Nothing here knows the person's rule.

    python scripts/live_hidden_rule_test.py OUT_DIR [cases] [seed]

Protocol with the person: wait for OUT_DIR/current.json to change index, read it, write A or L (or S for a
screenshot of the screen, Q to finish early) to OUT_DIR/decision.txt. Hands off the mouse while it runs; Esc in the
window aborts.
"""

from __future__ import annotations

import json
import random
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_dashboard_test import Abort, bring_to_front, stop_while_pumping  # noqa: E402

from playbook.config import get_settings  # noqa: E402
from playbook.decisions import add_context, build_decisions, save_decisions  # noqa: E402
from playbook.recorder import Recorder, _enable_dpi_awareness, foreground_window  # noqa: E402

TITLE = "Experiment tracker - Run review"
KILL, KEEP = "Kill run", "Keep run"


def make_cases(n: int, seed: int) -> list[dict]:
    """Experiment runs with a decoy readout (grad norm), a decoy clock and a run id; now and then the same run again."""
    rng = random.Random(seed)
    cases, run_id = [], 4800
    for i in range(n):
        again = cases and rng.random() < 0.3
        if again:
            prev = dict(cases[-1])
            prev["epoch"] += 1
            prev["gpu"] = max(5, min(98, prev["gpu"] + rng.randint(-4, 4)))
            prev["grad"] = round(abs(prev["grad"] + rng.uniform(-0.4, 0.4)), 2)
            cases.append(prev)
            continue
        run_id += rng.randint(1, 37)
        train = round(rng.uniform(0.3, 2.0), 2)
        ratio = rng.choice([0.95, 1.0, 1.05, 1.12, 1.2, 1.3, 1.45, 1.7])
        cases.append({"run_id": run_id, "epoch": rng.randint(1, 30), "train": train, "val": round(train * ratio, 2),
                      "gpu": rng.choice([12, 18, 24, 28, 35, 48, 62, 77, 91]) + rng.randint(0, 3),
                      "grad": round(rng.uniform(0.1, 5.0), 2), "owner": rng.choice(["Alice", "Bob", "Carol"])})
    return cases


def lines(c: dict, clock: str) -> list[str]:
    return [f"Run ID: {c['run_id']}", f"Epoch: {c['epoch']}", f"Train loss: {c['train']:.2f}", f"Val loss: {c['val']:.2f}",
            f"GPU util: {c['gpu']}", f"Grad norm: {c['grad']:.2f}", f"Owner: {c['owner']}", f"Clock: {clock}"]


class App:
    def __init__(self) -> None:
        _enable_dpi_awareness()
        from pynput import mouse

        self.mouse, self.Button = mouse.Controller(), mouse.Button
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg="white")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.aborted = False
        self.root.bind("<Escape>", lambda e: setattr(self, "aborted", True))
        tk.Label(self.root, text="Experiment tracker / run review", font=("Segoe UI", -56), bg="white").place(relx=0.04, rely=0.03)
        self.rows = [tk.Label(self.root, text="", font=("Segoe UI", -70, "bold"), bg="white", anchor="w") for _ in range(8)]
        for i, lab in enumerate(self.rows):
            lab.place(relx=0.04, rely=0.13 + 0.092 * i)
        self.pressed: str | None = None
        self.buttons = {}
        for name, color, relx in ((KILL, "#b02020", 0.52), (KEEP, "#3c8c3c", 0.76)):
            self.buttons[name] = tk.Button(self.root, text=name, font=("Segoe UI", -64, "bold"), bg=color, fg="white",
                                           command=lambda n=name: setattr(self, "pressed", n))
            self.buttons[name].place(relx=relx, rely=0.78, relwidth=0.21, relheight=0.14)
        self.pump(1.0)

    def show(self, text_lines: list[str]) -> None:
        self.pressed = None
        for lab, t in zip(self.rows, text_lines):
            lab.config(text=t)
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
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out = Path(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    out.mkdir(parents=True, exist_ok=True)
    settings = get_settings().model_copy(update={"sessions_dir": out / "sessions", "cache_dir": out / "cache"})
    cases = make_cases(n, seed)
    cur, dec = out / "current.json", out / "decision.txt"
    for f in (cur, dec):
        f.unlink(missing_ok=True)
    app = App()
    rec = Recorder(settings)
    session = rec.start()
    log, t_start = [], time.time()
    print(f"recording {session}; {n} cases", flush=True)
    try:
        app.show(lines(cases[0], time.strftime("%H:%M")))
        app.pump(1.5)
        app.click(app.root.winfo_rootx() + 400, app.root.winfo_rooty() + 90)  # an ordinary first click: the session starts with an action
        for i, c in enumerate(cases):
            shown = lines(c, time.strftime("%H:%M"))
            app.show(shown)
            tmp = out / "current.tmp"
            tmp.write_text(json.dumps({"index": i, "of": n, "lines": shown}), encoding="utf-8")
            tmp.replace(cur)
            while True:  # wait for the person; keep the window alive
                app.pump(0.25)
                if dec.exists():
                    ans = dec.read_text(encoding="utf-8").strip().upper()[:1]
                    dec.unlink()
                    if ans == "S":
                        import mss
                        from PIL import Image

                        with mss.mss() as sct:
                            shot = sct.grab(sct.monitors[1])
                            Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX").resize((960, 540)).save(out / "screen.png")
                        continue
                    if ans in ("A", "L", "Q"):
                        break
            if ans == "Q":
                break
            name = KILL if ans == "A" else KEEP
            app.click(*app.center(name))
            app.pump(0.8)
            log.append({"index": i, "case": c, "choice": name, "t": round(time.time() - t_start, 1), "pressed": app.pressed})
            print(f"case {i + 1}/{n}: {name} (pressed {app.pressed})", flush=True)
        stop_while_pumping(app, rec)
    except Abort as exc:
        print(f"ABORTED: {exc}", flush=True)
        stop_while_pumping(app, rec)
    finally:
        app.root.destroy()
    (out / "choices.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(f"recorded {len(log)} choices in {time.time() - t_start:.0f}s; reading the recording (OCR)...", flush=True)

    t0 = time.time()
    found = build_decisions(session, dwell_min_s=3.0, navigation=(KEEP,))
    save_decisions(found, session / "decisions.jsonl")
    print(f"pipeline: {len(found)} decisions from {len(log)} choices in {time.time() - t0:.0f}s", flush=True)
    (out / "pipeline_done.txt").write_text("done", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
