#!/usr/bin/env python3
"""ol1: the Anthropic backend, the cost ledger with hard caps, and the Message Batches driver.

The API key is read at run time from ANTHROPIC_API_KEY or from the owner's key file. It is passed to the SDK
client and nowhere else: it is never printed, logged, written to a result or passed on a command line.

Every request goes through Ledger.reserve() first: the request's worst-case cost (every input token billed
as a cache write, the whole max_tokens billed as output) is added to what has been spent and reserved, and the
request is refused when the sum would pass the model's cap for the ledger's scope. After the response the
reservation is replaced by the cost computed from response.usage.
"""

from __future__ import annotations

import atexit
import copy
import json
import math
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = Path(r"C:\Users\marcu\.ferrumos-secrets\anthropic_api_key.txt")
LEDGER_DIR = ROOT / "target/ol1/ledger"

# US dollars per million tokens: input, output (the owner's table); cache write 1.25 x input (5-minute TTL);
# cache read as listed by the claude-api skill (Opus 5.5 0.20, Sonnet 5.5 0.10; Haiku 5.5 assumed 0.1 x input).
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
}
CACHE_WRITE_FACTOR = 1.25
CACHE_WRITE_1H_FACTOR = 2.0
BATCH_FACTOR = 0.5

# Hard caps in US dollars per scope and model, retries included (protocol section 11).
CAPS = {
    "pilot": {
        "claude-haiku-5-5": 3.00,
        "claude-sonnet-5-5": 2.00,
        "claude-opus-5-5": 2.00,
    },
    "registered": {
        "claude-haiku-5-5": 20.00,
        "claude-sonnet-5-5": 45.00,
        "claude-opus-5-5": 45.00,
    },
    "reruns": {
        "claude-haiku-5-5": 1.00,
        "claude-sonnet-5-5": 1.00,
        "claude-opus-5-5": 1.00,
    },
}

# Request settings, fixed per model by the protocol (section 6). Thinking stays on (adaptive) on all three;
# the summarised thinking is stored with the transcript. No sampling parameters, no forced tool_choice.
SETTINGS = {
    "claude-haiku-5-5": {"effort": "medium", "max_tokens": 8000},
    "claude-sonnet-5-5": {"effort": "medium", "max_tokens": 8000},
    "claude-opus-5-5": {"effort": "medium", "max_tokens": 8000},
}
THINKING = {"type": "adaptive", "display": "summarized"}
CHARS_PER_TOKEN_FLOOR = (
    2.0  # worst-case token estimate from serialized length (real text is about 3.5)
)


class CapExceeded(RuntimeError):
    pass


def load_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("no API key found (environment or key file)")
    return key


def cost_of(model: str, usage: dict, batch: bool = False) -> float:
    p = PRICES[model]
    w1h = usage.get("cache_creation_1h_input_tokens", 0)
    w5m = usage.get("cache_creation_input_tokens", 0) - w1h
    c = (
        usage.get("input_tokens", 0) * p["input"]
        + w5m * p["input"] * CACHE_WRITE_FACTOR
        + w1h * p["input"] * CACHE_WRITE_1H_FACTOR
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["output"]
    ) / 1e6
    return c * (BATCH_FACTOR if batch else 1.0)


def worst_case(model: str, params: dict, batch: bool = False) -> float:
    n_in = math.ceil(len(json.dumps(params, default=str)) / CHARS_PER_TOKEN_FLOOR)
    p = PRICES[model]
    c = (
        n_in * p["input"] * CACHE_WRITE_1H_FACTOR + params["max_tokens"] * p["output"]
    ) / 1e6
    return c * (BATCH_FACTOR if batch else 1.0)


class LedgerBusy(RuntimeError):
    pass


class Ledger:
    """Running spend per model for one scope, persisted as JSON lines, one file per model (no request
    content, no key). Every reservation is written before its request is sent and closed by a settle or
    release line; a reservation left open (a process killed with a request in flight) counts at its worst
    case when the ledger is loaded again. One process at a time may write a model's file (lock file)."""

    def __init__(self, scope: str, directory: Path = LEDGER_DIR):
        if scope not in CAPS:
            raise ValueError(scope)
        self.scope, self.caps = scope, CAPS[scope]
        self.dir = Path(directory)
        self.lock = threading.Lock()
        self.spent = {m: 0.0 for m in self.caps}
        self.reserved = {m: 0.0 for m in self.caps}
        self.open_amount = {}
        self.held = set()
        self.n = 0
        for m in self.caps:
            self.spent[m] = self.load(self.path(m))

    def path(self, model):
        return self.dir / f"ledger_{self.scope}_{model}.jsonl"

    @staticmethod
    def load(path) -> float:
        """Settled cost plus the worst case of every reservation never closed."""
        if not Path(path).exists():
            return 0.0
        spent, pending = 0.0, {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            kind = r.get("kind", "settle")
            if kind == "reserve":
                pending[r["token"]] = r["amount"]
            elif kind == "release":
                pending.pop(r["token"], None)
            else:
                pending.pop(r.get("token"), None)
                spent += r["cost"]
        return spent + sum(pending.values())

    def _hold(self, model):
        if model in self.held:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = self.path(model).with_suffix(".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as e:
            raise LedgerBusy(
                f"{lock} exists: another process is spending on {model}, or one was killed; "
                "check, then delete the lock file"
            ) from e
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self.held.add(model)
        atexit.register(lambda: lock.unlink(missing_ok=True))

    def _write(self, model, rec):
        with self.path(model).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"model": model, **rec}, sort_keys=True) + "\n")

    def reserve(self, model: str, amount: float) -> str:
        if model not in self.caps:
            raise CapExceeded(f"model {model} has no cap in scope {self.scope}")
        with self.lock:
            total = self.spent[model] + self.reserved[model] + amount
            if total > self.caps[model]:
                raise CapExceeded(
                    f"{model}: spent {self.spent[model]:.4f} + reserved {self.reserved[model]:.4f} + worst case "
                    f"{amount:.4f} would pass the {self.scope} cap {self.caps[model]:.2f}"
                )
            self._hold(model)
            self.n += 1
            token = f"{os.getpid()}-{int(time.time() * 1000)}-{self.n}"
            self.reserved[model] += amount
            self.open_amount[token] = amount
            self._write(model, {"kind": "reserve", "token": token, "amount": amount})
            return token

    def settle(self, model: str, token: str, cost: float, record: dict) -> None:
        with self.lock:
            self.reserved[model] -= self.open_amount.pop(token)
            self.spent[model] += cost
            self._write(
                model, {"kind": "settle", "token": token, "cost": cost, **record}
            )

    def release(self, model: str, token: str) -> None:
        with self.lock:
            self.reserved[model] -= self.open_amount.pop(token)
            self._write(model, {"kind": "release", "token": token})

    def settle_foreign(
        self, model: str, token: str, amount: float, cost: float, record: dict
    ) -> None:
        """Close a reservation written by an earlier process (a batch submitted before a restart). The
        load counted it at its worst case `amount`; the settle line replaces that by the cost."""
        with self.lock:
            self._hold(model)
            self.spent[model] += cost - amount
            self._write(
                model, {"kind": "settle", "token": token, "cost": cost, **record}
            )


def usage_dict(usage) -> dict:
    d = usage.to_dict() if hasattr(usage, "to_dict") else dict(usage)
    out = {
        k: v for k, v in d.items() if isinstance(v, (int, float)) or k == "service_tier"
    }
    cc = d.get("cache_creation") or {}
    if isinstance(cc, dict) and cc.get("ephemeral_1h_input_tokens"):
        out["cache_creation_1h_input_tokens"] = cc["ephemeral_1h_input_tokens"]
    return out


def build_params(
    model: str, system: str, tools: list, messages: list, batch: bool = False
) -> dict:
    """The request body. Cache breakpoints: the system block (tools render before it, so tools and system
    are cached together) and, in synchronous runs, the last block of the last message (the growing review
    conversation). In a batch the system breakpoint has the 1-hour TTL and there is no conversation
    breakpoint: rounds are about six minutes apart, past the 5-minute TTL, so the dry run paid for cache
    writes of the conversation that were never read."""
    s = SETTINGS[model]
    msgs = copy.deepcopy(messages)
    last = msgs[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    if not batch:
        last["content"][-1]["cache_control"] = {"type": "ephemeral"}
    return {
        "model": model,
        "max_tokens": s["max_tokens"],
        "thinking": THINKING,
        "output_config": {"effort": s["effort"]},
        "system": [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral", "ttl": "1h"}
                if batch
                else {"type": "ephemeral"},
            }
        ],
        "tools": tools,
        "messages": msgs,
    }


def turn_from_message(msg, model: str, batch: bool = False) -> dict:
    d = msg.to_dict()
    u = usage_dict(msg.usage)
    return {
        "content": d["content"],
        "stop_reason": d.get("stop_reason"),
        "stop_details": d.get("stop_details"),
        "usage": u,
        "cost": cost_of(model, u, batch),
        "message_id": d.get("id"),
        "model": d.get("model"),
    }


class AnthropicBackend:
    """Synchronous backend for the review loop (pilot). Only models with a cap in the ledger's scope can be
    called."""

    def __init__(self, model: str, ledger: Ledger, client=None):
        if model not in PRICES:
            raise ValueError(f"model {model} is not in the protocol")
        self.model, self.ledger = model, ledger
        if client is None:
            import anthropic

            client = anthropic.Anthropic(
                api_key=load_key(), max_retries=3, timeout=300.0
            )
        self.client = client

    def complete(self, system, tools, messages):
        params = build_params(self.model, system, tools, messages)
        worst = worst_case(self.model, params)
        token = self.ledger.reserve(self.model, worst)
        t0 = time.time()
        try:
            msg = self.client.messages.create(**params)
        except Exception as e:  # noqa: BLE001  recorded as an error turn; the review ends (no tool is run)
            self.ledger.release(self.model, token)
            return {
                "content": [],
                "stop_reason": "error",
                "error": f"{type(e).__name__}: {getattr(e, 'message', str(e))[:300]}",
                "usage": {},
                "cost": 0.0,
                "request_id": None,
            }
        turn = turn_from_message(msg, self.model)
        turn["request_id"] = getattr(msg, "_request_id", None)
        turn["seconds"] = round(time.time() - t0, 2)
        turn["request"] = {
            k: params[k] for k in ("model", "max_tokens", "thinking", "output_config")
        }
        self.ledger.settle(
            self.model,
            token,
            turn["cost"],
            {
                "request_id": turn["request_id"],
                "usage": turn["usage"],
                "batch": False,
                "t": round(t0),
            },
        )
        return turn


# ---------------------------------------------------------------- Message Batches (registered run)
class BatchDriver:
    """Plays many episodes in lockstep through the Message Batches API: each round collects the pending
    request of every live episode, checks the round's worst case against the cap, submits one batch, and
    routes results back by custom_id (results arrive in any order)."""

    def __init__(
        self, model: str, ledger: Ledger, client=None, poll_seconds: float = 30.0
    ):
        self.model, self.ledger, self.poll = model, ledger, poll_seconds
        if client is None:
            import anthropic

            client = anthropic.Anthropic(
                api_key=load_key(), max_retries=3, timeout=300.0
            )
        self.client = client

    def run(self, episodes: dict, log=print) -> dict:
        """episodes: custom-id prefix -> episode generator (ol1_core.episode_steps). Returns prefix -> summary."""
        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request

        pending, done, rnd = {}, {}, 0
        for k, g in episodes.items():
            try:
                pending[k] = (g, next(g))
            except StopIteration as stop:
                done[k] = stop.value
        while pending:
            rnd += 1
            reqs, worst, ids = [], 0.0, {}
            for k, (g, (system, tools, messages)) in pending.items():
                cid = f"{k}-r{rnd}"
                params = build_params(self.model, system, tools, messages, batch=True)
                worst += worst_case(self.model, params, batch=True)
                reqs.append(
                    Request(
                        custom_id=cid, params=MessageCreateParamsNonStreaming(**params)
                    )
                )
                ids[cid] = k
            token = self.ledger.reserve(self.model, worst)
            try:
                batch = self.client.messages.batches.create(requests=reqs)
            except Exception:
                self.ledger.release(self.model, token)
                raise
            log(
                f"round {rnd}: batch {batch.id} with {len(reqs)} requests, worst case {worst:.4f}"
            )
            while True:
                b = self.client.messages.batches.retrieve(batch.id)
                if b.processing_status == "ended":
                    break
                time.sleep(self.poll)
            got, spent = {}, 0.0
            for res in self.client.messages.batches.results(batch.id):
                k = ids[res.custom_id]
                if res.result.type == "succeeded":
                    turn = turn_from_message(res.result.message, self.model, batch=True)
                else:
                    turn = {
                        "content": [],
                        "stop_reason": "error",
                        "error": res.result.type,
                        "usage": {},
                        "cost": 0.0,
                    }
                turn["request_id"] = res.custom_id
                spent += turn["cost"]
                got[k] = turn
            self.ledger.settle(
                self.model,
                token,
                spent,
                {"batch_id": batch.id, "requests": len(reqs), "batch": True},
            )
            nxt = {}
            for k, (g, _) in pending.items():
                turn = got.get(
                    k,
                    {
                        "content": [],
                        "stop_reason": "error",
                        "error": "missing",
                        "usage": {},
                        "cost": 0.0,
                    },
                )
                try:
                    nxt[k] = (g, g.send(turn))
                except StopIteration as stop:
                    done[k] = stop.value
            pending = nxt
        return done
