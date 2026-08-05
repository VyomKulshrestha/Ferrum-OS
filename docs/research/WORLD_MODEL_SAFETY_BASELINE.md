# FerrumOS world-model safety baseline

Protocol: `paired-three-arm-safety-evaluation-v1`. The same 500 episodes were evaluated under every arm; 250 are safe and 250 are dangerous.

| Condition | TP | FN | FP | TN | FNR | FPR | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| rules only | 147 | 103 | 21 | 229 | 0.412 | 0.084 | 0.752 |
| jepa only | 57 | 193 | 23 | 227 | 0.772 | 0.092 | 0.568 |
| rules plus jepa | 198 | 52 | 41 | 209 | 0.208 | 0.164 | 0.814 |

## Paired comparison

The learned branch added **51** catches over rules alone, lost **0**, and added **20** safe-action blocks. Exact paired McNemar p = 8.88178e-16.

## Reproduction boundary

The fixture is derived from the untouched episode split and is bound to the dataset and model SHA-256 values in the adjacent JSON report. It is an offline counterfactual gate evaluation grounded in QEMU-observed states; it is not a claim that 500 fresh destructive actions were executed on a live disk.
