"""The rule list and the automatic selection between the plain tree, ratio features, lookahead and a rule list."""

from playbook import induce, replay, study
from playbook.decisions import Decision
from playbook.rulelist import RuleList, fit_rulelist
from playbook.skill import build_judgment


def planted(n=60):
    """Above 5000: 'esc' if late (days >= 30), else 'none'. At or below 5000: 'ok' if the vendor flag is 1, else 'none'."""
    import random

    rng = random.Random(1)
    rows = []
    for i in range(n):
        amount, days, known = rng.choice([800, 2000, 4500, 6000, 7500, 9000]), rng.randrange(1, 60), rng.choice([0, 1])
        out = ("esc" if days >= 30 else "none") if amount > 5000 else ("ok" if known else "none")
        rows.append(Decision(f"s{i}", i, i + 1, "w", {"amount": float(amount), "days": float(days)}, out, features={"amount": float(amount), "days": float(days), "known": float(known)}))
    return rows


def test_rule_list_recovers_a_regime_with_exceptions_and_reads_as_sentences():
    ds = planted()
    rl = fit_rulelist(ds)
    assert isinstance(rl, RuleList) and rl.rules
    assert induce.accuracy(rl, ds) >= 0.95
    lines = induce.rules(rl)
    assert lines[-1].startswith("otherwise -> none") and all("->" in line for line in lines)
    assert {"amount", "days", "known"} >= induce.features_used(rl) and induce.features_used(rl)


def test_rule_list_is_accepted_wherever_a_tree_is():
    ds = planted()
    rl = fit_rulelist(ds)
    assert induce.predict(rl, ds[0]) == rl.predict(ds[0])
    assert induce.path_features(rl, ds[0]) <= induce.features_used(rl)
    leaves = induce.leaves(rl)
    assert leaves[-1][0] == () and leaves[-1][1].label == rl.default
    j = build_judgment(ds, None)  # builds with a tree; the rule list exports the same shape
    assert j and j["rules"]
    judgment = {"basis": {"observed_ranges": {}}, "rules": [{"when": list(c) or ["always"], "then": leaf.label, "support": f"{leaf.correct}/{leaf.n}", "thin_evidence": False}
                                                           for c, leaf in leaves]}
    decide = replay.rules_decider(judgment)
    assert all(decide(d) == rl.predict(d) for d in ds), "exporting in order and reading first-match reproduces the list"


def test_rule_list_edge_cases():
    import pytest

    with pytest.raises(ValueError):
        fit_rulelist([])
    same = [Decision(f"s{i}", i, i + 1, "w", {"x": 1.0}, "none", features={"x": float(i)}) for i in range(10)]
    rl = fit_rulelist(same)
    assert rl.rules == [] and rl.default == "none" and induce.accuracy(rl, same) == 1.0


def test_fit_auto_keeps_the_plain_tree_when_nothing_clearly_beats_it():
    D = study.domains()["dashboard"]
    ds = study.build(D, 60, 100).decisions
    auto = induce.fit_auto(ds)
    assert auto.choice == "plain features, tree" and auto.cv
    assert auto.accuracy(ds) == induce.accuracy(induce.fit(ds), ds)


def test_fit_auto_finds_ratio_features_on_a_rate_rule_without_being_told():
    S = study.domains()["service"]
    ds = study.build(S, 80, 100).decisions
    train, test = ds[:56], ds[56:]
    auto = induce.fit_auto(train)
    assert auto.ratios, auto.cv
    assert any("/" in line for line in auto.rules())
    plain = induce.accuracy(induce.fit(train), test)
    assert auto.accuracy(test) > plain + 0.1
    assert len(auto.prepare(test)) == len(test) and all(any("/" in f for f in d.features) for d in auto.prepare(test))


def test_fit_auto_with_too_few_decisions_is_the_plain_tree():
    D = study.domains()["dashboard"]
    ds = study.build(D, 8, 100).decisions
    auto = induce.fit_auto(ds)
    assert auto.choice == "plain features, tree"


def clean_rule(n=60, seed=2):
    import random

    rng = random.Random(seed)
    rows = []
    for i in range(n):
        x, y = rng.randrange(0, 10), rng.randrange(0, 10)
        rows.append(Decision(f"s{i}", i, i + 1, "w", {"x": float(x), "y": float(y)}, "act" if x >= 5 else "none", features={"x": float(x), "y": float(y)}))
    return rows


def test_stable_misfits_flag_flipped_labels_and_stay_quiet_on_a_clean_rule():
    rows = clean_rule()
    assert induce.stable_disagreements(rows) == []
    flipped = {5, 17, 33}
    for i in flipped:
        rows[i].outcome = "none" if rows[i].outcome == "act" else "act"
    got = {int(d.session[1:]) for d, _ in induce.stable_disagreements(rows)}
    assert flipped <= got and len(got) <= len(flipped) + 2
    assert [d for d, _ in induce.disagreements(rows, stable=True)] == [d for d, _ in induce.stable_disagreements(rows)]
    assert induce.stable_disagreements(rows[:4]) == [], "too few decisions to resample"


def test_shared_conditions_find_what_a_few_unexplained_choices_have_in_common():
    rows = []
    for i in range(40):
        low = i in (7, 23)
        rows.append(Decision(f"s{i}", i, i + 1, "w", {"gpu": 12.0 if low else 60.0 + i, "loss": 1.0 + i / 10}, "kill" if low else "keep",
                             features={"gpu": 12.0 if low else 60.0 + i, "loss": 1.0 + i / 10}))
    misfits = [rows[7], rows[23]]
    found = induce.shared_conditions(misfits, rows)
    assert found and found[0]["condition"].startswith("gpu <=") and found[0]["covers"] == 2 and found[0]["also_true_of"] == 0
    assert induce.shared_conditions(rows[:1], rows) == []


def test_window_choice_falls_back_to_the_full_history_without_enough_decisions():
    rows = clean_rule(30)
    tree, share = induce.fit_windowed(rows)
    assert share == 1.0 and induce.accuracy(tree, rows) >= 0.95
    tree, share = induce.fit_windowed(clean_rule(100))
    assert share in (1.0, 0.5)
