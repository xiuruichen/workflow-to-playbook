import pytest

from playbook.analyzer import fmt_ts
from playbook.consistency import annotate_steps, find_near_misses, is_near_miss
from playbook.models import Event, Step, StepCandidate


@pytest.mark.parametrize("typed, seen", [
    ("315,613", "315,663"),          # one digit changed (the real-recording miss)
    ("186,412", "168,412"),          # transposed digits
    ("jon.doe@example.com", "john.doe@example.com"),
    ("Q3-reprot.pdf", "Q3-report.pdf"),
    ("git chekout main", "git checkout main"),
])
def test_near_misses(typed, seen):
    assert is_near_miss(typed, seen)


@pytest.mark.parametrize("typed, seen", [
    ("315,663", "315663"),           # same number, different formatting
    ("2024", "2025"),                # only 4 digits: too common to flag 1 changed digit
    ("674,134", "315,663"),          # unrelated numbers
    ("boston pop", "boston population"),  # prefix / autocomplete
    ("Springfield", "Shelbyville"),  # different words
    ("Report", "report"),            # case only
])
def test_not_near_misses(typed, seen):
    assert not is_near_miss(typed, seen)


def cand(action, value, t):
    return StepCandidate(description="x", action=action, value=value, t_start=t, t_end=t)


def test_finds_cross_segment_typo_and_annotates_step():
    events = [Event(t=43.0, kind="type", text="315,613"), Event(t=60.0, kind="type", text="Boston")]
    cands = [
        cand("read", "Cincinnati population: 315,663 (2024 estimate)", 18.0),
        cand("type", "315,613", 43.0),  # typing steps are never treated as "seen" values
        cand("read", "Boston, Massachusetts", 55.0),
    ]
    misses = find_near_misses(events, cands)
    assert [(m.typed, m.seen, m.seen_t) for m in misses] == [("315,613", "315,663", 18.0)]

    steps = [Step(index=1, title="Look up", description="", t_start=10, t_end=30, model_confidence=0.9, confidence=0.9),
             Step(index=2, title="Enter value", description="", t_start=40, t_end=45, model_confidence=0.95, confidence=0.95)]
    assert annotate_steps(steps, misses, fmt_ts) == 1
    assert steps[1].review_note == 'Typed "315,613" but "315,663" was seen at 00:00:18 (consistency check).'
    assert steps[0].review_note is None


def test_exact_copy_and_masked_text_are_not_flagged():
    events = [Event(t=5, kind="type", text="168,412"), Event(t=6, kind="type", text="•••••")]
    cands = [cand("read", "Population 168,412", 1), cand("read", "168,421 households", 2)]
    assert find_near_misses(events, cands) == []


def test_values_listed_as_visible_on_screen_are_checked():
    events = [Event(t=7.0, kind="type", text="jon.doe@example.com")]
    cands = [cand("type", "jon.doe@example.com", 7.0)]
    visible = [("John Doe <john.doe@example.com>", 0.0), ("Q3 numbers?", 0.0)]
    (m,) = find_near_misses(events, cands, visible)
    assert (m.typed, m.seen) == ("jon.doe@example.com", "john.doe@example.com")


def test_typed_value_listed_as_visible_does_not_hide_the_typo():
    """Models list the typed field's contents as 'visible' too; that must not count as a correct copy."""
    events = [Event(t=7.0, kind="type", text="jon.doe@example.com")]
    visible = [("john.doe@example.com", 0.0), ("jon.doe@example.com", 0.0)]
    (m,) = find_near_misses(events, [], visible)
    assert m.seen == "john.doe@example.com"


def test_users_own_earlier_input_is_not_a_source():
    """A retyped, corrected command must not be flagged against the earlier typo still on screen."""
    events = [Event(t=3, kind="type", text="pyhton app.py"), Event(t=9, kind="type", text="python app.py")]
    visible = [("pyhton app.py", 0.0), ("NameError: name 'usr' is not defined", 0.0)]
    assert find_near_misses(events, [], visible) == []
