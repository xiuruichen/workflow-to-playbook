"""Scripted, synthetic "live" recordings of different kinds of computer work.

Each scenario draws simple but realistic screens (editor + terminal, email client, file
explorer + settings, browser + spreadsheet), scripts the user's mouse/keyboard input and
window switches, and runs them through the real Recorder per-frame logic. The result is a
genuine live-style session (H.264 video, keyframes, input events with window titles,
manifest.json) with known ground truth, so `python -m playbook.evaluate` can measure how
well the pipeline generalises across activity types. All data is fictional.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .config import Settings
from .keyframes import resize_max_width
from .recorder import Recorder, _Raw

W, H = 1280, 720
FONT = cv2.FONT_HERSHEY_SIMPLEX
MONO = cv2.FONT_HERSHEY_PLAIN

# ---------------------------------------------------------------------------- drawing kit
DARK, LIGHT, MUTED, BLUE = (30, 30, 30), (245, 245, 245), (110, 110, 110), (200, 110, 30)


def canvas(color=(250, 250, 250)) -> np.ndarray:
    return np.full((H, W, 3), color, np.uint8)


def text(img, s, x, y, scale=0.65, color=DARK, thick=1, font=FONT):
    cv2.putText(img, s, (x, y), font, scale, color, thick, cv2.LINE_AA)


def box(img, x1, y1, x2, y2, fill=None, border=(190, 190, 190), t=1):
    if fill is not None:
        cv2.rectangle(img, (x1, y1), (x2, y2), fill, -1)
    if border is not None:
        cv2.rectangle(img, (x1, y1), (x2, y2), border, t)


def titlebar(img, title, bg=(235, 235, 235), fg=DARK):
    box(img, 0, 0, W, 34, fill=bg, border=None)
    text(img, title, 14, 23, 0.6, fg)
    text(img, "_   []   X", W - 120, 23, 0.55, fg)


def draw_cursor(img, x, y):
    pts = np.array([[x, y], [x, y + 22], [x + 6, y + 17], [x + 15, y + 17]], np.int32)
    cv2.fillPoly(img, [pts], (0, 0, 0))
    cv2.polylines(img, [pts], True, (255, 255, 255), 1)


# ---------------------------------------------------------------------------- script DSL
WindowInfo = tuple[int, str, str]


class Script:
    """Builds a timeline of screens, pointer positions, window focus and raw input."""

    def __init__(self, screen: np.ndarray, app: str, title: str):
        self.t = 0.0
        self.screens: list[tuple[float, np.ndarray]] = [(0.0, screen)]
        self.windows: list[tuple[float, WindowInfo]] = [(0.0, (1, app, title))]
        self.pointer: list[tuple[float, tuple[int, int]]] = [(0.0, (W // 2, H // 2))]
        self.raws: list[_Raw] = []
        self._next_hwnd = 2

    def wait(self, seconds: float) -> None:
        self.t += seconds

    def show(self, screen: np.ndarray, at: float | None = None) -> None:
        self.screens.append((self.t if at is None else at, screen))

    def window(self, app: str, title: str, hwnd: int | None = None, at: float | None = None) -> int:
        """Focus a window: a new one (hwnd=None), or an existing/same one to change its title."""
        if hwnd is None:
            hwnd, self._next_hwnd = self._next_hwnd, self._next_hwnd + 1
        self.windows.append((self.t if at is None else at, (hwnd, app, title)))
        return hwnd

    def click(self, x, y, then=None, hold=1.6, button="left", double=False):
        self.pointer.append((self.t, (x, y)))
        t = self.t + 0.3
        for _ in range(2 if double else 1):
            self.raws += [_Raw(t, "press", x, y, button=button), _Raw(t + 0.05, "release", x, y, button=button)]
            t += 0.2
        if then is not None:
            self.show(then, at=t + 0.2)
        self.t = t + hold

    def drag(self, x1, y1, x2, y2, then=None, hold=1.6):
        self.pointer.append((self.t, (x1, y1)))
        self.raws.append(_Raw(self.t + 0.3, "press", x1, y1, button="left"))
        self.pointer.append((self.t + 0.6, (x2, y2)))
        self.raws.append(_Raw(self.t + 0.9, "release", x2, y2, button="left"))
        if then is not None:
            self.show(then, at=self.t + 1.1)
        self.t += 0.9 + hold

    def type(self, s: str, then=None, hold=1.6, cps=12.0):
        for i, ch in enumerate(s):
            self.raws.append(_Raw(self.t + i / cps, "key", key="space" if ch == " " else ch))
        end = self.t + len(s) / cps
        if then is not None:
            self.show(then, at=end + 0.1)
        self.t = end + hold

    def key(self, name: str, then=None, hold=1.6, mods: tuple[str, ...] = ()):
        self.raws.append(_Raw(self.t, "key", key=name, mods=frozenset(mods)))
        if then is not None:
            self.show(then, at=self.t + 0.3)
        self.t += hold


@dataclass
class Scenario:
    name: str
    description: str
    build: Callable[[], Script]
    # Each expected step is a list of keywords that must all appear in one playbook step;
    # "a|b" accepts either alternative.
    expected_steps: list[list[str]]
    # Words identifying the planted mistake; empty when the scenario has none.
    mistake: list[str] = field(default_factory=list)


def _clear_dir(path: Path) -> None:
    """Delete a previous run's output. Sync tools (OneDrive) and virus scanners can hold files
    briefly on Windows, so retry, then fall back to deleting whatever files can be deleted."""
    for _ in range(5):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError:
            time.sleep(0.5)
    for f in path.rglob("*"):
        if f.is_file():
            f.unlink(missing_ok=True)


def simulate(scenario: Scenario, settings: Settings, session_dir: Path) -> Path:
    """Render the scenario to a live-style session directory (overwritten if it exists)."""
    import imageio_ffmpeg

    script = scenario.build()
    _clear_dir(session_dir)
    (session_dir / "keyframes").mkdir(parents=True, exist_ok=True)

    rec = Recorder(settings)
    rec.session_dir = session_dir
    rec._mon = {"left": 0, "top": 0}
    rec._reset_capture_state()
    current: list[WindowInfo] = [script.windows[0][1]]
    rec._window_fn = lambda: current[0]

    def latest(timeline, now):
        return [v for t, v in sorted(timeline, key=lambda tv: tv[0]) if t <= now][-1]

    fps = settings.capture_fps
    writer = imageio_ffmpeg.write_frames(
        str(session_dir / "recording.mp4"), (W, H), fps=fps, codec="libx264", pix_fmt_in="bgr24",
        quality=None, output_params=["-crf", "30", "-movflags", "+faststart"],
    )
    writer.send(None)
    raws = sorted(script.raws, key=lambda r: r.t)
    ri = 0
    n_frames = int((script.t + 1.5) * fps) + 1
    now, small = 0.0, None
    for i in range(n_frames):
        now = i / fps
        current[0] = latest(script.windows, now)
        frame = latest(script.screens, now).copy()
        draw_cursor(frame, *latest(script.pointer, now))
        writer.send(frame.tobytes())
        while ri < len(raws) and raws[ri].t <= now:
            rec._raw.put(raws[ri])
            ri += 1
        small = resize_max_width(frame, settings.max_image_width)
        rec._ring.append((now, small))
        rec._tick(now, small, first=i == 0)
    writer.close()
    rec._finish(now, small, W, H)
    return session_dir


# ---------------------------------------------------------------------------- 1. coding
CODE = ['def greet(name):', '    return f"Hello, {name}!"', '', 'user = "Ada"', 'print(greet(usr))']
CODE_FIXED = CODE[:4] + ['print(greet(user))']
PROMPT = "PS C:\\project> "


def vscode(code, term, dirty=False, selected=None):
    img = canvas((40, 33, 30))
    titlebar(img, ("* " if dirty else "") + "app.py - project - Visual Studio Code", bg=(60, 60, 60), fg=LIGHT)
    box(img, 0, 34, 220, H, fill=(52, 45, 42), border=None)
    text(img, "EXPLORER: PROJECT", 12, 64, 0.5, (200, 200, 200))
    text(img, "app.py", 30, 94, 0.55, LIGHT)
    text(img, "README.md", 30, 120, 0.55, (170, 170, 170))
    box(img, 220, 34, W, 70, fill=(48, 42, 39), border=None)
    text(img, "app.py" + (" *" if dirty else ""), 240, 58, 0.55, LIGHT)
    for i, line in enumerate(code, 1):
        y = 105 + (i - 1) * 32
        text(img, str(i), 240, y, 0.55, (130, 130, 130))
        if selected and i == selected[0]:
            x = 290 + int(cv2.getTextSize(line[: selected[1]], FONT, 0.65, 1)[0][0])
            w = int(cv2.getTextSize(line[selected[1]: selected[2]], FONT, 0.65, 1)[0][0])
            box(img, x - 2, y - 20, x + w + 2, y + 8, fill=(120, 80, 40), border=None)
        text(img, line, 290, y, 0.65, (220, 220, 220))
    box(img, 220, 420, W, H, fill=(30, 25, 22), border=(80, 80, 80))
    text(img, "TERMINAL", 240, 445, 0.5, (200, 200, 200))
    for i, line in enumerate(term[-8:]):
        text(img, line, 240, 480 + i * 28, 0.6, (225, 225, 225))
    return img


def coding_script() -> Script:
    t0 = [PROMPT]
    typo_err = [PROMPT + "pyhton app.py", "pyhton : The term 'pyhton' is not recognized as the name",
                "of a cmdlet, function, script file, or operable program.", PROMPT]
    name_err = typo_err[:-1] + [PROMPT + "python app.py", "Traceback (most recent call last):",
                                '  File "app.py", line 5, in <module>', "NameError: name 'usr' is not defined", PROMPT]
    success = name_err[:-1] + [PROMPT + "python app.py", "Hello, Ada!", PROMPT]
    title = "app.py - project - Visual Studio Code"

    s = Script(vscode(CODE, t0), "Code.exe", title)
    s.wait(1.5)
    s.click(700, 480)
    s.type("pyhton app.py", then=vscode(CODE, [PROMPT + "pyhton app.py"]))
    s.key("enter", then=vscode(CODE, typo_err), hold=2.5)
    s.type("python app.py", then=vscode(CODE, typo_err[:-1] + [PROMPT + "python app.py"]))
    s.key("enter", then=vscode(CODE, name_err), hold=3.0)
    s.click(420, 233, double=True, then=vscode(CODE, name_err, selected=(5, 12, 15)), hold=1.0)
    s.type("user", then=vscode(CODE_FIXED, name_err, dirty=True))
    s.window("Code.exe", "* " + title, hwnd=1)
    s.key("s", mods=("ctrl",), then=vscode(CODE_FIXED, name_err))
    s.window("Code.exe", title, hwnd=1)
    s.click(700, 690)
    s.type("python app.py", then=vscode(CODE_FIXED, name_err[:-1] + [PROMPT + "python app.py"]))
    s.key("enter", then=vscode(CODE_FIXED, success), hold=3.0)
    return s


# ---------------------------------------------------------------------------- 2. email
def outlook_inbox(toast=False):
    img = canvas()
    titlebar(img, "Inbox - sam@example.com - Outlook", bg=(170, 100, 20), fg=(255, 255, 255))
    box(img, 0, 34, W, 80, fill=(240, 240, 240), border=None)
    box(img, 14, 42, 154, 72, fill=(170, 100, 20), border=None)
    text(img, "New Email", 30, 63, 0.6, (255, 255, 255), 2)
    box(img, 0, 80, 200, H, fill=(245, 245, 245), border=None)
    for i, f in enumerate(["Inbox", "Drafts", "Sent Items", "Archive"]):
        text(img, f, 20, 120 + i * 34, 0.6, DARK if i else BLUE, 2 if i == 0 else 1)
    box(img, 200, 80, 560, H, fill=(255, 255, 255))
    for i, (who, subj) in enumerate([("John Doe", "Q3 numbers?"), ("IT Desk", "Password policy"), ("Mia Chen", "Lunch Friday")]):
        y = 120 + i * 70
        if i == 0:
            box(img, 201, y - 30, 559, y + 30, fill=(250, 235, 215), border=None)
        text(img, who, 220, y - 5, 0.6, DARK, 2)
        text(img, subj, 220, y + 20, 0.55, MUTED)
    text(img, "Q3 numbers?", 590, 125, 0.9, DARK, 2)
    text(img, "John Doe <john.doe@example.com>", 590, 165, 0.65, BLUE)
    for i, line in enumerate(["Hi Sam,", "Could you send me the Q3 report when it's ready?", "Thanks,", "John"]):
        text(img, line, 590, 220 + i * 32, 0.62)
    if toast:
        box(img, W - 330, H - 80, W - 30, H - 30, fill=(60, 60, 60), border=None)
        text(img, "Message sent", W - 300, H - 48, 0.65, (255, 255, 255))
    return img


def outlook_compose(to="", subject="", body="", attachment=None):
    img = canvas()
    titlebar(img, f"{subject or 'Untitled'} - Message (HTML)", bg=(170, 100, 20), fg=(255, 255, 255))
    box(img, 20, 60, 120, 140, fill=(170, 100, 20), border=None)
    text(img, "Send", 45, 107, 0.7, (255, 255, 255), 2)
    box(img, 1060, 60, 1240, 100, fill=(240, 240, 240))
    text(img, "Attach File", 1085, 87, 0.6)
    for i, (label, value) in enumerate([("To", to), ("Cc", ""), ("Subject", subject)]):
        y = 60 + i * 45
        text(img, label, 140, y + 27, 0.6, MUTED)
        box(img, 240, y + 4, 1040, y + 38, fill=(255, 255, 255))
        text(img, value, 250, y + 28, 0.62)
    if attachment:
        box(img, 240, 205, 470, 245, fill=(240, 240, 240))
        text(img, attachment + "  (1.2 MB)", 252, 231, 0.55)
    box(img, 20, 260, W - 20, H - 20, fill=(255, 255, 255))
    words, lines, cur = body.split(" "), [], ""
    for w in words:
        if len(cur) + len(w) > 70:
            lines.append(cur)
            cur = ""
        cur += w + " "
    lines.append(cur)
    for i, line in enumerate(lines):
        text(img, line.strip(), 40, 300 + i * 32, 0.62)
    return img


def file_dialog():
    img = outlook_compose("jon.doe@example.com", "Q3 report", BODY)
    box(img, 300, 120, 980, 560, fill=(250, 250, 250), border=(120, 120, 120), t=2)
    box(img, 300, 120, 980, 154, fill=(230, 230, 230), border=None)
    text(img, "Insert File", 316, 143, 0.6)
    text(img, "Documents > Reports", 320, 190, 0.6, MUTED)
    for i, name in enumerate(["report.pdf", "report_draft.docx", "budget.xlsx"]):
        text(img, name, 340, 240 + i * 40, 0.65)
    box(img, 840, 500, 960, 540, fill=(170, 100, 20), border=None)
    text(img, "Insert", 868, 527, 0.6, (255, 255, 255))
    return img


BODY = "Hi John, please find the Q3 report attached. Best, Sam"


def email_script() -> Script:
    s = Script(outlook_inbox(), "OUTLOOK.EXE", "Inbox - sam@example.com - Outlook")
    s.wait(3.0)  # reads John's request
    s.click(84, 57, then=outlook_compose())
    compose = s.window("OUTLOOK.EXE", "Untitled - Message (HTML)", at=s.t - 1.2)
    s.click(600, 81)
    s.type("jon.doe@example.com", then=outlook_compose("jon.doe@example.com"))
    s.key("tab", hold=0.8)
    s.key("tab", hold=0.8)
    s.type("Q3 report", then=outlook_compose("jon.doe@example.com", "Q3 report"))
    s.window("OUTLOOK.EXE", "Q3 report - Message (HTML)", hwnd=compose)
    s.key("tab", hold=0.8)
    s.type(BODY, then=outlook_compose("jon.doe@example.com", "Q3 report", BODY), cps=20)
    s.click(1150, 80, then=file_dialog())
    dialog = s.window("OUTLOOK.EXE", "Insert File", at=s.t - 1.2)
    s.click(380, 240, double=True, then=outlook_compose("jon.doe@example.com", "Q3 report", BODY, "report.pdf"))
    s.window("OUTLOOK.EXE", "Q3 report - Message (HTML)", hwnd=compose, at=s.t - 1.2)
    s.click(70, 100, then=outlook_inbox(toast=True), hold=2.5)
    s.window("OUTLOOK.EXE", "Inbox - sam@example.com - Outlook", hwnd=1, at=s.t - 2.2)
    assert dialog
    return s


# ---------------------------------------------------------------------------- 3. files + settings
def explorer(rows, selected=None, rename=None, menu=None, status=""):
    img = canvas()
    titlebar(img, "Downloads - File Explorer")
    box(img, 0, 34, W, 80, fill=(245, 245, 245), border=None)
    text(img, "This PC  >  Downloads", 20, 64, 0.65)
    text(img, "Name", 240, 110, 0.55, MUTED)
    text(img, "Type", 760, 110, 0.55, MUTED)
    box(img, 0, 80, 210, H, fill=(245, 245, 245), border=None)
    for i, f in enumerate(["Desktop", "Downloads", "Documents", "Pictures"]):
        text(img, f, 20, 120 + i * 32, 0.6, BLUE if f == "Downloads" else DARK)
    for i, (name, kind) in enumerate(rows):
        y = 150 + i * 40
        if name == selected:
            box(img, 225, y - 26, 1000, y + 10, fill=(250, 225, 200), border=None)
        if name == rename:
            box(img, 235, y - 24, 600, y + 8, fill=(255, 255, 255), border=BLUE, t=2)
        text(img, ("[folder] " if kind == "File folder" else "") + name, 245, y, 0.62)
        text(img, kind, 760, y, 0.58, MUTED)
    if menu:
        x, y, items = menu
        box(img, x, y, x + 220, y + 34 * len(items) + 10, fill=(250, 250, 250), border=(150, 150, 150))
        for i, it in enumerate(items):
            text(img, it, x + 16, y + 30 + i * 34, 0.6)
    if status:
        text(img, status, 20, H - 16, 0.55, MUTED)
    return img


def settings_storage(on: bool):
    img = canvas((243, 243, 243))
    titlebar(img, "Settings")
    text(img, "System  >  Storage", 260, 90, 1.0, DARK, 2)
    box(img, 0, 34, 230, H, fill=(238, 238, 238), border=None)
    for i, f in enumerate(["System", "Bluetooth & devices", "Network", "Personalization"]):
        text(img, f, 20, 90 + i * 36, 0.58, BLUE if i == 0 else DARK)
    box(img, 260, 130, 1240, 220, fill=(255, 255, 255))
    text(img, "Storage Sense", 290, 170, 0.75, DARK, 2)
    text(img, "Automatically free up space, delete temporary files", 290, 200, 0.55, MUTED)
    box(img, 1100, 158, 1190, 192, fill=BLUE if on else (255, 255, 255), border=(90, 90, 90), t=2)
    cv2.circle(img, (1170 if on else 1120, 175), 11, (255, 255, 255) if on else (90, 90, 90), -1)
    text(img, "On" if on else "Off", 1040, 182, 0.6)
    return img


FILES = [("invoice_0423.pdf", "PDF Document"), ("photo_beach.jpg", "JPG File"), ("notes.txt", "Text Document")]


def files_script() -> Script:
    folder = ("Invoices", "File folder")
    renamed = ("2026-04 Invoice.pdf", "PDF Document")
    s = Script(explorer(FILES), "explorer.exe", "Downloads - File Explorer")
    s.wait(1.5)
    s.click(700, 500, button="right", then=explorer(FILES, menu=(700, 500, ["View", "Sort by", "New  >", "Properties"])))
    s.click(760, 600, then=explorer(FILES, menu=(700, 500, ["View", "Sort by", "New  >", "Properties"])), hold=0.6)
    s.show(explorer(FILES, menu=(920, 590, ["Folder", "Shortcut", "Text Document"])), at=s.t - 0.3)
    s.click(980, 620, then=explorer([("New folder", "File folder")] + FILES, selected="New folder", rename="New folder"))
    s.type("Invoices", then=explorer([("Invoices", "File folder")] + FILES, selected="Invoices", rename="Invoices"))
    s.key("enter", then=explorer([folder] + FILES, selected="Invoices"))
    s.click(330, 185, then=explorer([folder] + FILES, selected="invoice_0423.pdf"))
    s.key("f2", then=explorer([folder] + FILES, selected="invoice_0423.pdf", rename="invoice_0423.pdf"))
    s.type("2026-04 Invoice.pdf", then=explorer([folder, renamed] + FILES[1:], selected="2026-04 Invoice.pdf", rename="2026-04 Invoice.pdf"))
    s.key("enter", then=explorer([folder, renamed] + FILES[1:], selected="2026-04 Invoice.pdf"))
    s.drag(330, 185, 330, 145, then=explorer([folder] + FILES[1:], selected="Invoices", status="1 item moved to Invoices"))
    s.key("i", mods=("cmd",), then=settings_storage(False))
    s.window("SystemSettings.exe", "Settings", at=s.t - 1.2)
    s.click(1145, 175, then=settings_storage(True), hold=2.5)
    return s


# ---------------------------------------------------------------------------- 4. research + spreadsheet
def browser(url, body):
    img = canvas((255, 255, 255))
    titlebar(img, "Searchly - Google Chrome")
    box(img, 0, 34, W, 84, fill=(240, 240, 240), border=None)
    box(img, 120, 44, W - 40, 74, fill=(255, 255, 255))
    text(img, url, 135, 66, 0.6, (60, 60, 60))
    body(img)
    return img


def search_page(query):
    def body(img):
        text(img, "Searchly", 520, 250, 2.0, (40, 80, 200), 4)
        box(img, 290, 300, 990, 360, border=(120, 120, 120), t=2)
        text(img, query, 305, 340, 0.85)

    return browser("https://searchly.example", body)


def results_page():
    def body(img):
        text(img, "Results for: springfield population 2024", 60, 130, 0.8, MUTED)
        for i, (title, snip) in enumerate([("Springfield - Official City Data", "Population, area and history ..."),
                                           ("Springfield on Wikipedia", "Springfield is a city in ..."),
                                           ("Census Quick Facts", "Estimates for cities and towns ...")]):
            y = 200 + i * 110
            text(img, title, 60, y, 0.9, (180, 60, 20), 2)
            text(img, snip, 60, y + 36, 0.65, (70, 70, 70))

    return browser("https://searchly.example/?q=springfield+population+2024", body)


def article_page():
    def body(img):
        text(img, "Springfield - Official City Data", 60, 160, 1.2, DARK, 3)
        text(img, "Population (2024 estimate):  168,412", 60, 260, 1.0, DARK, 2)
        text(img, "Area: 61.5 sq mi      Founded: 1838", 60, 330, 0.8, MUTED)

    return browser("https://springfield.example/data", body)


def sheet(value="", selected=False):
    img = canvas((255, 255, 255))
    titlebar(img, "City Research.xlsx - Excel", bg=(60, 120, 40), fg=(255, 255, 255))
    x0, y0, cw, ch = 80, 120, 300, 50
    for j, c in enumerate("ABC"):
        text(img, c, x0 + j * cw + 140, y0 - 15, 0.7, MUTED)
    data = [["City", "Population 2024", "Source"], ["Springfield", value, ""]]
    for i in range(4):
        for j in range(3):
            box(img, x0 + j * cw, y0 + i * ch, x0 + (j + 1) * cw, y0 + (i + 1) * ch)
            if i < len(data):
                text(img, data[i][j], x0 + j * cw + 10, y0 + i * ch + 33, 0.7)
    if selected:
        box(img, x0 + cw, y0 + ch, x0 + 2 * cw, y0 + 2 * ch, border=(60, 120, 40), t=3)
    return img


def research_script() -> Script:
    s = Script(search_page(""), "chrome.exe", "Searchly - Google Chrome")
    s.wait(1.5)
    s.click(640, 330)
    s.type("springfield population 2024", then=search_page("springfield population 2024"))
    s.key("enter", then=results_page())
    s.window("chrome.exe", "springfield population 2024 - Searchly - Google Chrome", hwnd=1, at=s.t - 1.2)
    s.click(250, 200, then=article_page())
    s.window("chrome.exe", "Springfield - Official City Data - Google Chrome", hwnd=1, at=s.t - 1.2)
    s.wait(2.5)  # reads the population
    s.key("tab", mods=("alt",), then=sheet())
    s.window("EXCEL.EXE", "City Research.xlsx - Excel", at=s.t - 1.2)
    s.click(530, 195, then=sheet(selected=True))
    s.type("186,412", then=sheet("186,412", selected=True))  # digits swapped vs. the article
    s.key("enter", then=sheet("186,412"), hold=2.0)
    return s


SCENARIOS: dict[str, Scenario] = {
    sc.name: sc
    for sc in [
        Scenario(
            "coding",
            "Run a Python script in VS Code's terminal, fix a NameError, save, re-run",
            coding_script,
            expected_steps=[["pyhton"], ["nameerror|not defined"], ["usr"], ["save|ctrl+s"], ["hello"]],
            mistake=["pyhton"],
        ),
        Scenario(
            "email",
            "Reply to a request by composing an email with an attachment in Outlook",
            email_script,
            expected_steps=[["new email|new message|new mail|compose"], ["doe@example.com"], ["q3 report"],
                            ["report.pdf"], ["send"]],
            mistake=["jon.doe"],
        ),
        Scenario(
            "files",
            "Create a folder, rename a file, move it, then turn on Storage Sense",
            files_script,
            expected_steps=[["invoices", "folder"], ["2026-04 invoice"], ["invoices", "move|drag"], ["storage sense"]],
            mistake=[],
        ),
        Scenario(
            "research",
            "Look up a city's population and enter it into a spreadsheet",
            research_script,
            expected_steps=[["springfield population"], ["official"], ["168,412"], ["186,412|b2"]],
            mistake=["186,412"],
        ),
    ]
}
