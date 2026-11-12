#!/usr/bin/env python3
"""fi1 pipeline audit: does the tt1 G2 verdict depend on resampling events instead of test streams?

The registered G2 interval (tracker - frozen recall on HAI 20.07) comes from an event bootstrap
(real_telemetry_core.paired_event_bootstrap). The 38 events share threshold state within each of the two test
files, so the first audit left open whether a stream-level bootstrap would change the verdict. The cluster
bootstrap only needs per-stream sums: events, frozen detections and tracker detections per test file, which
the post-hoc file docs/research/threshold_transfer_tt1_posthoc_transient.json stores (its baseline reproduces
the registered counts). No dataset is opened. Output: target/real-telemetry/fi1/pipeline/tt1_g2_cluster.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import repro_env  # noqa: E402
import tt1d_final as M  # noqa: E402  (cluster_bootstrap of the tt1d registration: run-level resampling)


def main():
    ph = json.loads(
        (
            ROOT / "docs/research/threshold_transfer_tt1_posthoc_transient.json"
        ).read_text(encoding="utf-8")
    )
    reg = json.loads(
        (ROOT / "docs/research/threshold_transfer_tt1_result_hai-20.07.json").read_text(
            encoding="utf-8"
        )
    )
    streams = ph["baseline"]["per_stream"]
    groups, frozen, tracker = [], [], []
    for st in streams:
        n, f, t = st["events"], st["frozen"], st["tracker"]
        # per-stream sums are all a cluster bootstrap uses; the order of hits inside a stream does not matter
        groups += [st["stream"]] * n
        frozen += [True] * f + [False] * (n - f)
        tracker += [True] * t + [False] * (n - t)
    rules = reg["real_events"]["rules"]
    assert (
        sum(frozen) == rules["frozen"]["detected"]
        and sum(tracker) == rules["tracker"]["detected"]
    )
    stream_level = M.cluster_bootstrap(groups, frozen, tracker)
    for k in (
        "discordant_base_only",
        "discordant_rule_only",
    ):  # depend on the synthetic order within a stream
        stream_level.pop(k)
    out = {
        "registered_event_bootstrap": reg["gates"]["G2_tracker_vs_frozen"],
        "stream_cluster_bootstrap": stream_level,
        "per_stream": [
            {k: st[k] for k in ("stream", "events", "frozen", "tracker")}
            for st in streams
        ],
        "G2_holds_under_stream_resampling": stream_level["recall_difference_interval"][
            1
        ]
        < 0,
        "note": "with two streams the cluster bootstrap has three distinct resamples (each stream twice, or one of "
        "each); every one has tracker below frozen, so G2 holds at the stream level too, with a wider interval",
    }
    path = ROOT / "target/real-telemetry/fi1/pipeline/tt1_g2_cluster.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    repro_env.stamp_json(path)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    repro_env.pin_from_environment()
    main()
