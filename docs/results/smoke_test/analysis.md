# Analysis of run1

## Capture

- 50 decisions found for 50 choices.
- Readouts exact: 50/50. Owner word: 50/50. Outcome (kill vs not): 50/50.

## Rule fit (14 kills of 50; fitted on the first 35, tested on the last 15)

**default tree:** fits 92% of all choices, predicts 80% of the last 15

- `val_loss <= 2.145 and delta_val_loss <= -0.375 and gpu_util <= 44 -> Kill run (6/6)`
- `val_loss <= 2.145 and delta_val_loss <= -0.375 and gpu_util > 44 -> none (5/6)`
- `val_loss <= 2.145 and delta_val_loss > -0.375 -> none (30/32)`
- `val_loss > 2.145 -> Kill run (5/6)`

**default + ratios:** fits 96% of all choices, predicts 80% of the last 15

- `train_loss/val_loss <= 0.801037 and changed_run_id <= 0.5 -> none (3/3)`
- `train_loss/val_loss <= 0.801037 and changed_run_id > 0.5 -> Kill run (12/12)`
- `train_loss/val_loss > 0.801037 -> none (33/35)`

**lookahead + ratios:** fits 96% of all choices, predicts 80% of the last 15

- `train_loss/val_loss <= 0.801037 and changed_run_id <= 0.5 -> none (3/3)`
- `train_loss/val_loss <= 0.801037 and changed_run_id > 0.5 -> Kill run (12/12)`
- `train_loss/val_loss > 0.801037 -> none (33/35)`

## Report a person would get (ratios on)

# Pilot report

50 cases; you acted on 14 and left 36 alone.

## The rule we found

Read it as a hypothesis about your habits, not as a fact. 'changed_x' means x differs from the previous case.

- train_loss/val_loss <= 0.801037 and changed_run_id <= 0.5 -> none (3/3)
- train_loss/val_loss <= 0.801037 and changed_run_id > 0.5 -> Kill run (12/12)
- train_loss/val_loss > 0.801037 -> none (33/35)

It fits 96% of your 50 choices. Fitted on your first 35, it predicts 80% of your last 15 (always doing the most common thing would get 67%).

## The 2 choice(s) it cannot explain

For each: what the rule expected, what you did, and what was on screen. These are the places to explain why.

- at 54s: you chose Kill run; the rule expected none. Saw: run_id = 4833, epoch = 7, train_loss = 0.52, val_loss = 0.49, gpu_util = 29, grad_norm = 4.37, clock = 11, owner = bob. [O3, tacit 2/4]
- at 242s: you chose Kill run; the rule expected none. Saw: run_id = 5115, epoch = 7, train_loss = 1.52, val_loss = 1.44, gpu_util = 27, grad_norm = 3.16, clock = 11, owner = alice. [O3, tacit 2/4]

## Your own words against the fitted rule

You wrote: "I kill a run when it is overfitting (validation loss clearly above training loss, once it is past the first few epochs) or when it barely uses the GPU, except Carol's runs, which are meant to be light. If I just looked at the same run I leave it."

- The fit uses `changed_run_id`: you mention it.
- The fit uses `train_loss/val_loss`: you mention it.
- You mention `epoch`, but the fit does not use it.
- You mention `gpu_util`, but the fit does not use it.

Judge for yourself: is the fitted rule partly right? What would you correct?

## Next

Answer the questions about the unexplained choices (`python -m playbook pilot elicit pilot_log.json`), which refits the rule with what you tell it. Then judge: is the new rule closer to how you decide?
