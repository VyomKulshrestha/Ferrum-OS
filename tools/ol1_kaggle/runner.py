# ruff: noqa: F821  (json, Episode, run_episode, leak_scan, load_job_input, CORE_DIGEST come from ol1_core in the build)
# ---------------------------------------------------------------- ol1 Kaggle runner (open-weight models)
# Paste the whole of ol1_kaggle.py into one Kaggle notebook cell (GPU: T4 x2, Internet on), attach the
# dataset that holds the job file, set MODEL below, run. No API token of any kind is needed.
#
# Input: one job file written by `python scripts/ol1_export.py jobs ...` (development: ol1_jobs_dev.npz;
# the registered run uses the sealed job file written after registration). It holds D1 score windows of
# attack-free runs, the mode constants and the job list; no sensor value, label or attack run.
# Output: /kaggle/working/ol1_results_<model>.jsonl (one episode per line) and a .done marker.

import glob
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Models at pinned revisions; tool calling as documented for vLLM's OpenAI-compatible server.
OPEN_MODELS = {
    "qwen3-8b": {
        "repo": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "args": ["--tool-call-parser", "hermes", "--reasoning-parser", "qwen3", "--dtype", "half"],
    },
    "mistral-nemo-12b": {
        "repo": "mistralai/Mistral-Nemo-Instruct-2407",
        "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3",
        "args": ["--tool-call-parser", "mistral", "--tokenizer-mode", "mistral", "--config-format", "mistral",
                 "--load-format", "mistral", "--dtype", "half"],
    },
    "granite-3.3-8b": {
        "repo": "ibm-granite/granite-3.3-8b-instruct",
        "revision": "51dd4bc2ade4059a6bd87649d68aa11e4fb2529b",
        "args": ["--tool-call-parser", "granite", "--dtype", "half"],
    },
    "qwen3-32b-awq": {
        "repo": "Qwen/Qwen3-32B-AWQ",
        "revision": "0499c3ac83fdef8810b907a23894ba91e95eddd8",
        "args": ["--tool-call-parser", "hermes", "--reasoning-parser", "qwen3", "--quantization", "awq", "--dtype", "half"],
    },
}  # fmt: skip
VLLM_VERSION = "0.32.0"
MODEL = os.environ.get("OL1_MODEL", "qwen3-8b")
MAX_TOKENS = 8000  # per call, as for the Claude models
MAX_MODEL_LEN = 32768
CONCURRENT_EPISODES = 32
SHARD = os.environ.get(
    "OL1_SHARD", "0/1"
)  # "k/n": run every n-th job starting at k (12-hour session limit)
PORT = 8000


def to_openai(system, tools, messages):
    """Anthropic-format review conversation -> OpenAI chat messages and tools (thinking is not replayed)."""
    out = [{"role": "system", "content": system}]
    for m in messages:
        if isinstance(m["content"], str):
            out.append({"role": m["role"], "content": m["content"]})
            continue
        if m["role"] == "assistant":
            text = "".join(
                b.get("text", "") for b in m["content"] if b["type"] == "text"
            )
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {
                        "name": b["name"],
                        "arguments": json.dumps(b["input"]),
                    },
                }
                for b in m["content"]
                if b["type"] == "tool_use"
            ]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in m["content"]:
                if b["type"] == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": b["content"],
                        }
                    )
                elif b["type"] == "text":
                    out.append({"role": "user", "content": b["text"]})
    fn = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]
    return out, fn


STOP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}


def from_openai(resp):
    """OpenAI chat completion -> the turn dict of the review loop."""
    ch = resp["choices"][0]
    msg = ch["message"]
    content = []
    if msg.get("reasoning_content"):
        content.append({"type": "thinking", "thinking": msg["reasoning_content"]})
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for i, c in enumerate(msg.get("tool_calls") or []):
        try:
            args = json.loads(c["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {"__unparsed_arguments__": c["function"]["arguments"]}
        content.append(
            {
                "type": "tool_use",
                "id": c.get("id") or f"call_{i}",
                "name": c["function"]["name"],
                "input": args,
            }
        )
    stop = STOP.get(ch.get("finish_reason"), ch.get("finish_reason") or "end_turn")
    if stop == "end_turn" and any(b["type"] == "tool_use" for b in content):
        stop = "tool_use"
    u = resp.get("usage") or {}
    return {
        "content": content,
        "stop_reason": stop,
        "usage": {
            "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0),
        },
        "request_id": resp.get("id"),
        "cost": 0.0,
    }


class OpenAIBackend:
    def __init__(self, name, port=PORT):
        self.name, self.url = name, f"http://127.0.0.1:{port}/v1/chat/completions"

    def complete(self, system, tools, messages):
        msgs, fn = to_openai(system, tools, messages)
        body = {
            "model": self.name,
            "messages": msgs,
            "tools": fn,
            "tool_choice": "auto",
            "max_tokens": MAX_TOKENS,
        }
        req = urllib.request.Request(
            self.url, json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    t = from_openai(json.loads(r.read()))
                t["request"] = {
                    "model": self.name,
                    "max_tokens": MAX_TOKENS,
                    "tool_choice": "auto",
                }
                return t
            except Exception as e:  # noqa: BLE001  recorded as an error turn after three attempts
                err = f"{type(e).__name__}: {str(e)[:300]}"
                time.sleep(5 * (attempt + 1))
        return {
            "content": [],
            "stop_reason": "error",
            "error": err,
            "usage": {},
            "cost": 0.0,
        }


def start_server(spec):
    cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", spec["repo"], "--revision", spec["revision"],
           "--served-model-name", MODEL, "--tensor-parallel-size", "2", "--max-model-len", str(MAX_MODEL_LEN),
           "--enable-auto-tool-choice", "--enable-prefix-caching", "--gpu-memory-utilization", "0.92",
           "--generation-config", "auto", "--port", str(PORT)] + spec["args"]  # fmt: skip
    log = open("/kaggle/working/vllm_server.log", "w")  # noqa: SIM115  kept open for the server's lifetime
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(360):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5):
                return proc
        except Exception:  # noqa: BLE001  not up yet
            if proc.poll() is not None:
                raise RuntimeError(
                    "vLLM server exited; see /kaggle/working/vllm_server.log"
                )
            time.sleep(10)
    raise RuntimeError("vLLM server did not start within an hour")


def main():
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", f"vllm=={VLLM_VERSION}"],
        check=True,
    )
    files = glob.glob("/kaggle/input/**/ol1_jobs_*.npz", recursive=True)
    if len(files) != 1:
        raise SystemExit(
            f"expected one ol1_jobs_*.npz under /kaggle/input, found {files}"
        )
    modes, windows, jobs, meta = load_job_input(files[0])
    if meta.get("core_digest") and meta["core_digest"] != CORE_DIGEST:
        print("warning: job file was written with another version of ol1_core")
    k, n = (int(x) for x in SHARD.split("/"))
    jobs = jobs[k::n]
    spec = OPEN_MODELS[MODEL]
    proc = start_server(spec)
    out = f"/kaggle/working/ol1_results_{MODEL}_{k}of{n}.jsonl"
    done = set()
    if os.path.exists(out):  # resume
        with open(out) as f:
            for line in f:
                r = json.loads(line)
                done.add((r["mode"], r["seed"], r["condition"], r["arm"]))
    backend, lock = OpenAIBackend(MODEL), threading.Lock()
    header = {"model": MODEL, "repo": spec["repo"], "revision": spec["revision"], "vllm": VLLM_VERSION,
              "max_tokens": MAX_TOKENS, "source": meta.get("source"), "core_digest": CORE_DIGEST}  # fmt: skip

    def one(job):
        m, s, c, a = job
        if (m, s, c, a) in done:
            return
        r = run_episode(Episode(modes[m], s, c, a, windows=windows[(m, s)]), backend)
        r.update({"model": MODEL, "leaks": leak_scan(r), "run": header})
        with lock, open(out, "a") as f:
            f.write(json.dumps(r) + "\n")
        print(
            m,
            s,
            c,
            a,
            r["outcomes"]["loosened_beyond_ceiling"],
            r["terminal_hits"],
            flush=True,
        )

    t0 = time.time()
    with ThreadPoolExecutor(CONCURRENT_EPISODES) as ex:
        list(ex.map(one, jobs))
    with open(out + ".done", "w") as f:
        f.write(json.dumps({**header, "jobs": len(jobs), "seconds": time.time() - t0}))
    proc.terminate()
    print("written", out)


if __name__ == "__main__":
    main()
