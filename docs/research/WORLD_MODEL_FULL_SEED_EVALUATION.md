# FerrumOS full-pipeline seed evaluation

Every row independently trains the JEPA representation and transition MLP. The authored
500-episode safety fixture is fixed and is never used for checkpoint selection.

| Seed | Transition normalized error | H=3 normalized error | FNR | FPR | Balanced accuracy | AUROC | AUPRC |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 17 | 1.54% | 15.47% | 28.4% | 10.4% | 80.6% | 0.828 | 0.874 |
| 42 | 1.85% | 4.11% | 37.6% | 10.0% | 76.2% | 0.783 | 0.839 |
| 91 | 1.67% | 13.16% | 25.2% | 13.6% | 80.6% | 0.835 | 0.874 |
| 123 | 1.63% | 6.06% | 18.8% | 16.4% | 82.4% | 0.858 | 0.888 |
| 2026 | 1.57% | 27.04% | 25.2% | 16.8% | 79.0% | 0.825 | 0.865 |

The selected fixed-encoder checkpoint's 3.87% H=3 error is not one of these
end-to-end runs. Each row above retrains both the representation and transition
model; the larger values expose seed sensitivity plus compounding rollout error
instead of reusing the selected seed-42 representation.

## Aggregate

- `transition_normalized_mse`: mean 1.65%, sample SD 0.12 percentage points, 95% t interval [1.50%, 1.81%], range [1.54%, 1.85%].
- `transition_rollout_h3_normalized_mse`: mean 13.17%, sample SD 9.09 percentage points, 95% t interval [1.89%, 24.45%], range [4.11%, 27.04%].
- `combined_false_negative_rate`: mean 27.04%, sample SD 6.86 percentage points, 95% t interval [18.53%, 35.55%], range [18.80%, 37.60%].
- `combined_false_positive_rate`: mean 13.44%, sample SD 3.21 percentage points, 95% t interval [9.46%, 17.42%], range [10.00%, 16.80%].
- `combined_balanced_accuracy`: mean 79.76%, sample SD 2.33 percentage points, 95% t interval [76.87%, 82.65%], range [76.20%, 82.40%].
- `combined_auroc`: mean 0.8258, sample SD 0.0273, 95% t interval [0.7919, 0.8597], range [0.7830, 0.8584].
- `combined_average_precision`: mean 0.8681, sample SD 0.0180, 95% t interval [0.8458, 0.8905], range [0.8394, 0.8879].

The interval is across complete training runs on one fixed authored fixture. It does not
replace independent labels, natural-prevalence evaluation, or uncertainty across operating
systems and workloads.
