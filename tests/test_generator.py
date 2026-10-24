from playbook.generator import render_html, render_markdown, write_playbook
from playbook.models import Playbook, Step


def make_pb():
    steps = [
        Step(index=1, title="Open the sheet", description="Open City Research.xlsx", t_start=3, t_end=4,
             model_confidence=0.9, confidence=0.9, keyframe_after="keyframes/0001.jpg"),
        Step(index=2, title="Copy the population", description="Copy 168,412", t_start=133, t_end=140,
             model_confidence=0.7, confidence=0.55, uncertainty_reason="value partly hidden", evidence="cell B2 changed",
             calibration_notes=["No mouse/keyboard event corroborates this step"]),
        Step(index=3, title="Type the population", description="Type 186,412 into B2", t_start=150, t_end=152,
             model_confidence=0.95, confidence=0.95, review_note="Typed 186,412 but the source shows 168,412"),
    ]
    pb = Playbook(title="City lookup", goal="Record a population", steps=steps, session_id="s", source="live",
                  video="recording.mp4", duration=160, model="gemini-test", threshold=0.70, generated_at="now")
    pb.refresh_flags()
    return pb


def test_low_confidence_and_inconsistent_steps_are_flagged():
    md = render_markdown(make_pb())
    assert md.count("NEEDS REVIEW") == 2
    assert "Low confidence (0.55): value partly hidden" in md
    assert "Check: Typed 186,412 but the source shows 168,412" in md
    assert "2 of 3 steps need human review" in md
    assert "[00:02:13](recording.mp4#t=133)" in md
    assert "- [ ] Verified by a human" in md
    assert "🔎 0.95" in md  # understood, but worth checking


def test_verified_steps_are_not_flagged():
    pb = make_pb()
    pb.steps[1].review = pb.steps[2].review = "correct"
    md = render_markdown(pb)
    assert "NEEDS REVIEW" not in md
    assert "verified" in md


def test_steps_marked_wrong_stay_flagged_and_old_files_migrate():
    pb = make_pb()
    pb.steps[0].review = "wrong"
    md = render_markdown(pb)
    assert "❌ marked wrong" in md and "Marked wrong by a reviewer" in md
    assert "3 of 3 steps need human review" in md
    old = Step.model_validate({**pb.steps[0].model_dump(exclude={"review"}), "verified": True})
    assert old.review == "correct" and old.verified


def test_html_viewer_seeks_and_escapes():
    pb = make_pb()
    pb.steps[0].title = "Open <script>alert(1)</script>"
    page = render_html(pb)
    assert "<video id='video' src='recording.mp4'" in page
    assert "data-t='133'" in page and "▶ 00:02:13" in page
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert page.count("class='step flag'") == 2


def test_write_playbook_creates_files(tmp_path):
    path = write_playbook(make_pb(), tmp_path)
    assert path.read_text(encoding="utf-8").startswith("# City lookup")
    assert (tmp_path / "playbook.html").exists()
    assert Playbook.load(tmp_path).steps[2].review_note


def test_labels_export(tmp_path):
    import csv

    from playbook.labels import export_labels

    pb = make_pb()
    pb.steps[0].review, pb.steps[2].review = "correct", "wrong"
    session = tmp_path / "s1"
    session.mkdir()
    pb.save(session)
    out = tmp_path / "labels.csv"
    assert export_labels([session], out) == 2
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [(r["step"], r["label"], r["has_review_note"]) for r in rows] == [("1", "1", "0"), ("3", "0", "1")]
