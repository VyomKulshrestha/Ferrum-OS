#!/usr/bin/env python3
"""Verify the vision caution advisory (vision world model increment 4).

Static checks (numpy only, CI-friendly):
  * the artifact loads, has schema FERRUM_VISION_CAUTION_V1 and the physical_hai_v1
    authority string, finite weights and sane calibration;
  * its sha256 equals the sealed result's selected_artifact_sha256 and the integration
    protocol's pinned advisory sha; the sealed seed was opened exactly once;
  * the protected deployed artifacts are unchanged;
  * the guest runtime and gate code contain no vision-caution wiring, and the advisory
    package contains no route to a permit/command path;
  * the advisory is off by default.
--replay (torch + pybullet, slow): re-render selection seed 1, score it with the
  package's own encoder + head, and check that it reproduces the persisted 5% threshold.
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
from vision_caution import AUTHORITY, DEFAULT_ARTIFACT, SCHEMA, VisionCaution, load_artifact  # noqa: E402

RESULT = ROOT / "docs/research/vision_world_model_result_v4_dinov2.json"
PROTOCOL = ROOT / "docs/research/vision_caution_integration_protocol_v1.json"
LEDGER = ROOT / "target/vision-wm/final_access.jsonl"                     # live, gitignored
LEDGER_SNAPSHOT = ROOT / "docs/research/artifacts/vision-caution-v1/final_access_ledger.jsonl"   # committed copy for CI
WIRING_TOKENS = ("vision_caution", "VisionCaution", "FERRUM_VISION_CAUTION", "vision-caution")
GATE_SOURCES = ["userland/physical-runtime/src/safety.rs", "userland/physical-runtime/src/runtime.rs",
                "userland/physical-runtime/src/adapter.rs", "userland/physical-runtime/src/model.rs"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(cond, msg, failures):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def static(failures):
    art = load_artifact(DEFAULT_ARTIFACT)
    check(art["meta"]["schema"] == SCHEMA and art["meta"]["authority"] == AUTHORITY, "artifact schema + authority boundary", failures)
    check("NOT qualified for live use" in art["meta"].get("qualified_for", ""), "artifact declares it is not qualified for live use", failures)
    result = json.loads(RESULT.read_text(encoding="utf-8")) if RESULT.exists() else {}
    check(result.get("selected_artifact_sha256") == art["sha256"], "artifact sha256 == sealed result selected_artifact_sha256", failures)
    seed = result.get("final_seed")
    read = lambda p: [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    live, snap = read(LEDGER), read(LEDGER_SNAPSHOT)
    if live and snap:
        check(live[:len(snap)] == snap, "committed ledger snapshot is a prefix of the live ledger", failures)
    opens = live or snap
    check(bool(opens), f"ledger available ({'live' if live else 'committed snapshot'})", failures)
    seed_opens = [o for o in opens if o.get("final_seed") == seed and not str(o.get("reason", "")).startswith("RETIRED")]
    check(seed in (780, 781) and len(seed_opens) == 1, f"sealed seed {seed} opened exactly once", failures)
    if seed == 781:
        check(any(o.get("final_seed") == 780 and str(o.get("reason", "")).startswith("RETIRED") for o in opens),
              "seed 780 recorded as retired under the crash rule", failures)
    proto = json.loads(PROTOCOL.read_text(encoding="utf-8")) if PROTOCOL.exists() else {}
    pinned = proto.get("advisory_artifacts", {}).get("vision_caution_head", {}).get("sha256")
    check(pinned == art["sha256"], "integration protocol pins the advisory artifact sha256", failures)
    for rel, want in proto.get("protected_deployed_artifacts", {}).items():
        p = ROOT / rel
        check(p.exists() and sha256(p) == want, f"protected artifact unchanged: {rel}", failures)
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
    rec = VisionCaution().assess((np.zeros((48, 48), np.float32),) * 2, 0, (1, 2))
    check(rec.status == "no_confident_caution" and rec.degradation == "disabled_by_default", "advisory is off by default", failures)
    return art, result


def replay(art, failures):
    import os
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    import torch
    import torch.nn.functional as F
    sys.path.insert(0, str(ROOT / "scripts"))
    import vision_wm_final_v2 as FV
    import vision_wm_pretrained_encoders as PE
    import vision_wm_pybullet_data as D

    vc = VisionCaution(enabled=True)
    vc._load_models()
    f, a, h = D.collect(200, 20, 48, seed=1, scene="hard")
    e, t, act, y = PE.labels(a, h)
    mean = torch.tensor((0.485, 0.456, 0.406)).view(1, 3, 1, 1); std = torch.tensor((0.229, 0.224, 0.225)).view(1, 3, 1, 1)
    flat = torch.from_numpy(f.reshape(-1, 1, 48, 48))
    with torch.no_grad():
        feats = torch.cat([F.adaptive_avg_pool2d(vc._encoder((F.interpolate(flat[i:i + 64].repeat(1, 3, 1, 1), size=(224, 224), mode="bilinear",
                                                                            align_corners=False) - mean) / std), 4).half().float()
                           for i in range(0, len(flat), 64)]).view(f.shape[0], f.shape[1], 384, 4, 4)
        st = torch.cat([feats[e, t - 1], feats[e, t]], 1)
        oh = torch.zeros(len(e), 5); oh[np.arange(len(e)), act] = 1
        z = F.gelu(vc._head["red"](st)).flatten(1)
        logits = vc._head["mlp"](torch.cat([z, F.gelu(vc._head["act"](oh))], 1))[:, 0].numpy()
    thr = FV.calibrate(logits, y, 0.05)
    want = art["thresholds"]["fpr_0.05"]
    check(abs(thr - want) <= 1e-2 * max(1.0, abs(want)), f"package reproduces the registered 5% threshold on selection seed 1 ({thr:.4f} vs {want:.4f})", failures)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true")
    a = ap.parse_args()
    failures = []
    art, _ = static(failures)
    if a.replay:
        replay(art, failures)
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(failures)} failure(s)")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
