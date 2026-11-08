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


def test_categories_become_features_only_when_they_vary_and_recur():
    from playbook.decisions import Decision, add_context, parse_categories

    assert parse_categories(["Vendor: New", "Amount: 5,000", "Window: Chrome"]) == {"vendor": "new", "window": "chrome"}
    rows = [Decision(str(i), i, i + 1, "w", {"amount": 1.0}, "none", cats=c)
            for i, c in enumerate([{"vendor": "new", "window": "chrome"}, {"vendor": "known", "window": "chrome"},
                                   {"vendor": "new", "window": "chrome"}, {"vendor": "known", "window": "chrome"},
                                   {"vendor": "odd", "window": "chrome"}])]
    add_context(rows)
    assert rows[0].features["vendor=new"] == 1.0 and rows[0].features["vendor=known"] == 0.0
    assert "vendor=odd" not in rows[4].features, "a word seen once is noise"
    assert not any(k.startswith("window=") for r in rows for k in r.features), "a label that never varies is no feature"


def test_triage_rule_and_a_learnable_rule():
    from playbook import triage

    visits = triage.make_visits(200, seed=100)
    assert {v.outcome for v in visits} == {"Escalate", "Approve", "none"}
    assert sum(v.outcome == "Escalate" for v in visits) > 20, "every branch of the rule must be learnable from a short run"
    assert not visits[0].amount_changed
    same = [b for a, b in zip(visits, visits[1:]) if not b.amount_changed]
    assert same and all(b.vendor for b in same)
    T = study.domains()["triage"]
    big = study.build(T, 160, 100)
    assert induce.holdout(big.decisions, lookahead=True)["test_accuracy"] >= 0.85


def test_lookahead_recovers_more_of_a_compound_rule_than_the_greedy_tree():
    T = study.domains()["triage"]
    greedy, deep = [], []
    for seed in range(100, 110):
        ds = study.build(T, 80, seed).decisions
        greedy.append(induce.holdout(ds, lookahead=False)["test_accuracy"])
        deep.append(induce.holdout(ds, lookahead=True)["test_accuracy"])
    assert sum(deep) / 10 >= sum(greedy) / 10 + 0.03


def test_lookahead_does_not_change_a_rule_the_greedy_tree_already_fits():
    D2 = study.domains()["dashboard"]
    ds = study.build(D2, 40, 100).decisions
    assert induce.rules(induce.fit(ds, lookahead=True)) == induce.rules(induce.fit(ds, lookahead=False))


@pytest.mark.skipif(not ocr.available(), reason="needs the local OCR engine")
def test_triage_capture_reads_numbers_words_and_the_button_clicked(settings, tmp_path):
    from playbook import triage

    visits = triage.make_visits(10, 100)
    sessions = triage.build_sessions(settings.model_copy(update={"use_ocr": True}), tmp_path, visits)
    got = pool(sessions)
    assert len(got) == 10
    direct = study.build(study.domains()["triage"], 10, 100).decisions
    for c, d, v in zip(got, direct, visits):
        assert c.readouts.get("amount") == d.readouts["amount"]
        assert c.cats.get("vendor") == d.cats["vendor"]
        assert (c.outcome.lower().replace(" ", "") if c.outcome != NONE else NONE) == v.outcome.lower()


def test_cross_session_class_follows_the_decisions_own_path():
    from playbook.knowledge import classify_decision

    ds = study.build(D, 60, 100).decisions
    tree = induce.fit(ds)
    calm = next(d for d in ds if d.readouts["spikes"] < 2)
    assert "changed_batch_size" not in induce.path_features(tree, calm)
    assert classify_decision(calm, induce.path_features(tree, calm)).observability == "O4"
    busy = next(d for d in ds if d.readouts["spikes"] >= 2)
    assert classify_decision(busy, induce.path_features(tree, busy)).observability == "O5"


def test_strict_prompt_variant_changes_the_system_message():
    from playbook import replay

    seen = []

    def chat(messages, fmt):
        seen.append(messages[0]["content"])
        return '{"choice": "none"}'

    d = study.build(D, 10, 100).decisions[0]
    replay.model_decider(chat, "skill text", ["none"])(d)
    replay.model_decider(chat, "skill text", ["none"], strict=True)(d)
    assert replay.STRICT not in seen[0] and replay.STRICT in seen[1]


def test_service_domain_rule_and_ratio_features():
    from playbook import service
    from playbook.decisions import Decision, add_ratios

    v = service.Visit(requests=10000, errors=150, latency=500, version=41, version_changed=False)
    assert v.outcome == "Roll back"
    assert service.Visit(10000, 150, 500, 42, True).outcome == "none", "a new version buys time"
    assert service.Visit(10000, 600, 100, 41, True).outcome == "Page on-call", "paging ignores everything else"
    assert service.Visit(100000, 150, 900, 41, False).outcome == "none", "150 errors in 100000 requests is 0.15%"
    rows = add_ratios([Decision("a", 0, 1, "w", {"errors": 10.0, "requests": 100.0, "version": 3.0}, "none"),
                       Decision("b", 2, 3, "w", {"errors": 0.0, "requests": 200.0, "version": 3.0}, "none")])
    assert "requests/version" in rows[0].features and not any(k.startswith("errors/") for k in rows[0].features), \
        "a readout that is ever zero gets no ratios"
    S = study.domains()["service"]
    assert {d.outcome for d in study.build(S, 100, 100).decisions} == {"none", "Page on-call", "Roll back"}


def test_ratio_features_let_the_tree_learn_a_rate_rule():
    S = study.domains()["service"]
    plain, ratio = [], []
    for seed in range(100, 106):
        plain.append(induce.holdout(study.build(S, 80, seed).decisions)["test_accuracy"])
        ratio.append(induce.holdout(study.build(S, 80, seed, ratios=True).decisions)["test_accuracy"])
    assert sum(ratio) / 6 > sum(plain) / 6 + 0.1
    rules = induce.rules(induce.fit(study.build(S, 80, 100, ratios=True).decisions))
    assert any("errors/requests" in r for r in rules)


def test_cli_ratios_flag_finds_the_rate_rule(tmp_path, monkeypatch, capsys, settings):
    from playbook import __main__ as cli
    from playbook.decisions import save_decisions

    S = study.domains()["service"]
    dirs = []
    for i, d in enumerate(study.build(S, 80, 100).decisions):
        folder = tmp_path / f"v{i:03d}"
        folder.mkdir()
        save_decisions([d], folder / "decisions.jsonl")
        dirs.append(str(folder))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["induce", "--ratios", *dirs]) == 0
    assert "errors/requests" in capsys.readouterr().out


def test_vet_keeps_a_fact_that_explains_and_drops_one_that_does_not():
    import random

    built = study.build(D, 80, 100, hidden_fact=True)
    train = built.decisions[:56]
    questions = elicit.build_questions(train)
    good = study.simulated_expert(questions, built.hidden, random.Random(0), accuracy=1.0)
    kept, dropped = elicit.vet(train, good)
    assert kept and not dropped
    bad = [elicit.Answer(good[0].session, good[0].t1, "felt wrong", "gut feeling", [elicit.key(train[i]) for i in (0, 1, 2)])]
    kept2, dropped2 = elicit.vet(train, bad)
    assert not kept2 and dropped2, "a condition tagged on unrelated decisions explains nothing"
    assert all(a.fact is None for a in elicit.vet(train, [elicit.Answer("s", 0.0, "no idea", None)])[0])


@pytest.mark.skipif(not ocr.available(), reason="needs the local OCR engine")
def test_service_capture_reads_the_counts_and_the_button_clicked(settings, tmp_path):
    from playbook import service

    visits = service.make_visits(10, 100)
    got = pool(service.build_sessions(settings.model_copy(update={"use_ocr": True}), tmp_path, visits))
    direct = study.build(study.domains()["service"], 10, 100).decisions
    assert len(got) == 10

    def norm(o):
        return "".join(ch for ch in o.lower() if ch.isalnum())

    for c, d, v in zip(got, direct, visits):
        assert {k: c.readouts.get(k) for k in ("requests", "errors", "latency")} == {k: d.readouts[k] for k in ("requests", "errors", "latency")}
        assert (norm(c.outcome) if c.outcome != NONE else NONE) == (norm(v.outcome) if v.outcome != "none" else NONE)


@pytest.mark.skipif(not ocr.available(), reason="needs the local OCR engine")
def test_continuous_recording_needs_the_navigation_word_and_a_short_dwell(settings, tmp_path):
    """E7: with many checks in one recording, a 'Next run' click must not count as an action."""
    from playbook import dashboard
    from playbook.decisions import build_decisions
    from playbook.scenarios import simulate

    visits = dashboard.make_visits(6, 3)
    sess = simulate(dashboard.continuous_scenario(visits, [6.0] * 6, "c"), settings.model_copy(update={"use_ocr": True}), tmp_path / "s")
    counted = build_decisions(sess, dwell_min_s=3.0)
    ignored = build_decisions(sess, dwell_min_s=3.0, navigation=("Next run",))
    assert len(build_decisions(sess)) == 0, "six-second looks are below the default 8 s dwell"
    assert len(ignored) >= 5
    assert any(d.outcome != NONE for d in counted) and all(d.outcome != NONE for d in counted if "next" in d.outcome.lower())
    acted = sum(d.outcome != NONE for d in ignored)
    assert acted <= sum(v.stop for v in visits) and acted < sum(d.outcome != NONE for d in counted)


def test_judge_gives_the_same_answer_as_the_mechanical_reader_and_asks_outside_the_range(tmp_path, capsys):
    import json

    from playbook import __main__ as cli
    from playbook import replay
    from playbook.skill import build_judgment

    S = study.domains()["service"]
    ds = study.build(S, 80, 100, ratios=True).decisions
    train, test = ds[:56], ds[56:]
    j = build_judgment(train, None)
    decider = replay.rules_decider(j)
    for i, d in enumerate(test):
        previous = ds[56 + i - 1].readouts  # the check before, as the decision log knows it
        assert replay.judge(j, d.readouts, d.cats, previous)["outcome"] == decider(d)
    d = test[0]
    out = replay.judge(j, d.readouts)
    assert out["outcome"] in {r["then"] for r in j["rules"]} | {replay.ASK} and out["reason"]
    far = dict(d.readouts, errors=d.readouts["errors"] * 1000)
    assert replay.judge(j, far)["outcome"] == replay.ASK and "outside the range" in replay.judge(j, far)["reason"]
    path = tmp_path / "skill.json"
    path.write_text(json.dumps({"judgment": j}), encoding="utf-8")
    assert cli.main(["judge", "--rules", str(path), "--readouts", json.dumps(d.readouts)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["outcome"] == out["outcome"]
    path.write_text(json.dumps({"steps": []}), encoding="utf-8")
    assert cli.main(["judge", "--rules", str(path), "--readouts", "{}"]) == 1


def test_judge_computes_words_changes_and_quotients_the_rules_mention():
    from playbook import replay

    j = {"basis": {"observed_ranges": {}}, "rules": [
        {"when": ["errors/requests > 0.05"], "then": "Page", "support": "9/9", "thin_evidence": False},
        {"when": ["vendor=known > 0.5", "changed_amount <= 0.5"], "then": "Approve", "support": "5/5", "thin_evidence": False},
        {"when": ["always"], "then": "none", "support": "3/3", "thin_evidence": False}]}
    assert replay.judge(j, {"errors": 600.0, "requests": 8000.0})["outcome"] == "Page"
    assert replay.judge(j, {"errors": 10.0, "requests": 8000.0, "amount": 5.0}, {"vendor": "known"}, {"amount": 5.0})["outcome"] == "Approve"
    assert replay.judge(j, {"errors": 10.0, "requests": 8000.0, "amount": 6.0}, {"vendor": "known"}, {"amount": 5.0})["outcome"] == "none"
    assert replay.judge({"basis": {"observed_ranges": {}}, "rules": []}, {"x": 1.0})["outcome"] == replay.ASK
