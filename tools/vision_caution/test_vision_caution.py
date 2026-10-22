import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")   # the advisory runs on CPU; keep tests off the GPU

import numpy as np

from vision_caution import (
    AUTHORITY,
    HEAD_SHAPES,
    SCHEMA,
    STATUSES,
    VisionCaution,
    VisionCautionAdvisory,
    VisionCautionError,
    load_artifact,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HAS_TORCH = importlib.util.find_spec("torch") is not None


def encoder_path():
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download("facebook/dinov2-small", "model.safetensors", local_files_only=True)
    except Exception:
        return None


def make_artifact(directory, seed=0, **meta_overrides):
    rng = np.random.default_rng(seed)
    weights = {f"head.{k}": rng.normal(0, 0.05, shape).astype(np.float32) for k, shape in HEAD_SHAPES.items()}
    enc = encoder_path()
    meta = {"schema": SCHEMA, "authority": AUTHORITY,
            "encoder": {"weights_sha256": hashlib.sha256(Path(enc).read_bytes()).hexdigest() if enc else "0" * 64},
            "thresholds_logit": {"fpr_0.05": 0.5, "fpr_0.10": 0.2}, "platt": {"coef": 1.0, "intercept": 0.0},
            "frame_stack": 2, "horizon_steps": 3, "action_space": {"actions": [[0, 0]] * 5}}
    meta.update(meta_overrides)
    path = Path(directory) / f"art_{seed}.npz"
    np.savez_compressed(path, metadata=json.dumps(meta), **weights)
    return path


def frames(seed=1):
    rng = np.random.default_rng(seed)
    base = np.full((48, 48), 0.1, np.float32)
    a, b = base.copy(), base.copy()
    a[10:16, 10:16] = 1.0
    b[11:17, 12:18] = 1.0
    a += rng.normal(0, 0.01, a.shape).astype(np.float32)
    b += rng.normal(0, 0.01, b.shape).astype(np.float32)
    return np.clip(a, 0, 1), np.clip(b, 0, 1)


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.art = make_artifact(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def assess(self, vc, **kw):
        args = {"frames": frames(), "proposed_action": 2, "frame_ids": (10, 11)}
        args.update(kw)
        return vc.assess(**args)

    def test_disabled_by_default(self):
        os.environ.pop("FERRUM_VISION_CAUTION", None)
        rec = self.assess(VisionCaution(self.art))
        self.assertEqual((rec.status, rec.degradation), ("no_confident_caution", "disabled_by_default"))

    def test_artifact_failures_abstain_and_never_raise(self):
        cases = {
            "artifact_missing": VisionCaution(Path(self.tmp.name) / "absent.npz", enabled=True),
            "artifact_digest_mismatch": VisionCaution(self.art, expected_sha256="f" * 64, enabled=True),
            "artifact_authority_boundary": VisionCaution(make_artifact(self.tmp.name, 2, authority="may block"), enabled=True),
            "artifact_schema": VisionCaution(make_artifact(self.tmp.name, 3, schema="OTHER"), enabled=True),
            "artifact_calibration": VisionCaution(make_artifact(self.tmp.name, 4, platt={"coef": -1.0, "intercept": 0.0}), enabled=True),
        }
        for reason, vc in cases.items():
            rec = self.assess(vc)
            self.assertEqual((rec.status, rec.degradation), ("no_confident_caution", reason))
            self.assertIsNone(rec.caution_probability)

    def test_nonfinite_weights_rejected(self):
        bad = Path(self.tmp.name) / "nan.npz"
        with np.load(self.art) as z:
            arrays = {k: z[k] for k in z.files}
        arrays["head.red.weight"] = arrays["head.red.weight"].copy()
        arrays["head.red.weight"][0, 0, 0, 0] = np.nan
        np.savez_compressed(bad, **arrays)
        with self.assertRaises(VisionCautionError) as ctx:
            load_artifact(bad)
        self.assertEqual(str(ctx.exception), "artifact_nonfinite")

    def test_bad_inputs_abstain_before_inference(self):
        vc = VisionCaution(self.art, enabled=True)
        flat = np.full((48, 48), 0.3, np.float32)
        nan = frames()[1].copy(); nan[0, 0] = np.nan
        cases = {
            "frames_out_of_order": {"frame_ids": (11, 10)},
            "frame_ids_invalid": {"frame_ids": (1,)},
            "frame_obscured": {"frames": (flat, frames()[1])},
            "frame_values": {"frames": (frames()[0], nan)},
            "frame_shape_or_dtype": {"frames": (np.zeros((32, 32), np.float32), frames()[1])},
            "action_out_of_space": {"proposed_action": 7},
        }
        for reason, kw in cases.items():
            self.assertEqual(self.assess(vc, **kw).degradation, reason)

    def test_status_vocabulary_has_no_all_clear(self):
        self.assertNotIn("safe", " ".join(STATUSES))
        with self.assertRaises(ValueError):
            VisionCautionAdvisory("safe", 0.0, 0.0, 0.0, "fpr_0.05", 3, (1, 2), None, None)
        with self.assertRaises(ValueError):
            VisionCautionAdvisory("caution_raised", 0.9, 1.0, 0.5, "fpr_0.05", 3, (1, 2), None, None, authority="permit")

    def test_record_is_advisory_not_a_command(self):
        rec = self.assess(VisionCaution(self.art))
        body = json.loads(rec.to_json())
        self.assertEqual(body["authority"], AUTHORITY)
        self.assertEqual(body["schema"], "ferrum_vision_caution_advisory_v1")
        for forbidden in ("ferrum_routed_command_v1", "permit_issued", "adapter_invoked", "command", "target"):
            self.assertNotIn(forbidden, body)

    def test_package_has_no_route_to_authority(self):
        forbidden = ["ferrum_routed_command_v1", "BridgeCommand", "authorize", "execute_tool", "neural_intent_commit",
                     "physical_maintenance_demo", "PhysicalPrediction", "physical_sim_bridge", "ferrum_physical_runtime",
                     "socket", "subprocess", "urllib"]
        for name in ("vision_caution.py", "dinov2_small.py"):
            text = (HERE / name).read_text(encoding="utf-8")
            code = re.sub(r'"""[\s\S]*?"""', "", text)   # docstrings may describe the boundary
            for token in forbidden:
                self.assertNotIn(token, code, f"{name} mentions {token}")


@unittest.skipUnless(HAS_TORCH and encoder_path(), "torch and the cached DINOv2 weights are required")
class InferenceTests(unittest.TestCase):
    def test_encoder_matches_research_implementation(self):
        import torch
        from safetensors.torch import load_file
        sys.path.insert(0, str(ROOT / "scripts"))
        import vision_wm_pretrained_encoders as PE
        from dinov2_small import DinoV2Small

        sd = load_file(encoder_path())
        ours, ref = DinoV2Small(), PE.DinoV2Small()
        ours.load_state_dict(sd, strict=True); ref.load_state_dict(sd, strict=True)
        x = torch.randn(2, 3, 224, 224, generator=torch.Generator().manual_seed(0))
        with torch.no_grad():
            self.assertTrue(torch.allclose(ours.eval()(x), ref.eval()(x), atol=1e-5))

    def test_live_assess_matches_research_pipeline_and_rejects_stale_frames(self):
        import torch
        import torch.nn.functional as F
        sys.path.insert(0, str(ROOT / "scripts"))
        import vision_wm_pretrained_encoders as PE

        with tempfile.TemporaryDirectory() as tmp:
            art = make_artifact(tmp, 7)
            vc = VisionCaution(art, enabled=True)
            f0, f1 = frames()
            rec = vc.assess((f0, f1), 3, (100, 101))
            self.assertIn(rec.status, ("caution_raised", "no_caution_raised"))
            self.assertTrue(0.0 < rec.caution_probability < 1.0)
            # research path: PE.extract on a (1, 2, 48, 48) episode, then the train_head forward
            enc = PE.load_dino(True)
            feats = PE.extract(enc, np.stack([f0, f1])[None]).cpu()
            z = load_artifact(art)["weights"]
            st = torch.cat([feats[0, 0:1], feats[0, 1:2]], 1).float()
            red = F.conv2d(st, torch.from_numpy(z["red.weight"]), torch.from_numpy(z["red.bias"]))
            act = F.gelu(F.linear(torch.eye(5)[3:4], torch.from_numpy(z["act.weight"]), torch.from_numpy(z["act.bias"])))
            h = F.gelu(F.linear(torch.cat([F.gelu(red).flatten(1), act], 1), torch.from_numpy(z["mlp.0.weight"]), torch.from_numpy(z["mlp.0.bias"])))
            ref = float(F.linear(h, torch.from_numpy(z["mlp.2.weight"]), torch.from_numpy(z["mlp.2.bias"]))[0, 0])
            self.assertAlmostEqual(rec.caution_logit, ref, places=3)
            stale = vc.assess((f0, f1), 3, (99, 101))
            self.assertEqual((stale.status, stale.degradation), ("no_confident_caution", "frames_stale"))

    def test_encoder_digest_mismatch_abstains(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = make_artifact(tmp, 8, encoder={"weights_sha256": "0" * 64})
            rec = VisionCaution(art, enabled=True).assess(frames(), 1, (1, 2))
            self.assertEqual((rec.status, rec.degradation), ("no_confident_caution", "encoder_digest_mismatch"))


if __name__ == "__main__":
    unittest.main()
