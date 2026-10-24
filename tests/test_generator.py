from playbook.generator import render_markdown, write_playbook
from playbook.models import Playbook, Step


def make_pb():
    steps = [
        Step(index=1, title="Open the sheet", description="Open City Research.xlsx", t_start=3, t_end=4,
             model_confidence=0.9, confidence=0.9, keyframe_after="keyframes/0001.jpg"),
        Step(index=2, title="Copy the population", description="Copy 168,412", t_start=133, t_end=140,
             model_confidence=0.7, confidence=0.55, uncertainty_reason="value partly hidden", evidence="cell B2 changed",
             calibration_notes=["No mouse/keyboard event corroborates this step"]),
    ]
    pb = Playbook(title="City lookup", goal="Record a population", steps=steps, session_id="s", source="live",
                  video="recording.mp4", duration=150, model="gemini-test", threshold=0.70, generated_at="now")
    pb.refresh_flags()
    return pb


def test_low_confidence_steps_are_flagged():
    md = render_markdown(make_pb())
    assert md.count("NEEDS REVIEW") == 1
    assert "NEEDS REVIEW (0.55)" in md and "value partly hidden" in md
    assert "1 of 2 steps need human review" in md
    assert "[00:02:13](recording.mp4#t=133)" in md
    assert "- [ ] Verified by a human" in md


def test_verified_steps_are_not_flagged():
    pb = make_pb()
    pb.steps[1].verified = True
    md = render_markdown(pb)
    assert "NEEDS REVIEW" not in md
    assert "verified" in md


def test_write_playbook_creates_files(tmp_path):
    path = write_playbook(make_pb(), tmp_path)
    assert path.read_text(encoding="utf-8").startswith("# City lookup")
    assert Playbook.load(tmp_path).title == "City lookup"
