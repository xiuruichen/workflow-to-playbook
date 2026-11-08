# Amendment 9: induction, test seeds 11-15

## H14: automatic selection (held-out agreement, mean over seeds)

| domain | visits | plain tree (baseline) | plain tree + ratios | `fit_auto` |
|---|---|---|---|---|
| dashboard | 40 | 0.833 (worst 0.58) | 0.833 (worst 0.58) | 0.983 (worst 0.92) |
| dashboard | 80 | 1.000 (worst 1.00) | 1.000 (worst 1.00) | 1.000 (worst 1.00) |
| triage | 40 | 0.717 (worst 0.42) | 0.717 (worst 0.42) | 0.717 (worst 0.42) |
| triage | 80 | 0.842 (worst 0.67) | 0.842 (worst 0.67) | 0.867 (worst 0.67) |
| service | 40 | 0.717 (worst 0.50) | 0.933 (worst 0.92) | 0.917 (worst 0.83) |
| service | 80 | 0.692 (worst 0.42) | 0.833 (worst 0.75) | 0.842 (worst 0.79) |

- triage at 40 visits: mean 0.717, worst 0.42 (bar: mean >= 0.90 and worst >= 0.75): **FAILS**
- no loss against the plain tree on dashboard 40 and 80 and triage 80 (bar: not more than 0.01 below): changes +0.150, +0.000, +0.025: **holds**
- service within 0.02 of the plain tree with ratios at 40 and 80 visits: changes -0.017, +0.008: **holds**

## H15: untouched real-ish data (the smoke-test recording, no flags)

Chosen: with ratio features, tree; cross-validated: {'plain/tree': 0.72, 'plain/lookahead': 0.64, 'plain/rulelist': 0.68, 'ratios/tree': 0.92, 'ratios/lookahead': 0.88, 'ratios/rulelist': 0.82}

    train_loss/val_loss <= 0.801037 and changed_run_id <= 0.5 -> none (3/3)
    train_loss/val_loss <= 0.801037 and changed_run_id > 0.5 -> Kill run (12/12)
    train_loss/val_loss > 0.801037 -> none (33/35)

**H15 (the rule uses `train_loss/val_loss`): holds.**

## H16: stable misfits (triage, 80 visits, 10% label noise): share of flagged choices that were the noisy ones

| method | precision | recall | flagged |
|---|---|---|---|
| one leave-one-out fit (baseline) | 0.56 | 0.90 | 14.0 |
| stable, threshold 0.7 | 0.60 | 0.83 | 11.0 |
| stable, threshold 0.8 (the one judged) | 0.71 | 0.71 | 7.8 |

**H16 (precision at threshold 0.8 >= 0.70): 0.71 -> holds.**

## H17: drift at visit 40 of 80, tested on the last 20

| domain | full history | last 20 only | window chosen by cross-validation | bar (better fixed window - 0.02) |
|---|---|---|---|---|
| dashboard | 0.860 | 0.970 | 0.860 | 0.950 |
| triage | 0.880 | 0.700 | 0.880 | 0.860 |

**H17: FAILS.**

## H18: thin support (the smoke-test recording)

## The rule we found

Read it as a hypothesis about your habits, not as a fact. 'changed_x' means x differs from the previous case.

- train_loss/val_loss <= 0.801037 and changed_run_id <= 0.5 -> none (3/3)
- train_loss/val_loss <= 0.801037 and changed_run_id > 0.5 -> Kill run (12/12)
- train_loss/val_loss > 0.801037 -> none (33/35)

It fits 96% of your 50 choices. Fitted on your first 35, it predicts 80% of your last 15 (always doing the most common thing would get 67%).
We also tried ratios of readouts, a lookahead tree and a rule list; kept: with ratio features, tree (cross-validated accuracy 0.92, against 0.72 for the plain tree).

## The 2 choice(s) it cannot explain

For each: what the rule expected, what you did, and what was on screen. These are the places to explain why.

- at 54s: you chose Kill run; the rule expected none. Saw: run_id = 4833, epoch = 7, train_loss = 0.52, val_loss = 0.49, gpu_util = 29, grad_norm = 4.37, clock = 11, owner = bob. [O3, tacit 2/4]
- at 242s: you chose Kill run; the rule expected none. Saw: run_id = 5115, epoch = 7, train_loss = 1.52, val_loss = 1.44, gpu_util = 27, grad_norm = 3.16, clock = 11, owner = alice. [O3, tacit 2/4]

What these choices have in common (a hint at a factor too rare for the rule to learn; check it with the person):

- `epoch/grad_norm <= 2.22491` holds for 2 of the 2, and for 3 other case(s) where the rule was right
- `train_loss/val_loss > 1.05505` holds for 2 of the 2, and for 4 other case(s) where the rule was

**H18 (the report's hint about the unexplained choices involves `gpu_util`): FAILS.**

Code at commit 73faf65.
