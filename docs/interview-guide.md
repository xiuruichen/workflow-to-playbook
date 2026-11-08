# Interview guide: what to ask when the recording does not explain a choice

A brief for whoever designs the questions and decides how to judge the answers. Both are open; the code is built so that you can change them without touching anything else.

## What the interview is for

The decision tools fit a short rule to a person's choices ([tacit-knowledge.md](tacit-knowledge.md)). Some choices the rule gets wrong. Those are where the person knew something the screen did not show, or where the rule is simply incomplete. The interview asks about those choices, and **an answer is only useful if it ends as a condition the rule can use** (a named fact, plus the other cases it held for), because the test of an interview is whether the refitted rule predicts the person's *later* choices better.

Design aim, from the literature we adapt ([related-work.md](related-work.md)): targeted questions that draw out knowledge missing from the record (Brennig 2025), asked iteratively with some self-critique about whether the answers are filling the gap (Zuin et al. 2025). Only the abstracts of those papers were read.

## What exists (v0)

`playbook/interview.py` runs the loop; `playbook/interview_prompts.py` holds the wording.

For each choice the fitted rule cannot explain:
1. **A question** is written by a local model from what was on screen and what happened (never the fitted rule). If it is not short, not a question, or contains a digit, a plain template is used instead.
2. **The answer** (free text, kept verbatim) is read by the model into a short **condition** (at most five words) or none.
3. **A follow-up** asks which other offered cases the condition also held for; the numbers are read by code.
4. The condition becomes a 0/1 feature, the rule is refitted, and the **measured effect** (how many choices are newly explained) is recorded next to the model's own 0-1 rating of the answer.
5. It stops when nothing is left to explain, after 8 questions, or after a few answers in a row that explained nothing.

Fixed on purpose (these are checks, not wording): the model never sees the rule; a condition must be short; vague answers must give none; only offered cases can be tagged; the model's rating never overrides the measured effect.

## What is yours to decide

| Open question | Where it lives | v0 |
|---|---|---|
| **What to ask.** Candidate kinds: the criteria they used; what would have made them choose otherwise (counterfactual); what happened earlier that shaped it; what they knew that is not on screen; how sure they were | `STRATEGIES` in `interview_prompts.py` | three plain placeholders, `v0_open`, `v0_counterfactual`, `v0_context` |
| **Order and number** of questions; which misfits to ask first; when to give up on a person | `run_interview` (`max_questions`, `patience`, question order) | time order, 8 questions, stop after a few non-answers |
| **Follow-ups.** When to probe a vague answer, when to ask for an example, how to handle a contradiction with an earlier answer | `run_interview` | one follow-up, only to tag other cases |
| **Not leading.** Wording that does not suggest the answer; whether to show the rule's guess ("in similar situations you chose X") | `make_question`, `describe` | the guess is shown, no thresholds |
| **What a good answer is.** Specific, actionable (becomes a feature), consistent with earlier answers, backed by evidence (the refit improves), calibrated (the person says how sure they are) | `evaluate_answer`, `load_rubric` | mechanical measures only |
| **Success with a real expert.** What counts, beyond the held-out score: the person says "yes, that is it"; the rule changes in a way they endorse | [pilot-guide.md](pilot-guide.md) | the guide's four scoring questions |

## Trying a different set of questions

1. Add an entry to `STRATEGIES` in `playbook/interview_prompts.py`: a name, a description for readers, and an `instruction` appended to the question-writing prompt.
2. Compare it with the others on the same simulated experts:
   ```bash
   python scripts/compare_question_sets.py --strategies template,v0_open,my_strategy
   python scripts/compare_question_sets.py --strategies v0_open,my_strategy --expert llm   # answers depend on the wording
   ```
   It prints held-out gain, questions asked, how often a condition was named, how often it matches the planted fact, and the model's mean self-rating, per strategy. It uses development seeds; the pre-registered test seeds (6–10) are for the final run only ([evaluation-protocol.md](evaluation-protocol.md), amendment 7).
3. Use it with a person: `python -m playbook pilot elicit pilot_log.json --llm --questions my_strategy`.

## Scoring answers by hand

Write one JSON object per line to a file, keyed by the decision key (`Turn.key`, for example `visit013@402`), with any scores you define:

```json
{"key": "visit013@402", "specificity": 2, "actionability": 1, "evidence": 2}
```

`interview.load_rubric(path)` reads it and `interview.evaluate_answer(turn, rubric[key])` puts your scores beside the mechanical measures (named a condition, tagged other cases, measured effect, the model's rating), so a judgment about an answer can be compared with what the answer did.

## What we know so far

See [results.md](results.md#the-llm-driven-interview) for the measured results. Things to keep in mind:
- The simulated experts are scripted: their answers do not depend on how the question is worded, except with the LLM persona, which is noisy and shares the interviewer's model.
- The interviewer is a 4B model running locally. Extraction of a condition from a short answer is the weakest step; it sometimes misses a clear reason and sometimes reads an irrelevant remark as a condition. Whether a condition is *useful* is therefore decided by the measured effect on the rule, not by the model.
- Real people ramble, contradict themselves and answer a different question. None of that is tested until the pilot.
