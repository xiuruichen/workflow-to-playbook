"""The LLM-driven interview with a fake model: parsing, guard rails, stop rules, fallbacks, no leakage."""

import json

from playbook import elicit, interview, interview_prompts, study
from playbook.decisions import Decision

D = study.domains()["dashboard"]


class FakeChat:
    """Stands in for the model. Records every call; reads the answer to interpret out of the prompt."""

    def __init__(self, question="What were you thinking at that moment?", rating=0.8):
        self.calls, self.question, self.rating = [], question, rating

    def __call__(self, messages, fmt):
        system, user = messages[0]["content"], messages[1]["content"]
        self.calls.append((system, user))
        name = fmt["json_schema"]["name"]
        if name == "question":
            return json.dumps({"question": self.question})
        if name == "critique":
            return json.dumps({"rating": self.rating})
        answer = user.split("Answer:", 1)[1].lower()
        if name == "category":
            return json.dumps({"category": "ITEM" if "warm" in answer or "restart" in answer else "NONE"})
        if name == "phrase":
            word = next((w for w in answer.replace(",", " ").replace(".", " ").split() if "warm" in w or "restart" in w), "")
            return json.dumps({"phrase": word})
        if "warm" in answer or "restart" in answer:
            return json.dumps({"condition": "run just restarted", "kind": "off_screen"})
        return json.dumps({"condition": None, "kind": "none"})


def misfit(seed=100):
    built = study.build(D, 80, seed, hidden_fact=True)
    train = built.decisions[:56]
    qs = elicit.build_questions(train)
    return built, train, qs


def test_question_is_used_only_if_short_a_question_and_without_digits():
    _, _, qs = misfit()
    q = qs[0]
    assert interview.make_question(q, FakeChat(), "v0_open") == ("What were you thinking at that moment?", True)
    for bad in ("Because the loss is above 2.5?", "Tell me why", "Why " + "very " * 40 + "much?", "What happened at 12:00?"):
        text, by_model = interview.make_question(q, FakeChat(question=bad), "v0_open")
        assert not by_model and text == interview.fallback_question(q)
    assert interview.make_question(q, None) == (interview.fallback_question(q), False)

    def broken(messages, fmt):
        raise RuntimeError("model down")

    assert interview.make_question(q, broken) == (interview.fallback_question(q), False)


def test_what_the_model_is_told_never_includes_the_rule_or_the_hidden_fact():
    built, train, qs = misfit()
    chat = FakeChat()
    for q in qs[:3]:
        interview.make_question(q, chat)
    for system, user in chat.calls:
        assert not any(t in (system + user).lower() for t in study.HIDDEN_TERMS)
        assert "->" not in user and "<=" not in user, "the fitted rule is never shown"
    text = interview_prompts.QUESTION_SYSTEM + "".join(s["instruction"] for s in interview_prompts.STRATEGIES.values())
    assert not any(t in text.lower() for t in study.HIDDEN_TERMS)


def test_interpret_guard_rails():
    chat = FakeChat()
    v0 = lambda a, c: interview.interpret(a, [], c, method="v0")  # noqa: E731
    assert v0("It was still warming up.", chat) == {"condition": "run just restarted", "kind": "off_screen"}
    assert v0("Hard to say.", chat)["condition"] is None
    assert v0("ok", chat)["condition"] is None, "too short to read"
    assert v0("warmup", None)["condition"] is None

    def long_condition(messages, fmt):
        return json.dumps({"condition": "the run had only just been brought back after a restart", "kind": "off_screen"})

    assert v0("warmup", long_condition)["condition"] is None, "a condition is at most five words"
    assert v0("warmup", lambda m, f: "not json")["condition"] is None
    assert v0("warmup", lambda m, f: json.dumps({"condition": "x y", "kind": "none"}))["condition"] is None


def test_gated_extraction_needs_an_item_reason_and_a_phrase_taken_from_the_answer():
    chat = FakeChat()
    assert interview.interpret("It was still warming up, so I gave it time.", [], chat) == {"condition": "warming", "kind": "stated"}
    assert interview.interpret("Hard to say.", [], chat)["condition"] is None
    assert interview.interpret("ok", [], chat)["condition"] is None
    assert interview.interpret("warmup", [], None)["condition"] is None

    def classify(verdict, phrase):
        def chat_(messages, fmt):
            name = fmt["json_schema"]["name"]
            return json.dumps({"category": verdict} if name == "category" else {"phrase": phrase})
        return chat_

    assert interview.interpret("still warming up", [], classify("SELF", "warming up"))["condition"] is None, "only ITEM goes on"
    assert interview.interpret("still warming up", [], classify("NONE", "warming up"))["condition"] is None
    assert interview.interpret("still warming up", [], classify("ITEM", "warming up"))["condition"] == "warming up"
    assert interview.interpret("it was still warming up", [], classify("ITEM", "customer on trial"))["condition"] is None, "a phrase not in the answer is dropped"
    too_long = "it was still warming up so I gave it a whole lot of time"
    assert interview.interpret(too_long, [], classify("ITEM", too_long))["condition"] is None, "at most eight words"
    n_phrase = sum(1 for s_, u in chat.calls if "phrase" in s_.lower())
    assert n_phrase >= 3, "three differently worded phrase prompts are used"

    def mixed(messages, fmt):  # the majority of the three phrase prompts wins; a tie goes to the earliest
        name = fmt["json_schema"]["name"]
        if name == "category":
            return json.dumps({"category": "ITEM"})
        mixed.n += 1
        return json.dumps({"phrase": ["still warming", "warming up", "warming up"][mixed.n - 1]})

    mixed.n = 0
    assert interview.interpret("it was still warming up", [], mixed)["condition"] == "warming up"


def test_grounded_matches_stems_and_rejects_invention():
    assert interview.grounded("restarted", "I'd just restarted that run")
    assert interview.grounded("just restarted run", "I'd just restarted that run, so I waited")
    assert interview.grounded("restart", "right after the restarted job")
    assert not interview.grounded("customer on trial", "it was still warming up")
    assert not interview.grounded("", "anything")


def test_case_numbers_are_read_by_code_and_only_offered_cases_count():
    assert interview.parse_held_for("Cases 2, 5", 6) == [2, 5]
    assert interview.parse_held_for("None of them.", 6) == []
    assert interview.parse_held_for("all of them", 3) == [1, 2, 3]
    assert interview.parse_held_for("1 and 9 and 0", 4) == [1], "numbers outside the offered range are ignored"
    assert interview.parse_held_for("no idea", 4) == []


def test_critique_is_clamped_and_never_breaks_the_loop():
    assert interview.critique("q?", "a", FakeChat(rating=3.0)) == 1.0
    assert interview.critique("q?", "a", FakeChat(rating=-1)) == 0.0
    assert interview.critique("q?", "a", lambda m, f: "garbage") is None
    assert interview.critique("q?", "a", None) is None


def test_apply_union_keeps_every_tagged_case_of_one_condition():
    ds = [Decision(f"s{i}", i, i + 1, "w", {"x": 1.0}, "none") for i in range(5)]
    answers = [elicit.Answer("s0", 1.0, "r", "just restarted", [elicit.key(ds[1])]),
               elicit.Answer("s3", 4.0, "r", "Just Restarted", [elicit.key(ds[4])])]
    interview.apply_union(ds, answers)
    assert [d.features["just_restarted"] for d in ds] == [1.0, 1.0, 0.0, 1.0, 1.0]


def test_interview_with_a_clear_expert_names_the_fact_and_explains_decisions():
    built, train, qs = misfit(seed=100)
    chat = FakeChat()
    expert = study.FreeTextExpert(built.hidden, 100, vague_rate=0.0)
    iv = interview.run_interview(train, expert, chat, max_questions=8)
    assert iv.turns and any(t.condition for t in iv.turns)
    named = [t for t in iv.turns if t.condition]
    assert all(study.matches_hidden(t.condition) for t in named)
    assert iv.turns[-1].unexplained_after <= iv.turns[0].unexplained_before
    assert iv.stopped
    first_named = named[0]
    assert first_named.delta > 0, "the first useful answer explains something"
    assert all(a.reason for a in iv.answers), "the person's words are kept verbatim"
    assert evaluate_ok(first_named)


def evaluate_ok(turn):
    e = interview.evaluate_answer(turn, {"specificity": 2})
    return e["named_condition"] and e["measured_delta"] == turn.delta and e["rubric"] == {"specificity": 2}


def test_vague_answers_give_no_feature_and_the_interview_stops_on_patience():
    built, train, qs = misfit(seed=100)
    expert = study.FreeTextExpert(built.hidden, 100, vague_rate=1.0)
    iv = interview.run_interview(train, expert, FakeChat(), max_questions=8, patience=2)
    assert all(t.condition is None for t in iv.turns)
    assert not any(a.fact for a in iv.answers)
    assert len(iv.turns) == 2 and iv.stopped == "2 answers in a row changed nothing"


def test_follow_up_only_counts_offered_cases_and_budget_is_respected():
    built, train, qs = misfit(seed=101)

    def liar(text, ctx):
        if ctx.get("followup"):
            return "Cases 99, 100"  # not offered
        return "It was still warming up."

    iv = interview.run_interview(train, liar, FakeChat(), max_questions=1)
    assert len(iv.turns) == 1 and iv.stopped == "question budget spent"
    assert all(t.held_for == [] for t in iv.turns), "numbers outside the offered cases are ignored"


def test_without_a_model_the_template_is_used_and_nothing_is_extracted():
    built, train, qs = misfit(seed=100)
    expert = study.FreeTextExpert(built.hidden, 100, vague_rate=0.0)
    iv = interview.run_interview(train, expert, None, max_questions=3)
    assert iv.turns and all(not t.by_model and t.condition is None for t in iv.turns)


def test_interview_experiment_reports_gain_and_the_structured_baseline():
    out = study.interview_experiment(D, 100, FakeChat())
    assert {"before", "after", "gain", "structured_gain", "questions", "stopped", "turns", "expert_log"} <= set(out)
    assert out["after"] >= out["before"] - 1e-9
    assert out["expert_log"] and all(e["kind"] in ("clear", "vague", "irrelevant") for e in out["expert_log"])
    assert study.matches_hidden("Run just restarted") and not study.matches_hidden("gut feeling") and not study.matches_hidden(None)


def test_rubric_scores_load_by_decision_key_and_sit_beside_the_measures(tmp_path):
    path = tmp_path / "rubric.jsonl"
    path.write_text('{"key": "s1@5", "specificity": 2, "actionability": 1}\n\n{"key": "s2@9", "specificity": 0}\n', encoding="utf-8")
    rubric = interview.load_rubric(path)
    assert rubric == {"s1@5": {"specificity": 2, "actionability": 1}, "s2@9": {"specificity": 0}}
    assert interview.load_rubric(tmp_path / "missing.jsonl") == {}
    turn = interview.Turn("s1@5", "q?", True, "a", "cond", "off_screen", [], 0.5, 3, 1)
    e = interview.evaluate_answer(turn, rubric[turn.key])
    assert e["measured_delta"] == 2 and e["rubric"]["specificity"] == 2


def warmup_log(tmp_path):
    """A pilot log where the person also waits during an off-screen 'warmup' (every 9th and 10th case)."""
    from tests.test_pilot import person_log

    log = person_log(n=60)
    for c in log["cases"]:
        if c["index"] % 9 in (3, 4):
            c["choice"] = "leave"
    path = tmp_path / "pilot_log.json"
    path.write_text(json.dumps(log), encoding="utf-8")
    return path


def test_pilot_interview_with_a_model_saves_answers_and_reports_the_effect(tmp_path):
    from playbook import pilot

    decisions, _ = pilot.load_log(warmup_log(tmp_path))
    said = []
    result = pilot.ask_loop(decisions, tmp_path / "answers.jsonl", ask=lambda prompt: "it was still warming up", say=said.append,
                            chat=FakeChat(), strategy="v0_open")
    saved = elicit.load_answers(tmp_path / "answers.jsonl")
    assert saved and all(a.reason == "it was still warming up" for a in saved)
    assert any(a.fact and "warm" in a.fact for a in saved)
    assert {"before", "after", "facts"} <= set(result) and result["after"]["unexplained"] <= result["before"]["unexplained"]
    assert any("?" in s for s in said), "the questions were shown"


def test_cli_pilot_elicit_with_llm_uses_the_local_model(tmp_path, monkeypatch, capsys):
    from playbook import __main__ as cli
    from playbook import interview

    path = warmup_log(tmp_path)
    monkeypatch.setattr(interview, "local_chat", lambda stack, settings: FakeChat())
    monkeypatch.setattr("builtins.input", lambda prompt="": "it was still warming up")
    assert cli.main(["pilot", "elicit", str(path), "--llm", "--questions", "v0_counterfactual"]) == 0
    out = capsys.readouterr().out
    assert "Rule before your answers" in out and "Rule after your answers" in out
    assert (tmp_path / "pilot_answers.jsonl").is_file()


def test_misfit_orders_are_permutations_and_time_is_the_original_order():
    import pytest

    built, train, qs = misfit(seed=102)
    assert len(qs) >= 4
    assert [elicit.key(q.decision) for q in interview.rank_misfits(train, qs, "time")] == [elicit.key(q.decision) for q in qs]
    for order in ("surprise", "burst", "cluster"):
        ranked = interview.rank_misfits(train, qs, order)
        assert sorted(elicit.key(q.decision) for q in ranked) == sorted(elicit.key(q.decision) for q in qs)
        assert [elicit.key(q.decision) for q in ranked] == [elicit.key(q.decision) for q in interview.rank_misfits(train, qs, order)], "deterministic"
    with pytest.raises(ValueError):
        interview.rank_misfits(train, qs, "random")


def test_burst_order_puts_misfits_with_misfit_neighbours_first():
    built, train, qs = misfit(seed=102)
    index = {elicit.key(d): i for i, d in enumerate(train)}
    at = {index[elicit.key(q.decision)] for q in qs}
    near = lambda q: sum((index[elicit.key(q.decision)] + k) in at for k in (-1, 1))  # noqa: E731
    ranked = interview.rank_misfits(train, qs, "burst")
    counts = [near(q) for q in ranked]
    assert counts == sorted(counts, reverse=True)


def test_group_question_tags_the_cases_the_person_names_and_only_those():
    built, train, qs = misfit(seed=100)
    expert = study.FreeTextExpert(built.hidden, 100, vague_rate=0.0)
    iv = interview.run_interview(train, expert, FakeChat(), group_first=True, max_questions=2)
    first = iv.turns[0]
    assert first.key == "group" and first.condition and "warm" in first.condition
    assert first.held_for and all(k in built.hidden for k in first.held_for), "only the cases the expert numbered are tagged"
    assert first.delta > 0
    assert iv.answers[0].fact == first.condition
    for a in iv.answers[:1]:
        assert a.key in first.held_for, "the answer is anchored on a tagged case"


def test_group_question_is_skipped_when_there_is_no_group_of_three():
    built, train, qs = misfit(seed=109)
    few = qs[:2]
    out = interview.group_turn(train, few, lambda t, c: "x", FakeChat(), "gated")
    assert out is None


def test_a_vague_group_answer_tags_nothing():
    built, train, qs = misfit(seed=100)
    expert = study.FreeTextExpert(built.hidden, 100, vague_rate=1.0)
    iv = interview.run_interview(train, expert, FakeChat(), group_first=True, max_questions=1)
    assert iv.turns[0].condition is None and iv.turns[0].held_for == []
