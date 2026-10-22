#!/usr/bin/env python3
"""Verify the vision caution advisory (vision world model increment 4 + runtime-scene proxy).

Static checks (numpy only, CI-friendly), for each sealed-evaluated artifact
(V1: hard sim scene, five-impulse actions; V2: runtime-scene proxy, runtime PhysicalAction):
  * the artifact loads, has its schema and the physical_hai_v1 authority string, finite
    weights and sane calibration, and declares it is not for live use;
  * its sha256 equals its sealed result's selected_artifact_sha256 and its integration
    protocol's pinned advisory sha; its sealed seed was opened exactly once;
  * the protected deployed artifacts are unchanged;
  * the guest runtime and gate code contain no vision-caution wiring, and the advisory
    package contains no route to a permit/command path;
  * the advisory is off by default.
--replay (torch + pybullet, slow): re-render each artifact's selection seed, score it with
  the package's own encoder + head, and check that it reproduces the persisted 5% threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vision_caution"))
from vision_caution import AUTHORITY, SCHEMA, SCHEMA_V2, VisionCaution, load_artifact  # noqa: E402

LEDGER = ROOT / "target/vision-wm/final_access.jsonl"                     # live, gitignored
ART_DIR = ROOT / "docs/research/artifacts"
ARTIFACTS = {
    "v1": {"artifact": ART_DIR / "vision-caution-v1/selected_caution_head.npz", "schema": SCHEMA,
           "result": ROOT / "docs/research/vision_world_model_result_v4_dinov2.json",
           "protocol": ROOT / "docs/research/vision_caution_integration_protocol_v1.json",
           "snapshot": ART_DIR / "vision-caution-v1/final_access_ledger.jsonl",   # committed copy for CI
           "seeds": (780, 781), "not_live": ("qualified_for", "NOT qualified for live use")},
    "v2": {"artifact": ART_DIR / "vision-caution-v2/selected_caution_head.npz", "schema": SCHEMA_V2,
           "result": ROOT / "docs/research/vision_caution_runtime_proxy_result_v1.json",
           "protocol": ROOT / "docs/research/vision_caution_integration_protocol_v2.json",
           "snapshot": ART_DIR / "vision-caution-v2/final_access_ledger.jsonl",
           "seeds": (790, 791), "not_live": ("qualification", "never live use")},
}
WIRING_TOKENS = ("vision_caution", "VisionCaution", "FERRUM_VISION_CAUTION", "vision-caution")
GATE_SOURCES = ["userland/physical-runtime/src/safety.rs", "userland/physical-runtime/src/runtime.rs",
                "userland/physical-runtime/src/adapter.rs", "userland/physical-runtime/src/model.rs"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(cond, msg, failures):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def read_jsonl(p):
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.exists() else []


def static_artifact(name, spec, failures):
    art = load_artifact(spec["artifact"])
    check(art["meta"]["schema"] == spec["schema"] and art["meta"]["authority"] == AUTHORITY,
          f"{name}: artifact schema + authority boundary", failures)
    key, phrase = spec["not_live"]
    check(phrase in art["meta"].get(key, ""), f"{name}: artifact declares it is not for live use", failures)
    result = json.loads(spec["result"].read_text(encoding="utf-8")) if spec["result"].exists() else {}
    check(result.get("selected_artifact_sha256") == art["sha256"], f"{name}: artifact sha256 == sealed result selected_artifact_sha256", failures)
    seed = result.get("final_seed")
    live, snap = read_jsonl(LEDGER), read_jsonl(spec["snapshot"])
    if live and snap:
        check(live[:len(snap)] == snap, f"{name}: committed ledger snapshot is a prefix of the live ledger", failures)
    opens = live or snap
    check(bool(opens), f"{name}: ledger available ({'live' if live else 'committed snapshot'})", failures)
    seed_opens = [o for o in opens if o.get("final_seed") == seed and not str(o.get("reason", "")).startswith("RETIRED")]
    check(seed in spec["seeds"] and len(seed_opens) == 1, f"{name}: sealed seed {seed} opened exactly once", failures)
    if seed == spec["seeds"][1]:
        check(any(o.get("final_seed") == spec["seeds"][0] and str(o.get("reason", "")).startswith("RETIRED") for o in opens),
              f"{name}: seed {spec['seeds'][0]} recorded as retired under the crash rule", failures)
    proto = json.loads(spec["protocol"].read_text(encoding="utf-8")) if spec["protocol"].exists() else {}
    pinned = proto.get("advisory_artifacts", {}).get("vision_caution_head", {}).get("sha256")
    check(pinned == art["sha256"], f"{name}: integration protocol pins the advisory artifact sha256", failures)
    for rel, want in proto.get("protected_deployed_artifacts", {}).items():
        p = ROOT / rel
        check(p.exists() and sha256(p) == want, f"{name}: protected artifact unchanged: {rel}", failures)
    return art


def static(failures):
    arts = {name: static_artifact(name, spec, failures) for name, spec in ARTIFACTS.items()}
    sources = [ROOT / s for s in GATE_SOURCES] + sorted((ROOT / "userland/heliox-daemon/src").rglob("*.rs"))
    hits = [str(p.relative_to(ROOT)) for p in sources if p.exists() and any(t in p.read_text(encoding="utf-8", errors="ignore") for t in WIRING_TOKENS)]
    check(not hits, f"no vision-caution wiring in guest/gate code ({len(sources)} files scanned){': ' + ', '.join(hits) if hits else ''}", failures)
    forbidden = ("ferrum_routed_command_v1", "BridgeCommand", "authorize", "execute_tool", "neural_intent_commit",
                 "physical_maintenance_demo", "PhysicalPrediction", "physical_sim_bridge", "ferrum_physical_runtime")
    for name in ("vision_caution.py", "dinov2_small.py"):
        code = re.sub(r'"""[\s\S]*?"""', "", (ROOT / "tools/vision_caution" / name).read_text(encoding="utf-8"))
        bad = [t for t in forbidden if t in code]
        check(not bad, f"tools/vision_caution/{name} has no route to authority{': ' + ', '.join(bad) if bad else ''}", failures)
    import os
    os.environ.pop("FERRUM_VISION_CAUTION", None)
    for name, spec in ARTIFACTS.items():
        size = arts[name]["frame_size"]
        action = 0 if arts[name]["interface"] == "sim5" else ("stop", (0.0, 0.0, 0.0))
        rec = VisionCaution(spec["artifact"]).assess((np.zeros((size, size), np.float32),) * 2, action, (1, 2))
        check(rec.status == "no_confident_caution" and rec.degradation == "disabled_by_default", f"{name}: advisory is off by default", failures)
    return arts


def _package_logits(vc, frames, e, t, action_vecs):
    import torch
    import torch.nn.functional as F
    pool, n, T, s = vc._art["pool"], frames.shape[0], frames.shape[1], frames.shape[2]
    mean = torch.tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1); std = torch.tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
    flat = torch.from_numpy(frames.reshape(-1, 1, s, s))
    with torch.no_grad():
        feats = torch.cat([F.adaptive_avg_pool2d(vc._encoder((F.interpolate(flat[i:i + 64].repeat(1, 3, 1, 1), size=(224, 224), mode="bilinear",
                                                                            align_corners=False) - mean) / std), pool).half().float()
                           for i in range(0, len(flat), 64)]).view(n, T, 384, pool, pool)
        st = torch.cat([feats[e, t - 1], feats[e, t]], 1)
        z = F.gelu(vc._head["red"](st)).flatten(1)
        a = torch.from_numpy(np.asarray(action_vecs, np.float32))
        return vc._head["mlp"](torch.cat([z, F.gelu(vc._head["act"](a))], 1))[:, 0].numpy()


def replay(arts, failures):
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    sys.path.insert(0, str(ROOT / "scripts"))
    import vision_wm_final_v2 as FV

    for name, spec in ARTIFACTS.items():
        vc = VisionCaution(spec["artifact"], enabled=True)
        vc._load_models()
        if name == "v1":
            import vision_wm_pretrained_encoders as PE
            import vision_wm_pybullet_data as D
            f, a, h = D.collect(200, 20, 48, seed=1, scene="hard")
            e, t, act, y = PE.labels(a, h)
            logits = _package_logits(vc, f, e, t, np.eye(5, dtype=np.float32)[act])
            seed = 1
        else:
            import vision_runtime_domain_render as R
            import vision_runtime_proxy_final as RP
            seed = arts[name]["meta"]["selection_seed"]
            d = R.collect(RP.SPLITS["sel"][1], seed=seed)
            idx = RP.decisions(d)
            logits = _package_logits(vc, d["frames"], idx["e"], idx["t"], idx["a10"])
            y = idx["y"]
        thr = FV.calibrate(logits, y, 0.05)
        want = arts[name]["thresholds"]["fpr_0.05"]
        check(abs(thr - want) <= 1e-2 * max(1.0, abs(want)),
              f"{name}: package reproduces the registered 5% threshold on selection seed {seed} ({thr:.4f} vs {want:.4f})", failures)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args()
    failures = []
    arts = static(failures)
    if a.replay:
        replay(arts, failures)
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(failures)} failure(s)")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
