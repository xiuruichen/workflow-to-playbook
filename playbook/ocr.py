"""Local OCR of keyframes (RapidOCR on ONNX Runtime, CPU, no network).

Small local vision models read small on-screen text poorly. OCR gives exact text with
positions, used two ways:
- text near each click is added to the model prompt ("Text near event #2: 'New Email'");
- text in the region that changed since the previous keyframe becomes "visible values"
  for the consistency check, so catching a mistyped value doesn't depend on the model.

Full-frame OCR costs seconds per frame on a laptop CPU, so only the regions that matter are
read: the first frame in full, then crops around clicks and around what changed. Results
are cached per session in ocr.json.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .keyframes import changed_rect, load_image

_engine = None
_lock = threading.Lock()
Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 in keyframe pixels


@dataclass
class TextBox:
    text: str
    x1: int
    y1: int
    x2: int
    y2: int
    score: float

    def distance_to(self, x: float, y: float) -> float:
        dx = max(self.x1 - x, 0, x - self.x2)
        dy = max(self.y1 - y, 0, y - self.y2)
        return (dx * dx + dy * dy) ** 0.5


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


_threads: int | None = None  # CPU thread cap (low-power mode), set before the engine is created


def set_threads(n: int | None) -> None:
    global _threads, _engine
    with _lock:
        if n != _threads:
            _threads, _engine = n, None


def _get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            # Screens: no rotated text (skip the angle classifier) and don't upscale small crops.
            caps = {"intra_op_num_threads": _threads, "inter_op_num_threads": 1} if _threads else {}
            _engine = RapidOCR(det_limit_type="max", det_limit_side_len=1280, use_cls=False, **caps)
        return _engine


def read_image(img: np.ndarray, min_score: float = 0.6, offset: tuple[int, int] = (0, 0)) -> list[TextBox]:
    if img.size == 0:
        return []
    result, _ = _get_engine()(img)
    ox, oy = offset
    boxes = []
    for pts, text, score in result or []:
        if float(score) < min_score or not str(text).strip():
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        boxes.append(TextBox(str(text).strip(), int(min(xs)) + ox, int(min(ys)) + oy, int(max(xs)) + ox, int(max(ys)) + oy,
                             round(float(score), 3)))
    return boxes


class SessionOCR:
    """Region OCR for one session's keyframes, cached in ocr.json."""

    def __init__(self, session_dir: Path, enabled: bool = True):
        self.session_dir = Path(session_dir)
        self.enabled = enabled and available()
        self.path = self.session_dir / "ocr.json"
        try:
            self.cache: dict[str, list[dict]] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self._images: dict[str, np.ndarray] = {}
        self._dirty = False

    def _image(self, keyframe_path: str) -> np.ndarray:
        if keyframe_path not in self._images:
            if len(self._images) > 4:
                self._images.clear()
            self._images[keyframe_path] = load_image(self.session_dir / keyframe_path)
        return self._images[keyframe_path]

    def boxes(self, keyframe_path: str, rect: Rect | None = None) -> list[TextBox]:
        if not self.enabled:
            return []
        key = keyframe_path if rect is None else f"{keyframe_path}@{','.join(map(str, rect))}"
        if key not in self.cache:
            img = self._image(keyframe_path)
            if rect is None:
                found = read_image(img)
            else:
                x1, y1, x2, y2 = rect
                found = read_image(img[y1:y2, x1:x2], offset=(x1, y1))
            self.cache[key] = [b.__dict__ for b in found]
            self._dirty = True
        return [TextBox(**b) for b in self.cache[key]]

    def near(self, keyframe_path: str, x: float, y: float, size: int = 448, limit: int = 6) -> list[str]:
        """Text closest to a point (keyframe pixel coordinates), read from a crop around it."""
        if not self.enabled:
            return []
        h, w = self._image(keyframe_path).shape[:2]
        half = size // 2
        x1, y1 = max(0, int(x) - half), max(0, int(y) - half)
        rect = (x1, y1, min(w, x1 + size), min(h, y1 + size))
        boxes = sorted(self.boxes(keyframe_path, rect), key=lambda b: b.distance_to(x, y))
        return [b.text for b in boxes if b.distance_to(x, y) <= half / 2][:limit]

    def changed_text(self, prev_path: str | None, keyframe_path: str) -> list[str]:
        """Text in the part of the screen that changed since the previous keyframe (all text for the first)."""
        if not self.enabled:
            return []
        rect = None
        if prev_path is not None:
            rect = changed_rect(self._image(prev_path), self._image(keyframe_path))
            if rect is None:
                return []  # nothing changed
        return [b.text for b in self.boxes(keyframe_path, rect)]

    def save(self) -> None:
        if self._dirty:
            self.path.write_text(json.dumps(self.cache), encoding="utf-8")
            self._dirty = False
