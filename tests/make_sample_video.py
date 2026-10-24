"""Generate a small synthetic "workflow" screen recording for smoke tests.

The video shows a fake browser search, a results page, an article, then entering the
number into a fake spreadsheet. All data is fictional. The number is entered with two
digits swapped (168,412 -> 186,412), a deliberate mistake the analyzer should flag.
Text is large enough for a vision model to read.

    python tests/make_sample_video.py [out.mp4]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

W, H, FPS = 1280, 720, 10
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _text(img, s, x, y, scale=0.8, color=(30, 30, 30), thick=2):
    cv2.putText(img, s, (x, y), FONT, scale, color, thick, cv2.LINE_AA)


def _cursor(img, x, y):
    pts = np.array([[x, y], [x, y + 24], [x + 7, y + 18], [x + 16, y + 18]], np.int32)
    cv2.fillPoly(img, [pts], (0, 0, 0))
    cv2.polylines(img, [pts], True, (255, 255, 255), 1)


def browser(url: str, body) -> np.ndarray:
    img = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(img, (0, 0), (W, 80), (235, 235, 235), -1)
    cv2.rectangle(img, (120, 20), (W - 40, 60), (255, 255, 255), -1)
    _text(img, url, 135, 48, 0.7, (60, 60, 60))
    _text(img, "Chrome", 20, 48, 0.7, (80, 80, 80))
    body(img)
    return img


def search_home(query: str):
    def body(img):
        _text(img, "Searchly", 520, 250, 2.0, (200, 80, 40), 4)
        cv2.rectangle(img, (290, 300), (990, 360), (120, 120, 120), 2)
        _text(img, query + ("|" if len(query) < 40 else ""), 305, 340, 0.9)
        cv2.rectangle(img, (560, 390), (720, 435), (230, 230, 230), -1)
        _text(img, "Search", 595, 420, 0.8)

    return browser("https://searchly.example", body)


def results():
    def body(img):
        _text(img, "Results for: city population 2024", 60, 130, 0.9, (90, 90, 90))
        rows = [
            ("Springfield - Official City Data", "Population 2024: 168,412 residents ..."),
            ("Springfield on Wikipedia", "Springfield is a city in ..."),
            ("Census Quick Facts", "Estimates for cities and towns ..."),
        ]
        for i, (title, snip) in enumerate(rows):
            y = 200 + i * 120
            _text(img, title, 60, y, 1.0, (180, 60, 20))
            _text(img, snip, 60, y + 40, 0.7, (70, 70, 70))

    return browser("https://searchly.example/?q=city+population+2024", body)


def article():
    def body(img):
        _text(img, "Springfield - Official City Data", 60, 150, 1.3, (20, 20, 20), 3)
        _text(img, "Population (2024 estimate):  168,412", 60, 260, 1.1, (20, 20, 20), 2)
        _text(img, "Area: 61.5 sq mi      Founded: 1838", 60, 330, 0.9, (70, 70, 70))

    return browser("https://springfield.example/data", body)


def sheet(value: str, toast: bool = False):
    img = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(img, (0, 0), (W, 60), (40, 120, 60), -1)
    _text(img, "Sheets - City Research.xlsx", 20, 40, 0.9, (255, 255, 255))
    cols, x0, y0, cw, ch = ["A", "B", "C"], 80, 120, 300, 50
    for j, c in enumerate(cols):
        _text(img, c, x0 + j * cw + 140, y0 - 15, 0.8, (90, 90, 90))
    data = [["City", "Population 2024", "Source"], ["Springfield", value, ""]]
    for i in range(4):
        for j in range(3):
            cv2.rectangle(img, (x0 + j * cw, y0 + i * ch), (x0 + (j + 1) * cw, y0 + (i + 1) * ch), (200, 200, 200), 1)
            if i < len(data):
                _text(img, data[i][j], x0 + j * cw + 10, y0 + i * ch + 33, 0.75)
    if value:
        cv2.rectangle(img, (x0 + cw, y0 + ch), (x0 + 2 * cw, y0 + 2 * ch), (40, 120, 60), 3)
    if toast:
        cv2.rectangle(img, (W - 360, H - 100), (W - 40, H - 40), (50, 50, 50), -1)
        _text(img, "All changes saved", W - 330, H - 62, 0.8, (255, 255, 255))
    return img


def make_sample_video(path: Path) -> Path:
    import imageio_ffmpeg

    path = Path(path)
    # H.264 so the video plays in browsers (the HTML viewer, Streamlit, GitHub).
    writer = imageio_ffmpeg.write_frames(
        str(path), (W, H), fps=FPS, codec="libx264", pix_fmt_in="bgr24", quality=None,
        output_params=["-crf", "30", "-movflags", "+faststart"],
    )
    writer.send(None)

    def hold(img, seconds, cursor=(640, 600)):
        frame = img.copy()
        _cursor(frame, *cursor)
        payload = frame.tobytes()
        for _ in range(int(seconds * FPS)):
            writer.send(payload)

    query = "city population 2024"
    hold(search_home(""), 2.5, (620, 330))
    for i in range(1, len(query) + 1):  # typing animation
        hold(search_home(query[:i]), 0.1, (620, 330))
    hold(search_home(query), 1.5, (640, 412))
    hold(results(), 3.0, (200, 200))
    hold(article(), 3.5, (500, 262))
    hold(sheet(""), 2.5, (520, 195))
    hold(sheet("186,412"), 2.5, (520, 195))  # typo: digits swapped vs. the article
    hold(sheet("186,412", toast=True), 2.5, (520, 195))
    writer.close()
    return path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_workflow.mp4")
    print(make_sample_video(out))
