"""Live screen recording with input-event-anchored keyframes.

Threads:
- pynput mouse/keyboard listeners push raw input into a queue (they must stay fast).
- One capture thread grabs the screen at `capture_fps`, writes the H.264 video, turns raw
  input into high-level events (clicks, typed bursts, scrolls, shortcuts) and saves
  keyframes: one right before each event, one after the screen settles, plus keyframes on
  significant visual change and a slow heartbeat.

Video time is kept equal to wall-clock time by duplicating frames when capture lags, so
event timestamps can be used directly as seek positions in the recording.

Hotkeys: Ctrl+Shift+Q stops, Ctrl+Shift+P pauses/resumes (paused time is blanked out).
"""

from __future__ import annotations

import ctypes
import math
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .config import Settings, get_settings
from .keyframes import DUPLICATE_SCORE, change_score, save_jpeg, thumb, resize_max_width
from .models import Event, Keyframe, Manifest


def _enable_dpi_awareness() -> None:
    """Make mss and pynput both use physical pixels on scaled Windows displays."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi_awareness()


def new_session_dir(settings: Settings, suffix: str = "") -> Path:
    sid = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{suffix}" if suffix else "")
    path = settings.sessions_dir / sid
    path.mkdir(parents=True, exist_ok=False)
    (path / "keyframes").mkdir()
    return path


@dataclass
class _Raw:
    """Raw input from listener threads."""

    t: float
    kind: str  # press, release, scroll, key
    x: int = 0
    y: int = 0
    button: str = ""
    dx: int = 0
    dy: int = 0
    key: str = ""  # printable char or special key name
    mods: frozenset = field(default_factory=frozenset)


SPECIAL_ENDS_BURST = {"enter", "tab", "esc"}
IGNORED_KEYS = {"caps_lock", "num_lock", "scroll_lock"}  # state toggles, not actions
MODIFIERS = {"ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r", "alt_gr", "cmd", "cmd_l", "cmd_r", "shift", "shift_l", "shift_r"}


def _norm_mod(name: str) -> str:
    return name.split("_")[0] if name != "alt_gr" else "alt"


class Recorder:
    def __init__(
        self,
        settings: Settings | None = None,
        on_status: Callable[[str], None] | None = None,
    ):
        self.s = settings or get_settings()
        self.status = ""  # latest status message (safe to poll from a UI thread)
        self._user_status = on_status or (lambda msg: None)
        self.session_dir: Path | None = None
        self.paused = False
        self.running = False
        self.error: str | None = None
        self._stop = threading.Event()
        self._raw: queue.Queue[_Raw] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._listeners: list = []
        self._t0 = 0.0
        self._mods: set[str] = set()
        self._press: _Raw | None = None
        self._last_click: Event | None = None

        self.events: list[Event] = []
        self.keyframes: list[Keyframe] = []
        self._events_log = None

    # ------------------------------------------------------------------ public API
    def start(self) -> Path:
        self.session_dir = new_session_dir(self.s)
        self._events_log = open(self.session_dir / "events.jsonl", "a", encoding="utf-8")
        self._t0 = time.perf_counter()
        self._start_listeners()
        self.running = True
        self._thread = threading.Thread(target=self._capture_loop, name="capture", daemon=True)
        self._thread.start()
        self.on_status(f"Recording to {self.session_dir}")
        return self.session_dir

    def stop(self) -> Path:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        for lst in self._listeners:
            try:
                lst.stop()
            except Exception:
                pass
        self.running = False
        if self._events_log:
            self._events_log.close()
            self._events_log = None
        if self.error:
            raise RuntimeError(self.error)
        assert self.session_dir is not None
        return self.session_dir

    def on_status(self, msg: str) -> None:
        self.status = msg
        self._user_status(msg)

    def request_stop(self) -> None:
        self._stop.set()

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.on_status("Paused" if self.paused else "Resumed")

    def wait(self) -> None:
        """Block until stopped via hotkey (or KeyboardInterrupt)."""
        try:
            while not self._stop.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------ listeners
    def _now(self) -> float:
        return time.perf_counter() - self._t0

    def _start_listeners(self) -> None:
        from pynput import keyboard, mouse

        def on_click(x, y, button, pressed):
            self._raw.put(_Raw(self._now(), "press" if pressed else "release", int(x), int(y), button=button.name))

        def on_scroll(x, y, dx, dy):
            self._raw.put(_Raw(self._now(), "scroll", int(x), int(y), dx=int(dx), dy=int(dy)))

        def key_name(key) -> str:
            if isinstance(key, keyboard.Key):
                return key.name
            vk = getattr(key, "vk", None)
            char = getattr(key, "char", None)
            # With Ctrl held, .char is a control character; recover the letter from the virtual key.
            if vk is not None and (0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39) and (char is None or not char.isprintable()):
                return chr(vk).lower()
            return char or ""

        def on_press(key):
            name = key_name(key)
            if name in MODIFIERS:
                self._mods.add(_norm_mod(name))
                return
            if name in IGNORED_KEYS:
                return
            mods = frozenset(self._mods)
            if {"ctrl", "shift"} <= mods and name == "q":
                self._stop.set()
                return
            if {"ctrl", "shift"} <= mods and name == "p":
                self.toggle_pause()
                return
            if name:
                self._raw.put(_Raw(self._now(), "key", key=name, mods=mods))

        def on_release(key):
            name = key_name(key)
            if name in MODIFIERS:
                self._mods.discard(_norm_mod(name))

        ml = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
        kl = keyboard.Listener(on_press=on_press, on_release=on_release)
        ml.start()
        kl.start()
        self._listeners = [ml, kl]

    # ------------------------------------------------------------------ capture thread
    def _capture_loop(self) -> None:
        try:
            self._run_capture()
        except Exception as exc:  # surface errors to stop()
            self.error = f"Recording failed: {exc!r}"
            self._stop.set()

    def _reset_capture_state(self) -> None:
        self._ring: deque[tuple[float, np.ndarray]] = deque(maxlen=int(self.s.capture_fps * 3) + 2)
        self._pending_after: list[tuple[float, int]] = []  # (due_time, event_index)
        self._burst: list[str] = []
        self._burst_t = 0.0
        self._burst_last = 0.0
        self._last_kf_thumb = None
        self._last_kf_t = -1e9
        self._prev_thumb = None
        self._scroll: Event | None = None
        self._last_click = None

    def _run_capture(self) -> None:
        import imageio_ffmpeg
        import mss

        s = self.s
        assert self.session_dir is not None
        with mss.mss() as sct:
            mon = sct.monitors[min(s.monitor, len(sct.monitors) - 1)]
            self._mon = mon
            mon_w, mon_h = mon["width"], mon["height"]
            vid_w = min(mon_w, s.record_max_width)
            vid_h = int(mon_h * vid_w / mon_w)
            vid_w, vid_h = vid_w - vid_w % 2, vid_h - vid_h % 2
            writer = imageio_ffmpeg.write_frames(
                str(self.session_dir / "recording.mp4"),
                (vid_w, vid_h),
                fps=s.capture_fps,
                codec="libx264",
                pix_fmt_in="bgr24",
                quality=None,
                macro_block_size=2,
                output_params=["-preset", "ultrafast", "-crf", "28", "-movflags", "+faststart"],
            )
            writer.send(None)
            self._reset_capture_state()

            interval = 1.0 / s.capture_fps
            frames_written = 0
            paused_frame = None
            next_tick = time.perf_counter()
            last_status = 0.0
            first = True
            while True:
                stopping = self._stop.is_set()
                now = self._now()
                shot = np.asarray(sct.grab(mon))[:, :, :3]
                frame = np.ascontiguousarray(shot)
                if self.paused:
                    if paused_frame is None:
                        paused_frame = np.full_like(frame, 40)
                        cv2.putText(paused_frame, "RECORDING PAUSED", (60, mon_h // 2), cv2.FONT_HERSHEY_SIMPLEX, 3, (200, 200, 200), 6)
                    frame = paused_frame
                    self._drain_raw(discard=True)
                small = resize_max_width(frame, s.max_image_width)
                self._ring.append((now, small))

                vid_frame = cv2.resize(frame, (vid_w, vid_h), interpolation=cv2.INTER_AREA) if frame.shape[1] != vid_w or frame.shape[0] != vid_h else frame
                target = max(1, math.floor(now * s.capture_fps) + 1)
                payload = vid_frame.tobytes()
                while frames_written < target:
                    writer.send(payload)
                    frames_written += 1

                if first:
                    self._save_kf(small, now, "start")
                    first = False
                if not self.paused:
                    self._process_input(now, small)
                    self._visual_triggers(now, small)

                if now - last_status > 5:
                    self.on_status(f"Recording {now:5.0f}s | {len(self.events)} events | {len(self.keyframes)} keyframes")
                    last_status = now
                if stopping:
                    break
                next_tick += interval
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_tick = time.perf_counter()

            # Flush anything in flight and capture a final frame.
            self._flush_burst(now)
            self._flush_scroll()
            for _, ev_idx in self._pending_after:
                self._save_kf(small, now, "event_after", ev_idx)
            self._save_kf(small, now, "end", dedupe=False)
            writer.close()

        manifest = Manifest(
            session_id=self.session_dir.name,
            source="live",
            video="recording.mp4",
            duration=round(now, 2),
            width=mon_w,
            height=mon_h,
            fps=s.capture_fps,
            created=datetime.now().isoformat(timespec="seconds"),
            keyframes=self.keyframes,
            events=self.events,
        )
        manifest.save(self.session_dir)
        self.on_status(f"Saved {now:.0f}s recording, {len(self.events)} events, {len(self.keyframes)} keyframes")

    # ------------------------------------------------------------------ keyframes
    def _frame_before(self, t: float) -> np.ndarray:
        """Latest buffered frame captured strictly before time t."""
        best = self._ring[0][1]
        for ft, fr in self._ring:
            if ft < t:
                best = fr
            else:
                break
        return best

    def _save_kf(self, frame: np.ndarray, t: float, trigger: str, event_index: int | None = None, dedupe: bool = True) -> int:
        th = thumb(frame)
        if dedupe and self.keyframes and self._last_kf_thumb is not None and change_score(self._last_kf_thumb, th) < DUPLICATE_SCORE:
            kf = self.keyframes[-1]  # identical screen: reuse the previous keyframe
            if event_index is not None and event_index not in kf.event_indices:
                kf.event_indices.append(event_index)
            return kf.id
        kid = len(self.keyframes)
        assert self.session_dir is not None
        rel = f"keyframes/{kid:04d}_{trigger}_{t:07.2f}.jpg"
        save_jpeg(frame, self.session_dir / rel, self.s.max_image_width)
        self.keyframes.append(Keyframe(id=kid, t=round(t, 2), path=rel, trigger=trigger, event_indices=[event_index] if event_index is not None else []))
        self._last_kf_thumb, self._last_kf_t = th, t
        return kid

    def _visual_triggers(self, now: float, frame: np.ndarray) -> None:
        th = thumb(frame)
        stable = self._prev_thumb is not None and change_score(self._prev_thumb, th) < self.s.change_threshold / 4
        self._prev_thumb = th
        if self._pending_after or self._burst or self._last_kf_thumb is None:
            return
        drift = change_score(self._last_kf_thumb, th)
        if drift > self.s.change_threshold and stable and now - self._last_kf_t > 1.0:
            self._save_kf(frame, now, "change")
        elif now - self._last_kf_t > self.s.heartbeat_s and drift > DUPLICATE_SCORE:
            self._save_kf(frame, now, "heartbeat")

    # ------------------------------------------------------------------ input -> events
    def _drain_raw(self, discard: bool = False) -> list[_Raw]:
        items = []
        while True:
            try:
                items.append(self._raw.get_nowait())
            except queue.Empty:
                return [] if discard else items

    def _to_local(self, x: int, y: int) -> tuple[int, int]:
        return x - self._mon["left"], y - self._mon["top"]

    def _add_event(self, ev: Event, before_frame: np.ndarray | None = None) -> int:
        idx = len(self.events)
        self.events.append(ev)
        if self._events_log:
            self._events_log.write(ev.model_dump_json(exclude_none=True) + "\n")
            self._events_log.flush()
        frame = before_frame if before_frame is not None else self._frame_before(ev.t)
        self._save_kf(frame, ev.t, "event_before", idx)
        self._pending_after.append((ev.t + self.s.settle_s, idx))
        return idx

    def _process_input(self, now: float, frame: np.ndarray) -> None:
        for r in self._drain_raw():
            if r.kind in ("press", "release", "scroll"):
                self._flush_burst(r.t)
            if r.kind != "scroll":
                self._flush_scroll()
            if r.kind == "press":
                self._press = r
            elif r.kind == "release" and self._press is not None:
                p, self._press = self._press, None
                x, y = self._to_local(p.x, p.y)
                if math.hypot(r.x - p.x, r.y - p.y) > 20:
                    x2, y2 = self._to_local(r.x, r.y)
                    self._add_event(Event(t=round(p.t, 2), kind="drag", x=x, y=y, x2=x2, y2=y2, button=p.button))
                    continue
                kind = "right_click" if p.button == "right" else "click"
                last = self._last_click
                if kind == "click" and last and last.kind == "click" and p.t - last.t < 0.45 and abs(last.x - x) < 6 and abs(last.y - y) < 6:
                    last.kind = "double_click"  # upgrade the previous click in place
                    self._last_click = None
                    continue
                ev = Event(t=round(p.t, 2), kind=kind, x=x, y=y, button=p.button)
                self._add_event(ev)
                self._last_click = ev
            elif r.kind == "scroll":
                x, y = self._to_local(r.x, r.y)
                if self._scroll and r.t - self._scroll.t < 1.5:
                    self._scroll.dy = (self._scroll.dy or 0) + r.dy
                    self._scroll.dx = (self._scroll.dx or 0) + r.dx
                else:
                    self._flush_scroll()
                    self._scroll = Event(t=round(r.t, 2), kind="scroll", x=x, y=y, dx=r.dx, dy=r.dy)
                    self._scroll_before = self._frame_before(r.t)
            elif r.kind == "key":
                self._handle_key(r)

        if self._burst and now - self._burst_last > 1.5:
            self._flush_burst(now)
        if self._scroll and now - self._scroll.t > 1.5:
            self._flush_scroll()

        # Grab "after" frames once the screen has had time to react.
        due = [p for p in self._pending_after if p[0] <= now]
        if due:
            self._pending_after = [p for p in self._pending_after if p[0] > now]
            for _, ev_idx in due[-1:]:  # one frame covers all events that are due now
                self._save_kf(frame, now, "event_after", ev_idx)
            for _, ev_idx in due[:-1]:
                kf = self.keyframes[-1]
                if ev_idx not in kf.event_indices:
                    kf.event_indices.append(ev_idx)

    def _handle_key(self, r: _Raw) -> None:
        mods = {m for m in r.mods if m != "shift"}
        if mods:  # shortcut such as ctrl+c / alt+tab
            self._flush_burst(r.t)
            combo = "+".join(sorted(r.mods) + [r.key])
            self._add_event(Event(t=round(r.t, 2), kind="hotkey", text=combo))
            return
        if r.key in SPECIAL_ENDS_BURST:
            self._flush_burst(r.t)
            self._add_event(Event(t=round(r.t, 2), kind="key", text=r.key))
            return
        if r.key == "backspace":
            if self._burst:
                self._burst.pop()
                self._burst_last = r.t
            else:
                self._add_event(Event(t=round(r.t, 2), kind="key", text="backspace"))
            return
        char = " " if r.key == "space" else r.key
        if len(char) != 1:  # arrows, delete, F-keys, ...
            self._flush_burst(r.t)
            self._add_event(Event(t=round(r.t, 2), kind="key", text=r.key))
            return
        if not self._burst:
            self._burst_t = r.t
            self._burst_before = self._frame_before(r.t)
        self._burst.append(char)
        self._burst_last = r.t

    def _flush_burst(self, now: float) -> None:
        if not self._burst:
            return
        text = "".join(self._burst)
        if self.s.mask_typed_text:
            text = "•" * len(text)
        self._burst = []
        self._add_event(Event(t=round(self._burst_t, 2), kind="type", text=text), before_frame=self._burst_before)

    def _flush_scroll(self) -> None:
        if self._scroll is None:
            return
        ev, self._scroll = self._scroll, None
        self._add_event(ev, before_frame=self._scroll_before)


def record_session(settings: Settings | None = None, on_status: Callable[[str], None] = print) -> Path:
    """Record until Ctrl+Shift+Q / Ctrl+C. Returns the session directory."""
    rec = Recorder(settings, on_status=on_status)
    rec.start()
    on_status("Press Ctrl+Shift+Q (or Ctrl+C here) to stop, Ctrl+Shift+P to pause/resume.")
    rec.wait()
    return rec.stop()


def import_video(video: Path, settings: Settings | None = None, progress: Callable[[float, str], None] | None = None) -> Path:
    """Create a session from an existing screen-recording file."""
    import shutil

    from .keyframes import extract_from_video

    s = settings or get_settings()
    session_dir = new_session_dir(s, suffix="import")
    dest = session_dir / f"recording{video.suffix.lower()}"
    shutil.copy2(video, dest)
    kfs, duration, w, h, fps = extract_from_video(
        dest, session_dir / "keyframes", max_width=s.max_image_width, change_threshold=s.change_threshold, progress=progress
    )
    Manifest(
        session_id=session_dir.name,
        source="import",
        video=dest.name,
        duration=round(duration, 2),
        width=w,
        height=h,
        fps=fps,
        created=datetime.now().isoformat(timespec="seconds"),
        keyframes=kfs,
        events=[],
    ).save(session_dir)
    (session_dir / "events.jsonl").write_text("", encoding="utf-8")
    return session_dir


def resolve_session(arg: str | None, settings: Settings | None = None) -> Path:
    """Accept a session path, a session id, or 'latest'."""
    s = settings or get_settings()
    if arg and Path(arg).is_dir():
        return Path(arg)
    if arg and arg != "latest":
        p = s.sessions_dir / arg
        if p.is_dir():
            return p
        raise FileNotFoundError(f"No session '{arg}' in {s.sessions_dir}")
    sessions = list_sessions(s)
    if not sessions:
        raise FileNotFoundError(f"No sessions in {s.sessions_dir}")
    return sessions[0]


def list_sessions(settings: Settings | None = None) -> list[Path]:
    s = settings or get_settings()
    if not s.sessions_dir.exists():
        return []
    return sorted((p for p in s.sessions_dir.iterdir() if (p / "manifest.json").exists()), reverse=True)


__all__ = ["Recorder", "record_session", "import_video", "resolve_session", "list_sessions", "new_session_dir"]
