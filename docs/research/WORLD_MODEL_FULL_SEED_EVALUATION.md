# FerrumOS full-pipeline seed evaluation

Every row independently trains the JEPA representation and transition MLP. The authored
500-episode safety fixture is fixed and is never used for checkpoint selection.

| Seed | Transition error | H=3 error | FNR | FPR | Balanced accuracy | AUROC | AUPRC |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 17 | 0.0154 | 0.1547 | 0.284 | 0.104 | 0.806 | 0.828 | 0.874 |
| 42 | 0.0185 | 0.0411 | 0.376 | 0.100 | 0.762 | 0.783 | 0.839 |
| 91 | 0.0167 | 0.1316 | 0.252 | 0.136 | 0.806 | 0.835 | 0.874 |
| 123 | 0.0163 | 0.0606 | 0.188 | 0.164 | 0.824 | 0.858 | 0.888 |
| 2026 | 0.0157 | 0.2704 | 0.252 | 0.168 | 0.790 | 0.825 | 0.865 |

## Aggregate

- `transition_normalized_mse`: mean 0.0165, sample SD 0.0012, 95% t interval [0.0150, 0.0181], range [0.0154, 0.0185].
- `transition_rollout_h3_normalized_mse`: mean 0.1317, sample SD 0.0909, 95% t interval [0.0189, 0.2445], range [0.0411, 0.2704].
- `combined_false_negative_rate`: mean 0.2704, sample SD 0.0686, 95% t interval [0.1853, 0.3555], range [0.1880, 0.3760].
- `combined_false_positive_rate`: mean 0.1344, sample SD 0.0321, 95% t interval [0.0946, 0.1742], range [0.1000, 0.1680].
- `combined_balanced_accuracy`: mean 0.7976, sample SD 0.0233, 95% t interval [0.7687, 0.8265], range [0.7620, 0.8240].
- `combined_auroc`: mean 0.8258, sample SD 0.0273, 95% t interval [0.7919, 0.8597], range [0.7830, 0.8584].
- `combined_average_precision`: mean 0.8681, sample SD 0.0180, 95% t interval [0.8458, 0.8905], range [0.8394, 0.8879].

The interval is across complete training runs on one fixed authored fixture. It does not
replace independent labels, natural-prevalence evaluation, or uncertainty across operating
systems and workloads.
