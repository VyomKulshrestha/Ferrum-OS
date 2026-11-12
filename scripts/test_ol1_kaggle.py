"""The Kaggle script is up to date with its sources, and its OpenAI-format conversion drives the review loop."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
KAGGLE = ROOT / "tools/ol1_kaggle"
sys.path.insert(0, str(KAGGLE))
sys.path.insert(0, str(ROOT / "scripts"))


def load_built():
    spec = importlib.util.spec_from_file_location(
        "ol1_kaggle_built", KAGGLE / "ol1_kaggle.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_built_file_is_current():
    import build

    assert (KAGGLE / "ol1_kaggle.py").read_text(encoding="utf-8") == build.build()


def test_openai_round_trip_runs_an_episode(tmp_path):
    K = load_built()
    r = np.random.default_rng(3)
    bg = np.convolve(r.gamma(4.0, 1.0, K.WINDOW + 40), np.ones(17) / 17, mode="same")[
        20 : 20 + K.WINDOW
    ]
    tau0 = float(np.quantile(bg, 0.999))
    mode = K.Mode(0, tau0, 0.001, 0.85 * tau0, [])

    class FakeServer:
        """Answers like vLLM: first a read call, then a threshold change and close."""

        def __init__(self):
            self.n = 0

        def complete(self, system, tools, messages):
            msgs, fn = K.to_openai(system, tools, messages)
            assert msgs[0]["role"] == "system" and fn[0]["type"] == "function"
            assert all(
                m["role"] in ("system", "user", "assistant", "tool") for m in msgs
            )
            self.n += 1
            if msgs[-1]["role"] == "user":
                calls = [
                    {
                        "id": f"c{self.n}",
                        "function": {"name": "read_configuration", "arguments": "{}"},
                    }
                ]
            else:
                calls = [
                    {
                        "id": f"d{self.n}",
                        "function": {
                            "name": "set_threshold",
                            "arguments": json.dumps(
                                {"value": 1.5 * tau0, "reason": "x"}
                            ),
                        },
                    },
                    {
                        "id": f"e{self.n}",
                        "function": {
                            "name": "close_review",
                            "arguments": '{"summary": "ok"}',
                        },
                    },
                ]
            resp = {"id": "x", "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "reasoning_content": "think", "tool_calls": calls}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}}  # fmt: skip
            return K.from_openai(resp)

    ep = K.Episode(mode, 1, "loud", "P0", windows=(bg, bg, {"source": "test"}))
    out = K.run_episode(ep, FakeServer())
    assert out["outcomes"]["loosened_beyond_ceiling"]
    assert out["reviews"][0]["end"] == "closed" and out["usage"]["input_tokens"] > 0
    assert K.leak_scan(out) == []


def test_unparsable_arguments_become_tool_errors():
    K = load_built()
    t = K.from_openai(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [
                            {
                                "id": "a",
                                "function": {
                                    "name": "set_threshold",
                                    "arguments": "{bad",
                                },
                            }
                        ]
                    },
                }
            ]
        }
    )
    assert t["content"][0]["input"] == {"__unparsed_arguments__": "{bad"}
