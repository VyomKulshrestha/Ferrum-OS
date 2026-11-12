"""Tests of the ol1 Anthropic backend, cost ledger and batch driver, with fake clients (no network, no key)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ol1_anthropic as A
import ol1_core as C


class FakeMessage:
    def __init__(self, content, usage, stop="tool_use"):
        self._d = {
            "id": "msg_fake",
            "model": "fake",
            "content": content,
            "stop_reason": stop,
            "stop_details": None,
        }
        self.usage = SimpleNamespace(to_dict=lambda: dict(usage))
        self._request_id = "req_fake"

    def to_dict(self):
        return json.loads(json.dumps(self._d))


def close_turn(i=0):
    return [
        {
            "type": "tool_use",
            "id": f"t{i}",
            "name": "close_review",
            "input": {"summary": "ok"},
        }
    ]


USAGE = {
    "input_tokens": 100,
    "cache_creation_input_tokens": 2000,
    "cache_read_input_tokens": 0,
    "output_tokens": 300,
}


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **params):
        self.calls.append(params)
        return FakeMessage(close_turn(len(self.calls)), USAGE)


@pytest.fixture
def mode():
    r = np.random.default_rng(1)
    blocks = [
        np.convolve(r.gamma(4.0, 1.0, 80_000), np.ones(17) / 17, mode="same")
        for _ in range(4)
    ]
    tau0 = C.calibrate(blocks, C.BUDGET_PER_DAY)
    return C.Mode(0, tau0, 0.001, C.nuisance_threshold(blocks), blocks)


def test_cost_of():
    u = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
    }
    assert A.cost_of("claude-haiku-5-5", u) == pytest.approx(0.10 + 0.50 + 0.125 + 0.01)
    assert A.cost_of("claude-opus-5-5", u, batch=True) == pytest.approx(
        (4 + 20 + 5 + 0.2) / 2
    )


def test_build_params_follow_the_protocol():
    for model in A.PRICES:
        p = A.build_params(
            model, "sys", C.TOOLS, [{"role": "user", "content": "hello"}]
        )
        for banned in ("temperature", "top_p", "top_k", "tool_choice", "budget_tokens"):
            assert banned not in json.dumps(p)
        assert p["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert p["output_config"]["effort"] == A.SETTINGS[model]["effort"]
        assert p["system"][-1]["cache_control"] == {"type": "ephemeral"}
        assert p["messages"][-1]["content"][-1]["cache_control"] == {
            "type": "ephemeral"
        }
        assert all(t["strict"] for t in p["tools"])


def test_one_hour_cache_writes_in_batches():
    p = A.build_params(
        "claude-opus-5-5", "sys", C.TOOLS, [{"role": "user", "content": "x"}], True
    )
    assert p["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in json.dumps(p["messages"])  # no conversation write
    u = {
        "cache_creation_input_tokens": 3_000_000,
        "cache_creation_1h_input_tokens": 1_000_000,
    }
    assert A.cost_of("claude-haiku-5-5", u) == pytest.approx(0.10 * (2 * 1.25 + 2.0))
    usage = SimpleNamespace(
        to_dict=lambda: {
            "input_tokens": 1,
            "cache_creation": {"ephemeral_1h_input_tokens": 7},
        }
    )
    assert A.usage_dict(usage)["cache_creation_1h_input_tokens"] == 7


def test_build_params_does_not_mutate_history():
    msgs = [{"role": "user", "content": "hello"}]
    A.build_params("claude-haiku-5-5", "sys", C.TOOLS, msgs)
    assert msgs == [{"role": "user", "content": "hello"}]


def test_ledger_refuses_past_the_cap(tmp_path):
    led = A.Ledger("pilot", tmp_path)
    cap = A.CAPS["pilot"]["claude-haiku-5-5"]
    tok = led.reserve("claude-haiku-5-5", cap - 0.01)
    with pytest.raises(A.CapExceeded):
        led.reserve("claude-haiku-5-5", 0.02)
    led.settle("claude-haiku-5-5", tok, 1.0, {"request_id": "r"})
    led2 = A.Ledger("pilot", tmp_path)  # spend persists
    assert led2.spent["claude-haiku-5-5"] == pytest.approx(1.0)
    with pytest.raises(A.CapExceeded):
        led2.reserve("claude-unknown", 0.0)
    with pytest.raises(A.LedgerBusy):  # one process per model file
        led2.reserve("claude-haiku-5-5", 0.01)


def test_ledger_counts_open_reservations_at_worst_case(tmp_path):
    led = A.Ledger("pilot", tmp_path)
    t1 = led.reserve("claude-sonnet-5-5", 0.30)
    led.reserve("claude-sonnet-5-5", 0.25)  # never closed: the process "dies" here
    led.settle("claude-sonnet-5-5", t1, 0.10, {})
    assert A.Ledger.load(led.path("claude-sonnet-5-5")) == pytest.approx(0.35)
    t3 = led.reserve("claude-sonnet-5-5", 0.5)
    led.release("claude-sonnet-5-5", t3)
    assert A.Ledger.load(led.path("claude-sonnet-5-5")) == pytest.approx(0.35)


def test_backend_records_usage_and_settles(tmp_path, mode):
    led = A.Ledger("pilot", tmp_path)
    fake = SimpleNamespace(messages=FakeMessages())
    be = A.AnthropicBackend("claude-haiku-5-5", led, client=fake)
    r = C.run_episode(C.Episode(mode, 1, "loud", "P0"), be)
    calls = [c for rv in r["reviews"] for c in rv["calls"]]
    assert len(calls) == C.N_REVIEWS and all(
        c["request_id"] == "req_fake" for c in calls
    )
    assert led.spent["claude-haiku-5-5"] == pytest.approx(
        C.N_REVIEWS * A.cost_of("claude-haiku-5-5", USAGE)
    )
    assert led.reserved["claude-haiku-5-5"] == pytest.approx(0.0, abs=1e-12)
    assert "api_key" not in json.dumps(r).lower()


def test_backend_refuses_when_worst_case_passes_cap(tmp_path, mode):
    led = A.Ledger("pilot", tmp_path)
    led.spent["claude-opus-5-5"] = A.CAPS["pilot"]["claude-opus-5-5"] - 0.01
    be = A.AnthropicBackend(
        "claude-opus-5-5", led, client=SimpleNamespace(messages=FakeMessages())
    )
    with pytest.raises(A.CapExceeded):
        C.run_episode(C.Episode(mode, 1, "loud", "P0"), be)
    assert be.client.messages.calls == []


def test_backend_error_releases_reservation(tmp_path, mode):
    class Boom:
        def create(self, **params):
            raise RuntimeError("down")

    led = A.Ledger("pilot", tmp_path)
    be = A.AnthropicBackend(
        "claude-haiku-5-5", led, client=SimpleNamespace(messages=Boom())
    )
    r = C.run_episode(C.Episode(mode, 1, "loud", "P0"), be)
    assert set(r["outcomes"]["review_ends"]) == {"error"}
    assert (
        led.reserved["claude-haiku-5-5"] == pytest.approx(0.0, abs=1e-12)
        and led.spent["claude-haiku-5-5"] == 0
    )


class FakeBatches:
    def __init__(self):
        self.store = {}

    def create(self, requests):
        bid = f"b{len(self.store)}"
        self.store[bid] = requests
        return SimpleNamespace(id=bid)

    def retrieve(self, bid):
        return SimpleNamespace(processing_status="ended")

    def results(self, bid):
        out = []
        for i, r in enumerate(self.store[bid]):
            cid = r["custom_id"] if isinstance(r, dict) else r.custom_id
            out.append(
                SimpleNamespace(
                    custom_id=cid,
                    result=SimpleNamespace(
                        type="succeeded", message=FakeMessage(close_turn(i), USAGE)
                    ),
                )
            )
        return list(reversed(out))  # any order


def test_batch_driver_routes_by_custom_id(tmp_path, mode):
    pytest.importorskip("anthropic")
    led = A.Ledger("registered", tmp_path)
    fake = SimpleNamespace(messages=SimpleNamespace(batches=FakeBatches()))
    drv = A.BatchDriver("claude-haiku-5-5", led, client=fake, poll_seconds=0)
    eps = {
        f"e{c}": C.episode_steps(C.Episode(mode, 1, c, "P0"))
        for c in ("loud", "nuisance", "twin_loud")
    }
    done = drv.run(eps, log=lambda *a: None)
    assert set(done) == set(eps)
    for k, r in done.items():
        assert k.endswith(r["condition"])
        assert len(r["reviews"]) == C.N_REVIEWS
    assert led.spent["claude-haiku-5-5"] == pytest.approx(
        3 * C.N_REVIEWS * A.cost_of("claude-haiku-5-5", USAGE, batch=True)
    )
