import json

import pytest

from playbook.analyzer import Analyzer, AnalysisError, assign_events, build_windows, parse_json
from playbook.models import Event, Keyframe, Playbook
from tests.conftest import FakeClient

PASS1 = {
    "window_context": "User searches and opens a result",
    "steps": [
        {"action": "click", "description": "Click Search", "start_image": 2, "end_image": 3, "confidence": 0.95,
         "evidence": "ring on Search button"},
        {"action": "shortcut", "description": "Press Ctrl+L", "start_image": 1, "end_image": 2, "confidence": 0.9,
         "evidence": "address bar focused"},
        {"action": "read", "description": "Read the population figure", "start_image": 3, "end_image": 4,
         "confidence": 0.6, "evidence": "article open", "uncertainty_reason": "text is small"},
    ],
}
PASS2 = {
    "title": "Look up a city population",
    "goal": "Find the population and record it",
    "steps": [
        {"title": "Focus the address bar", "source_ids": ["c2"], "confidence": 0.9},
        {"title": "Click Search", "source_ids": ["c1"], "confidence": 0.95},
    ],
    "inputs": [{"name": "city", "example": "Springfield"}],
    "open_questions": ["Why this source?"],
}


def run(settings, session, pass1=(PASS1,), pass2=(PASS2,)):
    client = FakeClient(pass1, pass2)
    pb = Analyzer(settings, client=client).analyze(session)
    return pb, client


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    assert parse_json('[{"description": "x"}]') == {"steps": [{"description": "x"}]}


def test_windows_share_boundary_and_assign_each_event_once():
    kfs = [Keyframe(id=i, t=float(i), path="", trigger="change") for i in range(10)]
    wins = build_windows(kfs, 4)
    assert [w[0].id for w in wins] == [0, 3, 6]
    assert all(wins[i][-1].id == wins[i + 1][0].id for i in range(len(wins) - 1))
    events = [Event(t=t, kind="click", x=0, y=0) for t in (0.5, 3.0, 3.5, 9.5)]
    seen = []
    for n, w in enumerate(wins):
        for per_img in assign_events(w, events, n == len(wins) - 1):
            seen += [gi for gi, _ in per_img]
    assert sorted(seen) == [0, 1, 2, 3]


def test_full_pipeline_calibrates_merges_and_flags(settings, make_session):
    session = make_session()
    pb, client = run(settings, session)
    assert len(client.requests) == 2  # one window + consolidation
    assert pb.title == "Look up a city population"
    assert [s.title for s in pb.steps][:2] == ["Focus the address bar", "Click Search"]
    by_src = {s.source_ids[0]: s for s in pb.steps}
    # shortcut had no supporting input event -> 0.90 - 0.15; pass 2 can't raise a single-source step
    assert by_src["c2"].confidence == pytest.approx(0.75)
    assert any("No mouse/keyboard event" in n for n in by_src["c2"].calibration_notes)
    assert by_src["c1"].confidence == pytest.approx(0.95)
    # c3 was not placed by pass 2: kept as its own (flagged) step
    assert by_src["c3"].needs_review and by_src["c3"].confidence == pytest.approx(0.6)
    assert [s.index for s in pb.review_steps] == [by_src["c3"].index]
    assert (session / "analysis.json").exists()
    assert Playbook.load(session).steps[0].title == pb.steps[0].title


def test_cache_avoids_repeat_calls(settings, make_session):
    session = make_session()
    run(settings, session)
    _, client = run(settings, session)
    assert client.requests == []


def test_invalid_json_is_repaired_and_penalised(settings, make_session):
    pb, client = run(settings, make_session(), pass1=("not json at all", PASS1))
    assert len(client.requests) == 3
    click = next(s for s in pb.steps if s.source_ids == ["c1"])
    assert click.confidence == pytest.approx(0.85)
    assert any("repair" in n for n in click.calibration_notes)


def test_imported_video_gets_no_event_penalty(settings, make_session):
    pb, _ = run(settings, make_session(source="import"))
    click = next(s for s in pb.steps if s.source_ids == ["c1"])
    assert click.confidence == pytest.approx(0.80)
    assert any("Imported video" in n for n in click.calibration_notes)
    assert any("imported video" in n.lower() for n in pb.notes)


def test_consolidation_failure_falls_back_to_raw_steps(settings, make_session):
    pb, _ = run(settings, make_session(), pass2=("garbage", "still garbage"))
    assert len(pb.steps) == 3
    assert any("Consolidation pass failed" in n for n in pb.notes)


def test_merged_steps_may_rise_slightly_above_weakest(settings, make_session):
    merged = dict(PASS2, steps=[{"title": "Search", "source_ids": ["c1", "c2"], "confidence": 0.95}])
    pb, _ = run(settings, make_session(), pass2=(merged,))
    step = next(s for s in pb.steps if s.source_ids == ["c1", "c2"])
    assert step.confidence == pytest.approx(0.85)  # weakest (0.75) + 0.10 leeway
    assert step.t_start == 0.0 and step.keyframe_after.endswith("0002.jpg")


def test_missing_api_key_is_a_clear_error(settings, make_session):
    settings.gemini_api_key = ""
    with pytest.raises(AnalysisError, match="GEMINI_API_KEY"):
        Analyzer(settings).analyze(make_session())


def test_images_and_events_are_sent(settings, make_session):
    _, client = run(settings, make_session())
    parts = client.requests[0]["messages"][1]["content"]
    assert sum(p["type"] == "image_url" for p in parts) == 4
    text = json.dumps(parts)
    assert "click at (100,100)" in text and "typed" in text and "hello" in text


def test_review_note_flags_a_confident_step(settings, make_session):
    noted = dict(PASS2, steps=[{"title": "Click Search", "source_ids": ["c1"], "confidence": 0.95,
                                "review_note": "Searched for 315,613 but the page shows 315,663"}])
    pb, _ = run(settings, make_session(), pass2=(noted,))
    step = next(s for s in pb.steps if s.source_ids == ["c1"])
    assert step.confidence > settings.confidence_threshold
    assert step.needs_review and "315,663" in step.review_note


def test_image_numbers_in_model_text_become_timestamps(settings, make_session):
    p1 = {"steps": [{"action": "click", "description": "Click Search", "start_image": 2, "end_image": 3,
                     "confidence": 0.9, "evidence": "Image 2 shows the button; images 3 confirms"}]}
    pb, _ = run(settings, make_session(), pass1=(p1,), pass2=("bad", "bad"))
    assert pb.steps[0].evidence == "[00:00:02] shows the button; [00:00:04] confirms"
