"""Keyframe utilities shared by live recording and video import.

- change detection at two scales: a coarse thumbnail for big changes (page loads, app
  switches) and a finer image for small but meaningful ones (a typed value, a line of
  terminal output), cheap enough to run every frame
- JPEG writing with downscaling
- annotation of input events (click markers, labels) for the vision model
- scene-change keyframe extraction from an existing video file
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .models import Event, Keyframe

THUMB_WIDTH = 160
PIXEL_DELTA = 25  # grayscale delta that counts a pixel as "changed" (coarse)
FINE_WIDTH = 640
FINE_DELTA = 40  # grayscale delta that counts a pixel as "changed" (fine; ignores compression noise)
# At most this many changed fine pixels = same screen. Measured: caret blinks, spinners and
# ticking timers change ~10-135 px; a typed word or new line of output changes ~160+ px.
SAME_MAX_PX = 150
SETTLED_MIN_PX = 300  # a settled change at least this large is worth a keyframe (e.g. new terminal output)


def thumb(frame: np.ndarray) -> np.ndarray:
    """Small grayscale version of a BGR frame for fast comparisons."""
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (THUMB_WIDTH, max(1, int(h * THUMB_WIDTH / w))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


@dataclass
class Signature:
    """Two-scale grayscale fingerprint of a frame."""

    coarse: np.ndarray
    fine: np.ndarray


def signature(frame: np.ndarray) -> Signature:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    fine = gray if w <= FINE_WIDTH else cv2.resize(gray, (FINE_WIDTH, max(1, int(h * FINE_WIDTH / w))), interpolation=cv2.INTER_AREA)
    coarse = cv2.resize(gray, (THUMB_WIDTH, max(1, int(h * THUMB_WIDTH / w))), interpolation=cv2.INTER_AREA)
    return Signature(coarse, fine)


def changed_px(a: Signature, b: Signature) -> int:
    """Number of noticeably changed pixels at FINE_WIDTH."""
    fb = b.fine if b.fine.shape == a.fine.shape else cv2.resize(b.fine, (a.fine.shape[1], a.fine.shape[0]))
    return int(np.count_nonzero(cv2.absdiff(a.fine, fb) > FINE_DELTA))


def same_screen(a: Signature, b: Signature) -> bool:
    return changed_px(a, b) <= SAME_MAX_PX


def notable_change(a: Signature, b: Signature, threshold: float) -> bool:
    """A big change (fraction of the coarse image) or a smaller one that is clearly real."""
    return change_score(a.coarse, b.coarse) > threshold or changed_px(a, b) > SETTLED_MIN_PX


def change_score(a: np.ndarray, b: np.ndarray) -> float:
    """Fraction of pixels (0..1) that differ noticeably between two thumbnails or frames."""
    if a.ndim == 3:
        a = thumb(a)
    if b.ndim == 3:
        b = thumb(b)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > PIXEL_DELTA)) / diff.size


def resize_max_width(frame: np.ndarray, max_width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    return cv2.resize(frame, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)


def save_jpeg(frame: np.ndarray, path: Path, max_width: int, quality: int = 85) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", resize_max_width(frame, max_width), [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError(f"Could not encode keyframe {path}")
    path.write_bytes(buf.tobytes())


def load_image(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    return img


def annotate(frame: np.ndarray, numbered: list[tuple[int, Event]], src_w: int, src_h: int) -> np.ndarray:
    """Draw markers for `(number, event)` pairs (in src_w x src_h coordinates) onto a copy of `frame`.

    Pointer events get a red ring with a number; the number matches the event list sent
    to the model, so it can tie "event #2" to the exact on-screen location.
    """
    out = frame.copy()
    h, w = out.shape[:2]
    sx, sy = w / max(src_w, 1), h / max(src_h, 1)
    r = max(12, w // 60)
    for n, ev in numbered:
        if ev.x is None or ev.y is None:
            continue
        x, y = int(ev.x * sx), int(ev.y * sy)
        if not (0 <= x < w and 0 <= y < h):
            continue
        color = (0, 0, 255) if ev.kind != "scroll" else (255, 128, 0)
        cv2.circle(out, (x, y), r, color, 3)
        cv2.circle(out, (x, y), 3, color, -1)
        if ev.kind == "drag" and ev.x2 is not None and ev.y2 is not None:
            cv2.arrowedLine(out, (x, y), (int(ev.x2 * sx), int(ev.y2 * sy)), color, 3)
        label = str(n)
        cv2.putText(out, label, (x + r, y - r), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 4)
        cv2.putText(out, label, (x + r, y - r), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    return out


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()


def extract_from_video(
    video_path: Path,
    out_dir: Path,
    *,
    max_width: int = 1280,
    sample_fps: float = 2.0,
    change_threshold: float = 0.02,
    min_gap_s: float = 1.0,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[Keyframe], float, int, int, float]:
    """Pick keyframes from an existing screen recording using scene-change detection.

    For every significant visual change we save the frame just *before* the change and
    the first *stable* frame after it, mimicking the before/after pairs of live capture.

    Returns (keyframes, duration_s, width, height, fps). Keyframe paths are relative to
    `out_dir.parent` (the session directory).
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 0 or fps > 240:
        fps = 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, round(fps / sample_fps))

    keyframes: list[Keyframe] = []
    session_dir = out_dir.parent

    def save(frame: np.ndarray, t: float, trigger: str) -> None:
        kid = len(keyframes)
        path = out_dir / f"{kid:04d}_{trigger}_{t:07.2f}.jpg"
        save_jpeg(frame, path, max_width)
        keyframes.append(Keyframe(id=kid, t=round(t, 2), path=path.relative_to(session_dir).as_posix(), trigger=trigger))

    ref = None  # signature of the last saved keyframe
    prev = None  # (t, frame, signature) of the previous sample
    pending = False  # a change started and we are waiting for the screen to settle
    pending_since = 0.0
    last_saved_t = -1e9
    idx = 0
    t = 0.0
    while True:
        if idx % step:
            if not cap.grab():
                break
            idx += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / fps
        idx += 1
        sig = signature(frame)
        if ref is None:
            save(frame, t, "start")
            ref, last_saved_t = sig, t
        else:
            if not pending and notable_change(ref, sig, change_threshold):
                pending, pending_since = True, t
                if prev is not None and not same_screen(ref, prev[2]) and prev[0] - last_saved_t >= min_gap_s / 2:
                    save(prev[1], prev[0], "scene")  # last frame before the change
            if pending and prev is not None:
                # Save once the screen stops changing (or give up waiting on animations/video).
                settled = same_screen(prev[2], sig) or t - pending_since > 5.0
                if settled and t - last_saved_t >= min_gap_s:
                    save(frame, t, "scene")
                    ref, last_saved_t, pending = sig, t, False
        prev = (t, frame, sig)
        if progress and total:
            progress(min(idx / total, 1.0), f"Scanning video {t:.0f}s")
    cap.release()

    duration = total / fps if total else t
    if prev is not None and (ref is None or not same_screen(ref, prev[2])):
        save(prev[1], prev[0], "end")
    return keyframes, duration, width, height, fps
