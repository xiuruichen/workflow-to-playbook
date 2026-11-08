# Exploratory studies E1-E6 (seeds [1, 2, 3, 4, 5]; commit b67b1e2)

Exploratory: no pre-set pass/fail criterion. Held-out agreement, mean (min-max) over 5 seeds, chronological 70/30 split.

## E1 learning curve (visits)

| domain | value | greedy | lookahead |
|---|---|---|---|
| dashboard | 10 | 0.80 (0.67-1.00) | 0.73 (0.33-1.00) |
| dashboard | 20 | 0.77 (0.33-1.00) | 0.93 (0.67-1.00) |
| dashboard | 30 | 0.91 (0.56-1.00) | 0.91 (0.56-1.00) |
| dashboard | 40 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 60 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 80 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 120 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| triage | 10 | 0.80 (0.67-1.00) | 0.80 (0.67-1.00) |
| triage | 20 | 0.50 (0.17-0.67) | 0.63 (0.50-0.83) |
| triage | 30 | 0.60 (0.11-0.89) | 0.62 (0.11-0.89) |
| triage | 40 | 0.87 (0.67-1.00) | 0.87 (0.67-1.00) |
| triage | 60 | 0.86 (0.72-1.00) | 0.86 (0.72-1.00) |
| triage | 80 | 0.89 (0.75-1.00) | 0.93 (0.79-1.00) |
| triage | 120 | 0.86 (0.69-1.00) | 0.97 (0.86-1.00) |

## E2 label noise

| domain | value | greedy | lookahead | flagged are noisy (precision) | noisy flagged (recall) |
|---|---|---|---|---|---|
| dashboard | 0.0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) | - | - |
| dashboard | 0.05 | 0.97 (0.89-1.00) | 0.97 (0.89-1.00) | 0.93 (0.67-1.00) | 1.00 (1.00-1.00) |
| dashboard | 0.1 | 0.93 (0.89-0.94) | 0.86 (0.50-0.94) | 0.84 (0.67-1.00) | 1.00 (1.00-1.00) |
| dashboard | 0.2 | 0.77 (0.56-0.89) | 0.77 (0.56-0.89) | 0.71 (0.52-1.00) | 0.91 (0.60-1.00) |
| triage | 0.0 | 0.86 (0.72-1.00) | 0.86 (0.72-1.00) | - | - |
| triage | 0.05 | 0.72 (0.61-0.78) | 0.72 (0.61-0.78) | 0.42 (0.11-0.75) | 1.00 (1.00-1.00) |
| triage | 0.1 | 0.72 (0.67-0.83) | 0.73 (0.67-0.83) | 0.50 (0.29-0.83) | 0.96 (0.80-1.00) |
| triage | 0.2 | 0.58 (0.50-0.72) | 0.57 (0.33-0.72) | 0.49 (0.34-0.76) | 0.91 (0.77-1.00) |

## E3 OCR misreads

| domain | value | greedy | lookahead |
|---|---|---|---|
| dashboard | 0.0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 0.02 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 0.05 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 0.1 | 0.81 (0.56-0.94) | 0.81 (0.56-0.94) |
| triage | 0.0 | 0.86 (0.72-1.00) | 0.86 (0.72-1.00) |
| triage | 0.02 | 0.86 (0.72-1.00) | 0.86 (0.72-1.00) |
| triage | 0.05 | 0.84 (0.72-1.00) | 0.84 (0.72-1.00) |
| triage | 0.1 | 0.81 (0.72-0.94) | 0.87 (0.72-1.00) |

## E4a distractor readouts

| domain | value | greedy | lookahead |
|---|---|---|---|
| dashboard | 0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 2 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 4 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| dashboard | 8 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| triage | 0 | 0.86 (0.72-1.00) | 0.86 (0.72-1.00) |
| triage | 2 | 0.82 (0.72-1.00) | 0.86 (0.72-1.00) |
| triage | 4 | 0.83 (0.67-1.00) | 0.83 (0.67-1.00) |
| triage | 8 | 0.82 (0.61-1.00) | 0.82 (0.61-1.00) |

## E4b rule drift (held-out = the last 20 of 80 visits)

| domain | fitted on | agreement |
|---|---|---|
| dashboard | greedy: all earlier visits | 0.89 (0.75-1.00) |
| dashboard | greedy: only visits after the change | 0.87 (0.75-1.00) |
| dashboard | lookahead: all earlier visits | 0.89 (0.75-1.00) |
| dashboard | lookahead: only visits after the change | 0.96 (0.90-1.00) |
| triage | greedy: all earlier visits | 0.86 (0.75-0.95) |
| triage | greedy: only visits after the change | 0.67 (0.50-0.80) |
| triage | lookahead: all earlier visits | 0.83 (0.75-0.95) |
| triage | lookahead: only visits after the change | 0.68 (0.50-0.85) |

## E5 imperfect expert (80 visits, hidden warmup fact, one elicitation round, greedy)

| domain | expert | held-out before | after |
|---|---|---|---|
| dashboard | names the right fact 100% of the time, otherwise says nothing useful | 0.81 (0.67-0.92) | 0.85 (0.67-1.00) |
| dashboard | names the right fact 80% of the time, otherwise says nothing useful | 0.81 (0.67-0.92) | 0.85 (0.67-1.00) |
| dashboard | names the right fact 60% of the time, otherwise says nothing useful | 0.81 (0.67-0.92) | 0.85 (0.67-1.00) |
| dashboard | names the right fact 0% of the time, otherwise says nothing useful | 0.81 (0.67-0.92) | 0.81 (0.67-0.92) |
| dashboard | names the right fact 60% of the time, otherwise tags the wrong decisions | 0.81 (0.67-0.92) | 0.85 (0.67-1.00) |
| dashboard | names the right fact 0% of the time, otherwise tags the wrong decisions | 0.81 (0.67-0.92) | 0.83 (0.67-1.00) |
| triage | names the right fact 100% of the time, otherwise says nothing useful | 0.68 (0.50-0.83) | 0.71 (0.50-0.92) |
| triage | names the right fact 80% of the time, otherwise says nothing useful | 0.68 (0.50-0.83) | 0.71 (0.50-0.92) |
| triage | names the right fact 60% of the time, otherwise says nothing useful | 0.68 (0.50-0.83) | 0.71 (0.50-0.92) |
| triage | names the right fact 0% of the time, otherwise says nothing useful | 0.68 (0.50-0.83) | 0.68 (0.50-0.83) |
| triage | names the right fact 60% of the time, otherwise tags the wrong decisions | 0.68 (0.50-0.83) | 0.69 (0.50-0.88) |
| triage | names the right fact 0% of the time, otherwise tags the wrong decisions | 0.68 (0.50-0.83) | 0.64 (0.38-0.83) |

## E6 observability class of each decision vs ground truth (40 visits x 5 seeds)

Truth: O5 if the planted outcome depends on an earlier visit, else O4 if the person did nothing, else O3.

- dashboard: O4->O5: 81, O4->path:O4: 81, O5->O5: 119, O5->path:O5: 119
- triage: O3->O3: 12, O3->O5: 47, O3->path:O3: 59, O4->O4: 18, O4->O5: 64, O4->path:O4: 60, O4->path:O5: 22, O5->O3: 9, O5->O4: 1, O5->O5: 49, O5->path:O3: 12, O5->path:O4: 3, O5->path:O5: 44
