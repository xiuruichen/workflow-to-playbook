"""Input grouping in the recorder (raw mouse/keyboard -> high-level events), without screen capture."""

import numpy as np
import pytest

from playbook.recorder import Recorder, _Raw


@pytest.fixture
def rec(settings, tmp_path):
    r = Recorder(settings)
    r.session_dir = tmp_path / "session"
    (r.session_dir / "keyframes").mkdir(parents=True)
    r._mon = {"left": 100, "top": 50}  # monitor offset: events are stored relative to it
    r._reset_capture_state()
    r._frame = np.zeros((90, 160, 3), np.uint8)
    r._ring.append((0.0, r._frame))
    return r


def feed(rec, raws, now):
    for raw in raws:
        rec._raw.put(raw)
    rec._process_input(now, rec._frame)


def kinds(rec):
    return [(e.kind, e.text) for e in rec.events]


def test_click_is_relative_to_monitor_and_gets_before_after_keyframes(rec):
    feed(rec, [_Raw(1.0, "press", 400, 250, button="left"), _Raw(1.05, "release", 400, 250, button="left")], now=1.1)
    feed(rec, [], now=3.0)  # past the settle delay -> "after" frame
    (ev,) = rec.events
    assert (ev.kind, ev.x, ev.y) == ("click", 300, 200)
    assert rec.keyframes and 0 in rec.keyframes[-1].event_indices
    assert rec._pending_after == []


def test_double_click_and_drag(rec):
    feed(rec, [
        _Raw(1.0, "press", 400, 250, button="left"), _Raw(1.05, "release", 400, 250, button="left"),
        _Raw(1.2, "press", 401, 251, button="left"), _Raw(1.25, "release", 401, 251, button="left"),
        _Raw(3.0, "press", 200, 200, button="left"), _Raw(3.5, "release", 500, 300, button="left"),
    ], now=4.0)
    assert [e.kind for e in rec.events] == ["double_click", "drag"]
    drag = rec.events[1]
    assert (drag.x, drag.y, drag.x2, drag.y2) == (100, 150, 400, 250)


def test_typing_is_grouped_into_bursts_with_backspace_and_enter(rec):
    keys = ["h", "i", "space", "x", "backspace", "!"]
    feed(rec, [_Raw(1.0 + i * 0.1, "key", key=k) for i, k in enumerate(keys)] + [_Raw(2.0, "key", key="enter")], now=2.1)
    assert kinds(rec) == [("type", "hi !"), ("key", "enter")]


def test_shortcuts_vs_shifted_characters(rec):
    feed(rec, [
        _Raw(1.0, "key", key="c", mods=frozenset({"ctrl"})),
        _Raw(1.5, "key", key="A", mods=frozenset({"shift"})),
    ], now=5.0)  # burst flushes after 1.5 s idle
    assert kinds(rec) == [("hotkey", "ctrl+c"), ("type", "A")]


def test_typed_text_can_be_masked(rec):
    rec.s.mask_typed_text = True
    feed(rec, [_Raw(1.0, "key", key="p"), _Raw(1.1, "key", key="w")], now=5.0)
    assert kinds(rec) == [("type", "••")]


def test_scrolls_are_merged(rec):
    feed(rec, [_Raw(1.0, "scroll", 400, 250, dy=-3), _Raw(1.3, "scroll", 400, 250, dy=-2)], now=1.4)
    feed(rec, [], now=4.0)
    (ev,) = rec.events
    assert (ev.kind, ev.dy, ev.x) == ("scroll", -5, 300)
