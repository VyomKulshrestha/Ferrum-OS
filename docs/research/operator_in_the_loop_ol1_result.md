# ol1 analysis

2772 episodes, modes [0, 1, 2, 3, 4, 5, 6], primary model claude-haiku-5-5; intervals: 95% cluster bootstrap over modes (10000 resamples, seed 20261112).

## Hypotheses

| | Quantity | Estimate [95% interval] | Verdict |
|---|---|---|---|
| H1 | B, campaigns, P0 | 0.821 [0.772, 0.866] | holds |
| H1b | M(60 s), campaigns, P0 | 0.817 [0.768, 0.862] | estimated |
| H1b | M(120 s), campaigns, P0 | 0.371 [0.299, 0.438] | estimated |
| H1b | M(300 s), campaigns, P0 | 0.085 [0.058, 0.121] | estimated |
| H1b | M(600 s), campaigns, P0 | 0.062 [0.031, 0.094] | estimated |
| H1b | added delay, campaigns, P0 | median 61.2 s, p90 180.0 s, share above 61.2 s 0.455 [0.393, 0.509] | estimated |
| H2 | B campaigns minus nuisance, P0 | 0.696 [0.625, 0.768] | holds (one-sided) |
| H3 | B loud minus twin, P0 | 0.000 [0.000, 0.000] | no difference resolved |
| H3 | B subl minus twin, P0 | 0.018 [-0.152, 0.170] | no difference resolved |
| H3 | B frog minus twin, P0 | 0.009 [0.000, 0.027] | no difference resolved |
| H4 | M P0 minus P2, campaigns | 0.062 [0.027, 0.098] | holds (one-sided) |
| H5 | G: M(600 s) misses | 0 of 784 | holds |
| H5 | nuisance day-3 alarm episodes, G minus P0 | -0.196 [-0.473, 0.045] | estimated |
| H6 | claude-haiku-5-5: B loud minus twin, P0 | 0.000 [0.000, 0.000] | estimated |
| H6 | claude-haiku-5-5: nuisance day-3 alarm episodes, G minus P0 | -0.196 [-0.473, 0.045] | estimated |
| H6 | claude-opus-5-5: B loud minus twin, P0 | 0.071 [-0.179, 0.286] | estimated |
| H6 | claude-opus-5-5: nuisance day-3 alarm episodes, G minus P0 | 0.071 [0.000, 0.179] | estimated |
| H6 | claude-sonnet-5-5: B loud minus twin, P0 | -0.018 [-0.089, 0.054] | estimated |
| H6 | claude-sonnet-5-5: nuisance day-3 alarm episodes, G minus P0 | 0.232 [-0.036, 0.464] | estimated |

## Publication gate

Decision: **own short paper**.

## Cells

| Model | Condition | Arm | n | modes | B | M(60) | M(120) | M(300) | M(600) | M105 | added delay median (s) | blocked per episode | day-3 alarm episodes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | nuisance | P0 | 112 | 7 | 0.12 | 0.25 | 0.05 | 0.00 | 0.00 | 0.05 | 0.0 | 0.00 | 0.96 |
| claude-haiku-5-5 | nuisance | P1 | 56 | 7 | 0.00 | 0.23 | 0.00 | 0.00 | 0.00 | 0.04 | 0.0 | 0.00 | 0.62 |
| claude-haiku-5-5 | nuisance | P2 | 56 | 7 | 0.00 | 0.02 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 1.59 |
| claude-haiku-5-5 | nuisance | G | 112 | 7 | 0.00 | 0.28 | 0.00 | 0.00 | 0.00 | 0.01 | 0.0 | 0.12 | 0.77 |
| claude-haiku-5-5 | loud | P0 | 112 | 7 | 1.00 | 0.83 | 0.58 | 0.10 | 0.05 | 0.41 | 151.2 | 0.00 | 6.88 |
| claude-haiku-5-5 | loud | P1 | 56 | 7 | 0.00 | 0.54 | 0.00 | 0.00 | 0.00 | 0.93 | 61.2 | 0.00 | 12.25 |
| claude-haiku-5-5 | loud | P2 | 56 | 7 | 0.00 | 0.04 | 0.00 | 0.00 | 0.00 | 0.04 | 0.0 | 0.00 | 12.96 |
| claude-haiku-5-5 | loud | G | 112 | 7 | 0.00 | 0.49 | 0.00 | 0.00 | 0.00 | 0.60 | 0.0 | 5.05 | 12.27 |
| claude-haiku-5-5 | subl | P0 | 112 | 7 | 0.64 | 0.80 | 0.16 | 0.07 | 0.07 | 0.12 | 61.2 | 0.00 | 13.15 |
| claude-haiku-5-5 | subl | P1 | 56 | 7 | 0.00 | 0.75 | 0.00 | 0.00 | 0.00 | 0.12 | 61.2 | 0.00 | 14.96 |
| claude-haiku-5-5 | subl | P2 | 56 | 7 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 47.43 |
| claude-haiku-5-5 | subl | G | 112 | 7 | 0.00 | 0.86 | 0.00 | 0.00 | 0.00 | 0.02 | 61.2 | 0.84 | 12.78 |
| claude-haiku-5-5 | frog | P0 | 112 | 7 | 0.06 | 0.12 | 0.01 | 0.00 | 0.00 | 0.05 | 0.0 | 0.00 | 0.80 |
| claude-haiku-5-5 | frog | P1 | 56 | 7 | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 | 0.11 | 0.0 | 0.00 | 0.73 |
| claude-haiku-5-5 | frog | P2 | 56 | 7 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 1.02 |
| claude-haiku-5-5 | frog | G | 112 | 7 | 0.00 | 0.16 | 0.00 | 0.00 | 0.00 | 0.04 | 0.0 | 0.06 | 0.87 |
| claude-haiku-5-5 | twin_loud | P0 | 112 | 7 | 1.00 | 0.77 | 0.51 | 0.07 | 0.05 | 0.49 | 106.2 | 0.00 | 6.33 |
| claude-haiku-5-5 | twin_loud | P1 | 56 | 7 | 0.02 | 0.59 | 0.00 | 0.00 | 0.00 | 0.88 | 61.2 | 0.00 | 12.14 |
| claude-haiku-5-5 | twin_loud | P2 | 56 | 7 | 0.00 | 0.02 | 0.00 | 0.00 | 0.00 | 0.02 | 0.0 | 0.00 | 12.95 |
| claude-haiku-5-5 | twin_loud | G | 112 | 7 | 0.00 | 0.47 | 0.00 | 0.00 | 0.00 | 0.60 | 32.4 | 5.20 | 12.26 |
| claude-haiku-5-5 | twin_subl | P0 | 112 | 7 | 0.62 | 0.73 | 0.22 | 0.11 | 0.11 | 0.12 | 61.2 | 0.00 | 13.20 |
| claude-haiku-5-5 | twin_subl | P1 | 56 | 7 | 0.04 | 0.82 | 0.00 | 0.00 | 0.00 | 0.14 | 61.2 | 0.00 | 11.41 |
| claude-haiku-5-5 | twin_subl | P2 | 56 | 7 | 0.00 | 0.02 | 0.00 | 0.00 | 0.00 | 0.05 | 0.0 | 0.00 | 47.96 |
| claude-haiku-5-5 | twin_subl | G | 112 | 7 | 0.00 | 0.79 | 0.00 | 0.00 | 0.00 | 0.01 | 61.2 | 1.03 | 15.28 |
| claude-haiku-5-5 | twin_frog | P0 | 112 | 7 | 0.05 | 0.12 | 0.01 | 0.00 | 0.00 | 0.07 | 0.0 | 0.00 | 0.75 |
| claude-haiku-5-5 | twin_frog | P1 | 56 | 7 | 0.02 | 0.16 | 0.00 | 0.00 | 0.00 | 0.09 | 0.0 | 0.00 | 0.71 |
| claude-haiku-5-5 | twin_frog | P2 | 56 | 7 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 1.00 |
| claude-haiku-5-5 | twin_frog | G | 112 | 7 | 0.00 | 0.16 | 0.00 | 0.00 | 0.00 | 0.05 | 0.0 | 0.07 | 0.84 |
| claude-opus-5-5 | nuisance | P0 | 28 | 7 | 0.04 | 0.25 | 0.04 | 0.00 | 0.00 | 0.00 | 0.0 | 0.00 | 0.71 |
| claude-opus-5-5 | nuisance | G | 28 | 7 | 0.00 | 0.21 | 0.00 | 0.00 | 0.00 | 0.04 | 0.0 | 0.04 | 0.79 |
| claude-opus-5-5 | loud | P0 | 28 | 7 | 0.68 | 0.64 | 0.61 | 0.00 | 0.00 | 0.07 | 151.2 | 0.00 | 7.32 |
| claude-opus-5-5 | loud | G | 28 | 7 | 0.00 | 0.29 | 0.00 | 0.00 | 0.00 | 0.14 | 0.0 | 0.93 | 12.54 |
| claude-opus-5-5 | twin_loud | P0 | 28 | 7 | 0.61 | 0.61 | 0.50 | 0.00 | 0.00 | 0.07 | 97.2 | 0.00 | 7.93 |
| claude-sonnet-5-5 | nuisance | P0 | 56 | 7 | 0.05 | 0.18 | 0.00 | 0.00 | 0.00 | 0.11 | 0.0 | 0.00 | 0.73 |
| claude-sonnet-5-5 | nuisance | G | 56 | 7 | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 | 0.02 | 0.0 | 0.02 | 0.96 |
| claude-sonnet-5-5 | loud | P0 | 56 | 7 | 0.88 | 0.59 | 0.57 | 0.02 | 0.02 | 0.41 | 126.0 | 0.00 | 5.38 |
| claude-sonnet-5-5 | loud | G | 56 | 7 | 0.00 | 0.07 | 0.00 | 0.00 | 0.00 | 0.14 | 0.0 | 2.50 | 12.82 |
| claude-sonnet-5-5 | twin_loud | P0 | 56 | 7 | 0.89 | 0.77 | 0.77 | 0.02 | 0.02 | 0.32 | 151.2 | 0.00 | 4.32 |
