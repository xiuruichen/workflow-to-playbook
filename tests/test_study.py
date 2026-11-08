"""The fast experiment harness, the induce ablations and the judgment metrics (no model needed)."""

import pytest

from playbook import elicit, induce, ocr, study
from playbook.dashboard import build_sessions, make_visits
from playbook.decisions import NONE, pool
from playbook.evaluate import Score

D = study.domains()["dashboard"]


def test_build_is_reproducible_and_matches_the_planted_rule():
    a, b = study.build(D, 30, 100), study.build(D, 30, 100)
    assert [d.to_dict() for d in a.decisions] == [d.to_dict() for d in b.decisions]
    visits = make_visits(30, 100)
    assert [d.outcome != NONE for d in a.decisions] == [v.stop for v in visits]
    assert not a.flipped and not a.hidden


def test_noise_knobs_change_the_log_as_declared():
    noisy = study.build(D, 60, 100, label_noise=0.2)
    assert noisy.flipped and all(noisy.clean[k] != d.outcome for d in noisy.decisions
                                 for k in [elicit.key(d)] if k in noisy.flipped)
    assert any("aux1" in d.readouts for d in study.build(D, 10, 100, distractors=2).decisions)
    clean = study.build(D, 40, 100)
    bad = study.build(D, 40, 100, misread=0.5)
    assert [d.readouts for d in clean.decisions] != [d.readouts for d in bad.decisions]
    drifted = study.build(D, 60, 100, drift_at=30)
    assert [d.outcome for d in drifted.decisions[:30]] == [d.outcome for d in clean_prefix(30)]


def clean_prefix(n):
    return study.build(D, 60, 100).decisions[:n]


def test_the_fitted_rule_recovers_the_planted_one_and_the_ablations_hurt():
    r = study.run(D, 40, 100)
    assert r["recovery"] == 1.0 and r["test_agreement"] == 1.0
    assert r["without_none"] < r["test_agreement"], "with no non-actions to learn from the rule can only ever say 'act'"
    assert r["without_context"] <= r["test_agreement"]


def test_ablation_strips_only_cross_session_features():
    ds = study.build(D, 20, 100).decisions
    stripped = induce.strip_context(ds)
    assert all(not k.startswith(("changed_", "delta_")) for d in stripped for k in d.features)
    assert any(k.startswith("changed_") for d in ds for k in d.features), "the originals are untouched"
    with pytest.raises(ValueError):
        induce.holdout(ds, without="everything")


def test_label_noise_is_flagged_as_unexplained():
    r = study.run(D, 60, 100, label_noise=0.1)
    assert r["noisy_decisions"] > 0 and r["unexplained_that_were_noise"] > 0


def test_one_elicitation_round_with_a_perfect_expert_helps_on_a_hidden_fact():
    built = study.build(D, 80, 100, hidden_fact=True)
    out = study.elicitation(built, 100)
    assert out["answers"] >= 1 and out["test_after"] >= out["test_before"]
    assert out["unexplained_after"] <= out["unexplained_before"]
    useless = study.elicitation(built, 100, accuracy=0.0)
    assert all(a.fact is None for a in study.simulated_expert(elicit.build_questions(built.decisions), built.hidden,
                                                                __import__("random").Random(0), accuracy=0.0))
    assert useless["test_after"] == useless["test_before"]


def test_summarize():
    s = study.summarize([{"a": 1.0}, {"a": 0.5}], ("a",))
    assert s["a"] == {"mean": 0.75, "min": 0.5, "max": 1.0}


def test_flag_precision_recall_and_f1():
    def score(**kw):
        base = dict(scenario="s", steps=5, expected_found=4, expected_total=5, missing=[], mistake_planted=True,
                    mistake_flagged=True, false_flags=0, api_calls=0, model="m")
        return Score(**{**base, **kw})

    assert score().flag_f1 == 1.0 and score().recall == 0.8
    assert score(false_flags=1).flag_precision == 0.5
    missed = score(mistake_flagged=False)
    assert missed.flag_recall == 0.0 and missed.flag_f1 == 0.0
    clean = score(mistake_planted=False, mistake_flagged=False)
    assert clean.flag_f1 == 1.0, "nothing planted and nothing flagged is a perfect score"


@pytest.mark.skipif(not ocr.available(), reason="needs the local OCR engine")
def test_fast_harness_matches_the_capture_path(settings, tmp_path):
    """The shortcut is only valid if it agrees with what the real pipeline reads from rendered screens."""
    n, seed = 6, 100
    sessions = build_sessions(settings.model_copy(update={"use_ocr": True}), tmp_path, make_visits(n, seed))
    def squash(d):
        return {k.replace("_", ""): v for k, v in d.items()}

    captured, direct = pool(sessions), study.build(D, n, seed).decisions
    assert len(captured) == len(direct) == n
    for c, d in zip(captured, direct):
        assert squash(c.readouts) == squash(d.readouts)  # OCR may spell "Batch size" without the space
        assert (c.outcome == NONE) == (d.outcome == NONE)
        assert squash({k: v for k, v in c.features.items() if k.startswith("changed_")}) == squash(
            {k: v for k, v in d.features.items() if k.startswith("changed_")})


def test_ocr_dropping_a_space_does_not_split_a_readout():
    """Found by the fidelity test: one visit read "Batchsize: 256" while the others read "Batch size: 256"."""
    from playbook.decisions import Decision, add_context

    rows = [Decision("a", 0, 1, "w", {"batch_size": 256.0, "spikes": 2.0}, "none"),
            Decision("b", 2, 3, "w", {"batchsize": 256.0, "spikes": 2.0}, "none"),
            Decision("c", 4, 5, "w", {"batch_size": 512.0, "spikes": 2.0}, "Stop run")]
    add_context(rows)
    assert all("batch_size" in d.readouts and "batchsize" not in d.readouts for d in rows)
    assert rows[1].features["changed_batch_size"] == 0.0 and rows[2].features["changed_batch_size"] == 1.0
