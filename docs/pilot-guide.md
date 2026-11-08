# Pilot guide: one real person, about 45 minutes

Why: everything so far was checked on scripted "people" who follow a rule we planted. The roadmap's success statement needs a real person whose rule we do not know: *the person recognizes the fitted rule as partly right and corrects it, and the corrected rule predicts later decisions better than the first fit.* This pilot tests that once, with n = 1. It supports no claim about experts in general.

## Before you start

- **Consent.** The person is told what is recorded (the cases shown, each choice, how long it took, any reasons and the rule they write), that nothing leaves the computer, and that they can stop at any time and have the files deleted. If it is not the researcher themself, write down that they agreed. Ethics for anyone beyond the researcher is still an open item in the roadmap.
- **Pick a theme the person knows.** `run` (checking a training run), `invoice` or `ticket`. A theme where they have real experience gives a real rule; an unfamiliar one gives a rule made up on the spot (still a rule, but not tacit knowledge).
- Fix the seed and the number of cases in advance and note them (default seed 7, 60 cases: the learning curve in `docs/results/exploratory.md` shows 40 is thin for a rule with more than one condition; at about 10 seconds a case, 60 takes 10-15 minutes). Do not look at the cases first.

## Run it

```bash
python -m playbook pilot make --theme run --cases 60 --seed 7      # writes pilot.html
```

1. Open `pilot.html` in a browser, full screen. Optionally start `python -m playbook record` first to also record the screen (this tests the capture path on a human; the pilot itself does not need it).
2. The person goes through the cases at their own pace (**A** = act, **L** = leave it alone; a one-line reason is optional) and then writes, in their own words, *when* they act. **Do not hint at what would be a good rule.**
3. They download the log (`pilot_log.json`). Then:

```bash
python -m playbook pilot report pilot_log.json [--ratios]     # pilot_report.md (--ratios also tries quotients of readouts, useful if the person judges by a rate): the fitted rule, held-out accuracy, unexplained choices, their words against the rule
python -m playbook pilot elicit pilot_log.json     # interview about the unexplained choices; refits the rule from what they say
```

## What to ask afterwards (write down their words)

1. Read the fitted rule to them. *Is it partly right? What is wrong or missing?*
2. For each unexplained choice: *what did you know that the screen did not show?* (`pilot elicit` asks this and turns a named condition into a feature.)
3. *Did you change how you decided during the session?* (A rule that drifts is a finding, not noise.)

## How to score it (decide before looking at the report)

| Question | Counts as yes when |
|---|---|
| Partly right | the person says at least one condition in the fitted rule is something they actually use |
| Corrected | they name a condition the fit missed or reject one it used |
| Better after the correction | after `pilot elicit`, the rule explains more of their choices and has fewer unexplained ones, and the person agrees it reads closer to how they decide |
| Match with their own words | `pilot_report.md` lists which fitted features the person did and did not mention |

Report all four, including a no. Held-out accuracy in the report uses the first 70% of cases to fit and the last 30% to test (18 cases at 60), so one case moves it by 8 points.

## Limits

n = 1; the cases are synthetic; the page logs choices itself, so this does not test screen capture or OCR on a human unless the screen was recorded as well; a person told to "decide" may make up a rule; the rule they state afterwards may differ from what they did, which is exactly what the comparison looks at. A second stage with the person's real task (a recorded session of work they actually do, with `record`, `decisions`, `induce`, `elicit`, `replay`) is the next step if this one works, and it needs on-screen readouts to be text (see the README), and for a long recording of many checks `python -m playbook decisions --dwell 3 --navigation <the words on the 'next item' controls>` (the defaults assume one check per recording; see E7 in NOTES.md).
