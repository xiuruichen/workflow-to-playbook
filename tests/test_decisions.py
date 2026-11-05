"""Frames, decision log, rule fitting and knowledge classes (no model; the pipeline test uses local OCR)."""

import pytest

from playbook import induce, ocr
from playbook.dashboard import make_visits, visit_scenario
from playbook.decisions import Decision, add_context, parse_readouts, pool, save_decisions
from playbook.frames import compile_frames
from playbook.knowledge import classify_decision, classify_step
from playbook.models import Event, Keyframe, Manifest, Step
from playbook.scenarios import simulate


def manifest(events, duration=40.0, keyframe_times=(0.0,)):
    return Manifest(session_id="s", source="live", duration=duration, width=100, height=100, fps=5, created="now",
                    events=events, keyframes=[Keyframe(id=i, t=t, path=f"keyframes/{i}.jpg", trigger="heartbeat")
                                              for i, t in enumerate(keyframe_times)])


def click(t):
    return Event(t=t, kind="click", app="a.exe", window="w", x=1, y=1)


def test_dwell_frames_hold_the_pauses_between_actions():
    frames = compile_frames(manifest([click(1), click(2), click(20), click(21)], duration=22))
    assert [(f.kind, f.t0, f.t1) for f in frames] == [("active", 1, 2), ("dwell", 2, 20), ("active", 20, 21)]
    assert frames[1].keyframe_ids == [0], "the screen the pause started on is the evidence, even if it predates it"


def test_trailing_pause_is_a_dwell_and_short_gaps_are_not():
    frames = compile_frames(manifest([click(1), click(5)], duration=30))
    assert [f.kind for f in frames] == ["active", "dwell"]
    assert compile_frames(manifest([click(1), click(5)], duration=8))[-1].kind == "active"


def test_parse_readouts():
    assert parse_readouts(["Spikes: 2", "Batch size: 1,024", "Loss = 2.31", "no numbers here"]) == {
        "spikes": 2.0, "batch_size": 1024.0, "loss": 2.31}


def dec(i, spikes, batch, outcome):
    return Decision("s", i, i + 12, "w", {"spikes": float(spikes), "batch_size": float(batch)}, outcome)


def test_cross_session_context_marks_a_changed_value():
    ds = add_context([dec(0, 1, 256, "none"), dec(1, 2, 256, "stop"), dec(2, 2, 512, "none")])
    assert [d.features.get("changed_batch_size") for d in ds] == [None, 0.0, 1.0]


def planted():
    out, batch = [], 256
    for i, (spikes, change) in enumerate([(0, 0), (2, 0), (3, 1), (1, 0), (2, 1), (2, 0), (0, 1), (3, 0), (2, 0), (1, 0),
                                          (3, 1), (2, 0), (0, 0), (2, 1), (3, 0), (1, 1)] * 2):
        batch *= 2 if change and i else 1
        out.append(dec(i, spikes, batch, "stop" if spikes >= 2 and not (change and i) else "none"))
    return add_context(out)


def test_rule_recovers_the_planted_cross_session_rule():
    ds = planted()
    tree = induce.fit(ds)
    assert induce.accuracy(tree, ds) == 1.0
    assert {"spikes", "changed_batch_size"} <= induce.features_used(tree)
    train, test = induce.holdout_accuracy(ds)
    assert test == 1.0
    plain = [Decision(**{**d.__dict__, "features": dict(d.readouts)}) for d in ds]
    assert induce.accuracy(induce.fit(plain), plain) < 1.0, "without the earlier session the rule cannot be told apart"


def test_disagreements_list_the_decisions_the_rule_cannot_explain():
    ds = planted()
    odd = ds[1]
    odd.outcome = "none"  # the expert let a spiking run go for a reason nobody can see
    assert odd in [d for d, _ in induce.disagreements(ds)]


def test_knowledge_classes():
    assert classify_decision(dec(0, 1, 256, "none")).observability == "O4"
    assert classify_decision(dec(0, 2, 256, "stop")).observability == "O3"
    c = classify_decision(dec(0, 2, 256, "none"), {"spikes", "changed_batch_size"}, rule_gets_it_right=False)
    assert c.observability == "O5" and c.method == "pool and fit a rule" and c.tacit_score >= 3
    step = Step(index=1, title="t", description="", t_start=0, t_end=1, model_confidence=0.9, confidence=0.9, action="click")
    assert classify_step(step).observability == "O1"
    assert classify_step(step.model_copy(update={"uncertainty_reason": "why?"})).observability == "O6"


@pytest.mark.skipif(not ocr.available(), reason="needs the local OCR engine")
def test_dashboard_session_becomes_a_decision(settings, tmp_path):
    visits = make_visits(8, seed=1)
    stop = next(v for v in visits if v.stop)
    keep = next(v for v in visits if not v.stop)
    paths = [simulate(visit_scenario(v, f"v{i}"), settings.model_copy(update={"use_ocr": True}), tmp_path / f"v{i}")
             for i, v in enumerate([keep, stop])]
    ds = pool(paths)
    assert [d.outcome == "none" for d in ds] == [True, False]
    assert ds[1].readouts["spikes"] == stop.spikes and ds[1].readouts["batch_size"] == stop.batch_size
    assert (paths[0] / "decisions.jsonl").is_file()


def hidden_factor_decisions(n=60, seed=3):
    """Planted rule with a fact that is never on screen: no stop during warmup."""
    import random

    rng = random.Random(seed)
    rows, warmup, batch = [], set(), 256
    for i in range(n):
        spikes, change, warm = rng.choice([0, 1, 2, 3]), int(i > 0 and rng.random() < 0.25), int(rng.random() < 0.25)
        batch *= 2 if change else 1
        rows.append(dec(i, spikes, batch, "stop" if spikes >= 2 and not change and not warm else "none"))
        rows[-1].session = f"v{i:02d}"
        if warm:
            warmup.add(f"v{i:02d}@{rows[-1].t1:g}")
    return add_context(rows), warmup


def first_text(questions):
    return questions[0].text()


def test_questions_target_what_the_rule_cannot_explain_and_answers_fix_the_rule():
    from playbook import elicit

    ds, warm_keys = hidden_factor_decisions()
    questions = elicit.build_questions(ds)
    asked = {elicit.key(q.decision) for q in questions}
    assert asked & warm_keys, "the decisions the hidden fact explains are among those asked about"
    assert "most similar decisions" in first_text(questions) or "screen does not show" in first_text(questions)

    first = next(q for q in questions if elicit.key(q.decision) in warm_keys)
    tagged = [elicit.key(d) for d in elicit.tag_candidates(first, questions) if elicit.key(d) in warm_keys]
    answers = [elicit.Answer(first.decision.session, first.decision.t1, "run was still warming up", "warmup phase", tagged)]
    result = elicit.effect(ds, answers)
    assert result["facts"] == ["warmup_phase"]
    assert result["after"]["accuracy"] > result["before"]["accuracy"]
    assert result["after"]["unexplained"] < result["before"]["unexplained"]


def test_answers_round_trip(tmp_path):
    from playbook import elicit

    path = tmp_path / "a.jsonl"
    elicit.save_answers([elicit.Answer("s", 12.0, "why", "fact x", ["t@5"])], path)
    (a,) = elicit.load_answers(path)
    assert (a.key, a.fact, a.also) == ("s@12", "fact x", ["t@5"]) and elicit.load_answers(tmp_path / "none") == []


def test_replay_scores_deciders_on_held_out_decisions():
    import json

    from playbook import elicit, replay

    ds, warm = hidden_factor_decisions(n=80, seed=5)
    first = next(q for q in elicit.build_questions(ds[:56]) if elicit.key(q.decision) in warm)
    answers = [elicit.Answer(first.decision.session, first.decision.t1, "warming up", "warmup",
                             [k for k in map(elicit.key, ds[:56]) if k in warm])]
    # a stand-in "model": acts on the skill text, so we can tell which arm it was given
    def chat(messages, fmt):
        has_rules = "Judgment calls" in messages[0]["content"]
        return json.dumps({"choice": "stop" if "spikes = 3" in messages[1]["content"] or "spikes = 2" in messages[1]["content"]
                           and (not has_rules or "warmup: no" in messages[1]["content"]) else "none"})

    out = replay.run(ds, answers, chat, "Check the run.")
    assert out["train"] == 56 and out["test"] == 24 and out["options"] == ["none", "stop"]
    arms = out["arms"]
    assert set(arms) == {"majority", "rules", "skill", "skill+judgment"}
    assert arms["rules"]["agreement"] >= arms["majority"]["agreement"]
    assert arms["skill+judgment"]["agreement"] >= arms["skill"]["agreement"]
    assert arms["skill"]["wrong_actions"] >= arms["skill+judgment"]["wrong_actions"]
    assert replay.run(ds, answers)["arms"].keys() == {"majority", "rules"}


def test_rules_decider_asks_a_human_outside_the_observed_range():
    from playbook import replay
    from playbook.skill import build_judgment

    ds, _ = hidden_factor_decisions()
    decide = replay.rules_decider(build_judgment(ds))
    far = Decision("x", 0, 12, "w", {"spikes": 40.0, "batch_size": 256.0}, "none",
                   features={"spikes": 40.0, "batch_size": 256.0})
    assert decide(far) == replay.ASK


def test_cli_commands_run_on_saved_decisions(settings, tmp_path, monkeypatch, capsys):
    """decisions.jsonl files are all the induce/elicit/replay commands need."""
    import io

    from playbook import __main__ as cli

    ds, _ = hidden_factor_decisions(n=40, seed=2)
    dirs = []
    for i, d in enumerate(ds):
        folder = tmp_path / f"s{i:02d}"
        folder.mkdir()
        d.session = folder.name
        save_decisions([d], folder / "decisions.jsonl")
        dirs.append(str(folder))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["induce", *dirs]) == 0 and "Fitted rule" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # no one to answer: stops cleanly
    assert cli.main(["elicit", *dirs]) == 0 and "Rule before your answers" in capsys.readouterr().out
    assert cli.main(["replay", *dirs]) == 0
    out = capsys.readouterr().out
    assert "majority" in out and "rules" in out
