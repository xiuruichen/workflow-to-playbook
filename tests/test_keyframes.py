import numpy as np

from playbook.keyframes import annotate, change_score, extract_from_video, thumb
from playbook.models import Event
from tests.make_sample_video import make_sample_video


def test_change_score_identical_and_different():
    a = np.full((720, 1280, 3), 255, np.uint8)
    b = a.copy()
    b[100:400, 100:700] = 0
    assert change_score(a, a) == 0.0
    assert change_score(thumb(a), thumb(b)) > 0.1


def test_annotate_marks_click_without_mutating_input():
    img = np.full((360, 640, 3), 255, np.uint8)
    out = annotate(img, [(1, Event(t=0, kind="click", x=640, y=360))], 1280, 720)
    assert out.shape == img.shape
    assert (img == 255).all()
    assert (out != 255).any()


def test_extract_from_video_finds_scene_changes(tmp_path):
    video = make_sample_video(tmp_path / "sample.mp4")
    kfs, duration, w, h, fps = extract_from_video(video, tmp_path / "session" / "keyframes")
    assert (w, h) == (1280, 720)
    assert 15 < duration < 25
    # start, typed query, results, article, empty sheet, filled sheet, saved toast ...
    assert 5 <= len(kfs) <= 25
    times = [k.t for k in kfs]
    assert times == sorted(times)
    assert kfs[0].trigger == "start"
    for k in kfs:
        assert (tmp_path / "session" / k.path).is_file()
