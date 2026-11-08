# Amendment 3: ratio features, seeds [6, 7, 8, 9, 10] (commit b325fd5)

Held-out agreement, mean (min-max).

| domain | visits | label noise | A (default) | R (+ ratio features) |
|---|---|---|---|---|
| service | 40 | 0.0 | 0.57 (0.42-0.75) | 0.78 (0.67-0.92) |
| service | 80 | 0.0 | 0.72 (0.67-0.83) | 0.93 (0.83-1.00) |
| service | 60 | 0.1 | 0.59 (0.44-0.72) | 0.81 (0.72-0.89) |
| dashboard | 40 | 0.0 | 0.88 (0.42-1.00) | 0.88 (0.42-1.00) |
| dashboard | 80 | 0.0 | 1.00 (1.00-1.00) | 1.00 (1.00-1.00) |
| triage | 40 | 0.0 | 0.75 (0.50-1.00) | 0.75 (0.50-1.00) |
| triage | 80 | 0.0 | 0.88 (0.75-1.00) | 0.88 (0.75-1.00) |

**service: R at least A in every cell: True; mean gain +0.213 (bar +0.10). Cost check (dashboard, triage): mean change +0.000 (bar -0.03). R at 80 visits on service: 0.93 (predicted below 0.90); A: 0.72 (predicted below 0.90). -> R is ADOPTED as an option.**
