"""Every scenario builds a valid live-style session, and the scorer works (no API calls)."""

import pytest

from playbook.evaluate import score
from playbook.models import Manifest, Playbook, Step
from playbook.scenarios import SCENARIOS, simulate


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_builds_a_live_session(name, settings, tmp_path):
    session = simulate(SCENARIOS[name], settings, tmp_path / name)
    m = Manifest.load(session)
    assert m.source == "live" and (session / "recording.mp4").stat().st_size > 10_000
    assert len(m.events) >= 8 and len(m.keyframes) >= len(m.events) // 2
    assert all(e.app and e.window for e in m.events), "every event carries its window"
    assert all((session / k.path).is_file() for k in m.keyframes)
    times = [k.t for k in m.keyframes]
    assert times == sorted(times)


def test_window_switches_become_focus_events(settings, tmp_path):
    m = Manifest.load(simulate(SCENARIOS["email"], settings, tmp_path / "email"))
    assert [e.window for e in m.events if e.kind == "focus"] == [
        "Untitled - Message (HTML)", "Insert File", "Q3 report - Message (HTML)", "Inbox - sam@example.com - Outlook",
    ]


def make_step(i, title, review_note=None, conf=0.9):
    return Step(index=i, title=title, description="", t_start=i, t_end=i + 1, model_confidence=conf, confidence=conf,
                review_note=review_note)


def test_score_counts_recall_mistakes_and_false_flags():
    sc = SCENARIOS["coding"]
    pb = Playbook(title="t", session_id="s", source="live", duration=30, model="m", threshold=0.7, generated_at="now", steps=[
        make_step(1, "Run 'pyhton app.py'", review_note="Typo: pyhton instead of python"),
        make_step(2, "Read the NameError in the terminal"),
        make_step(3, "Change usr to user"),
        make_step(4, "Save with Ctrl+S", conf=0.5),  # a false flag
    ])
    pb.refresh_flags()
    s = score(sc, pb, api_calls=3)
    assert (s.expected_found, s.expected_total) == (4, 5) and s.missing == ["hello"]
    assert s.mistake_flagged and s.false_flags == 1
