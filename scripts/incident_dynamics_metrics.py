"""Episode-paired research metrics, shared by the runner and independent audit."""
import numpy as np
from scipy.special import expit


def episode_means(values, episodes):
    names, group = np.unique(episodes, return_inverse=True)
    means = np.bincount(group, weights=values) / np.bincount(group)
    return names, means


def bootstrap_difference(left, right, episodes, seed, quantiles=(.025, .975)):
    _, differences = episode_means(left - right, episodes)
    rng = np.random.default_rng(seed)
    draws = rng.integers(len(differences), size=(10000, len(differences)))
    samples = differences[draws].mean(1)
    return {"estimate": float(differences.mean()), "interval": np.quantile(samples, quantiles).tolist(),
            "interval_level": 1 - 2 * quantiles[0], "episodes": len(differences), "resamples": 10000}


def prediction_metrics(predicted, windows, spec):
    error = np.mean(np.abs(predicted - windows.targets) / spec.scale, axis=-1)
    relevant = [0, 1, 3] if spec.name == "ferrumos" else [0, 1, 2, 4, 5]
    active_error = np.mean(np.abs(predicted[:, :, relevant] - windows.targets[:, :, relevant]) / spec.scale[relevant], axis=-1)
    result = {}
    for h in (1, 3, 5):
        valid = windows.valid[:, h - 1] > 0
        ids, means = episode_means(error[valid, h - 1], windows.episodes[valid])
        _, active = episode_means(active_error[valid, h - 1], windows.episodes[valid])
        result[f"h{h}"] = {"episode_macro_mae": float(means.mean()), "warning_dimension_mae": float(active.mean()),
                            "episodes": len(ids), "windows": int(valid.sum())}
    return result, error


def warning_summary(scores, labels, threshold, calibration, episodes):
    warnings = scores >= threshold
    probability = expit(calibration[0] + calibration[1] * scores)
    ids, groups = np.unique(episodes, return_inverse=True)
    counts = np.stack([np.bincount(groups, weights=v, minlength=len(ids)) for v in
                       (warnings & labels, warnings & ~labels, ~warnings & ~labels, ~warnings & labels)], axis=1)
    tp, fp, tn, fn = counts.sum(0).astype(int)
    bins = []
    ece = 0.0
    for i in range(10):
        selected = (probability >= i / 10) & (probability < (i + 1) / 10 if i < 9 else probability <= 1)
        count = int(selected.sum())
        if count:
            mean_probability, frequency = float(probability[selected].mean()), float(labels[selected].mean())
            ece += count / len(labels) * abs(mean_probability - frequency)
            bins.append({"bin": i, "count": count, "mean_probability": mean_probability, "frequency": frequency})
    report = {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
              "recall": float(tp / (tp + fn)) if tp + fn else None,
              "fpr": float(fp / (fp + tn)) if fp + tn else None,
              "brier": float(np.mean((probability - labels) ** 2)), "ece_10_bins": ece,
              "prevalence": float(labels.mean()), "reliability_bins": bins, "episodes": len(ids)}
    return report, counts


def paired_warning_difference(left, right, seed):
    assert left.shape == right.shape
    rng = np.random.default_rng(seed)
    draws = rng.integers(len(left), size=(10000, len(left)))
    a, b = left[draws].sum(1), right[draws].sum(1)
    result = {}
    for name, numerator, denominator in (("recall", 0, (0, 3)), ("fpr", 1, (1, 2))):
        bootstrap = a[:, numerator] / a[:, denominator].sum(1) - b[:, numerator] / b[:, denominator].sum(1)
        aa, bb = left.sum(0), right.sum(0)
        point = aa[numerator] / aa[list(denominator)].sum() - bb[numerator] / bb[list(denominator)].sum()
        result[name] = {"difference": float(point), "interval_97_5_percent": np.quantile(bootstrap, [.0125, .9875]).tolist()}
    return result
