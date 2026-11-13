# ruff: noqa: F821  (json, hashlib, Episode, run_episode, leak_scan, load_job_input, CORE_DIGEST come from ol1_core in the build)
# ---------------------------------------------------------------- ol1 Kaggle runner (open-weight models)
# Run in one Kaggle notebook cell (GPU: T4 x2, Internet on) with the dataset that holds this file and the
# job file attached:
#     import os, glob, runpy
#     os.environ["OL1_MODEL"] = "qwen3-8b"
#     runpy.run_path(glob.glob("/kaggle/input/**/ol1_kaggle.py", recursive=True)[0], run_name="__main__")
# No API token of any kind is needed.
#
# Input: one job file (ol1_jobs_*.npz; OL1_JOBS names it when the dataset holds more than one). It holds D1
# score windows of attack-free runs, the mode constants and the job list; no sensor value, label or attack
# run.
# Output: /kaggle/working/ol1_results_<model>_<k>of<n>.jsonl (one episode per line) and a .done marker; in
# the log, one line "OL1REC {...}" per finished episode (what the analysis needs; scripts/ol1_kaggle_ingest.py
# turns pasted lines into episode records), stage lines "OL1STAGE ...", and at the end one line
# "OL1DONE {...}" with the number of episodes, the sha256 of the results file and the elapsed seconds.

import glob
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

T_START = time.time()

# Models at pinned revisions; tool calling as documented for vLLM's OpenAI-compatible server. "ignore" keeps
# the explicit download to the weights the server loads (Mistral's consolidated file, not both formats).
OPEN_MODELS = {
    "qwen3-8b": {
        "repo": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "args": ["--tool-call-parser", "hermes", "--reasoning-parser", "qwen3", "--dtype", "half"],
        "ignore": ["*.pth", "*.bin", "original/*"],
    },
    "mistral-nemo-12b": {
        "repo": "mistralai/Mistral-Nemo-Instruct-2407",
        "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3",
        "args": ["--tool-call-parser", "mistral", "--tokenizer-mode", "mistral", "--config-format", "mistral",
                 "--load-format", "mistral", "--dtype", "half"],
        "ignore": ["*.pth", "*.bin", "model-*.safetensors", "model.safetensors.index.json"],
        # 24.5 GB of fp16 weights leave about 1.5 GB of cache per T4: a shorter context, shorter answers
        "max_model_len": 16384, "max_tokens": 4096, "gpu_memory_utilization": "0.95",
    },
    "granite-3.3-8b": {
        "repo": "ibm-granite/granite-3.3-8b-instruct",
        "revision": "51dd4bc2ade4059a6bd87649d68aa11e4fb2529b",
        "args": ["--tool-call-parser", "granite", "--dtype", "half"],
        "ignore": ["*.pth", "*.bin", "original/*"],
    },
    "qwen3-32b-awq": {
        "repo": "Qwen/Qwen3-32B-AWQ",
        "revision": "0499c3ac83fdef8810b907a23894ba91e95eddd8",
        "args": ["--tool-call-parser", "hermes", "--reasoning-parser", "qwen3", "--quantization", "awq", "--dtype", "half"],
        "ignore": ["*.pth", "*.bin", "original/*"],
    },
}  # fmt: skip
VLLM_VERSION = "0.32.0"
MODEL = os.environ.get("OL1_MODEL", "qwen3-8b")
MAX_TOKENS = (
    8000  # per call, as for the Claude models (OPEN_MODELS may lower it per model)
)
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
    def __init__(self, name, port=PORT, max_tokens=MAX_TOKENS):
        self.name, self.url = name, f"http://127.0.0.1:{port}/v1/chat/completions"
        self.max_tokens = max_tokens

    def complete(self, system, tools, messages):
        msgs, fn = to_openai(system, tools, messages)
        body = {
            "model": self.name,
            "messages": msgs,
            "tools": fn,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
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
                    "max_tokens": self.max_tokens,
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


SERVER_LOG = "/kaggle/working/vllm_server.log"


def stage(name, **kw):
    """One progress line in the notebook log: OL1STAGE <name> <elapsed s> {details}."""
    print(f"OL1STAGE {name} {time.time() - T_START:.0f}s {json.dumps(kw)}", flush=True)


def tree_bytes(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def download_model(spec):
    """Download the pinned snapshot before the server starts, with a progress line a minute, so a slow
    download and a slow server start can be told apart in the log. Returns the local snapshot path."""
    from huggingface_hub import snapshot_download

    try:
        from huggingface_hub import constants

        cache = constants.HF_HUB_CACHE
    except (
        ImportError,
        AttributeError,
    ):  # progress lines only; the download does not need it
        cache = os.path.expanduser("~/.cache/huggingface/hub")
    repo_dir = os.path.join(cache, "models--" + spec["repo"].replace("/", "--"))
    box, done = {}, threading.Event()

    def get():
        try:
            box["path"] = snapshot_download(
                spec["repo"], revision=spec["revision"], ignore_patterns=spec["ignore"]
            )
        except Exception as e:  # noqa: BLE001  reported below
            box["error"] = e
        done.set()

    threading.Thread(target=get, daemon=True).start()
    stage("download_start", repo=spec["repo"], revision=spec["revision"])
    while not done.wait(60):
        stage("download_progress", gb=round(tree_bytes(repo_dir) / 1e9, 2))
    if "error" in box:
        raise RuntimeError(f"model download failed: {box['error']!r}")
    stage("download_done", gb=round(tree_bytes(repo_dir) / 1e9, 2))
    return box["path"]


def server_log_tail(n=60):
    try:
        with open(SERVER_LOG, errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError as e:
        return f"(no server log: {e})"


def start_server(spec, model_path):
    cmd = [sys.executable, "-m", "vllm.entrypoints.openai.api_server", "--model", model_path,
           "--served-model-name", MODEL, "--tensor-parallel-size", "2", "--max-model-len", str(spec.get("max_model_len", MAX_MODEL_LEN)),
           "--enable-auto-tool-choice", "--enable-prefix-caching", "--gpu-memory-utilization", spec.get("gpu_memory_utilization", "0.92"),
           "--generation-config", "auto", "--port", str(PORT)] + spec["args"]  # fmt: skip
    log = open(SERVER_LOG, "w")  # noqa: SIM115  kept open for the server's lifetime
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    stage("server_start")
    for i in range(360):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5):
                stage("server_ready")
                return proc
        except Exception:  # noqa: BLE001  not up yet
            if proc.poll() is not None:
                print(
                    "OL1FAIL vLLM server exited; last lines of its log:\n"
                    + server_log_tail(),
                    flush=True,
                )
                raise RuntimeError(f"vLLM server exited; see {SERVER_LOG}") from None
            if i % 6 == 5:
                stage("server_waiting")
            time.sleep(10)
    print(
        "OL1FAIL vLLM server not ready after an hour; last lines of its log:\n"
        + server_log_tail(),
        flush=True,
    )
    proc.terminate()
    raise RuntimeError("vLLM server did not start within an hour")


TOOL_ABBREV = {
    "set_threshold": "thr",
    "set_alarm_delay": "dly",
    "suppress_alarms": "sup",
    "recalibrate_threshold": "rcl",
    "exclude_channel": "exc",
    "read_alarm_history": "rah",
    "read_score_summary": "rss",
    "read_configuration": "rcf",
    "escalate_to_engineer": "esc",
    "close_review": "cls",
}
MAX_HISTORY = 24


def ol1rec(r, carry, model):
    """The compact per-episode record printed to the log (see scripts/ol1_kaggle_ingest.py): what the
    analysis needs and nothing else. The terminal outcomes are recomputed from the final configuration."""
    o, f = r["outcomes"], r["final_config"]
    hist = []
    for rv in r["reviews"]:
        for e in rv["events"]:
            if e["outcome"] != "applied":
                continue
            a = e["after"]
            v = {"set_threshold": a["threshold"], "recalibrate_threshold": a["threshold"], "set_alarm_delay": a["delay_s"],
                 "suppress_alarms": e["input"].get("hours"), "exclude_channel": 1}.get(e["tool"])  # fmt: skip
            hist.append(
                [
                    e["review"],
                    TOOL_ABBREV[e["tool"]],
                    round(float(v), 4) if v is not None else None,
                ]
            )
    ends = {}
    for x in o["review_ends"]:
        ends[x] = ends.get(x, 0) + 1
    rec = {
        "M": model,
        "m": r["mode"],
        "s": r["seed"],
        "c": r["condition"],
        "a": r["arm"],
        "f": [f["threshold"], f["delay_s"], f["mute_until"], int(bool(f["excluded"]))],
        "k": int(carry),
        "h": hist[:MAX_HISTORY],
        "hn": len(hist),
        "n": [
            sum(len(rv["calls"]) for rv in r["reviews"]),
            o["invalid_calls"],
            o["gate_blocked"],
            o["gate_escalated"],
            o["escalations"],
        ],  # fmt: skip
        "e": ends,
        "o": [
            int(o["loosened_beyond_ceiling"]),
            o["first_beyond_ceiling_review"],
            int(o["loosened_any"]),
            o["first_loosening_review"],
            int(o["tightened_any"]),
            int(o["no_change"]),
        ],  # fmt: skip
        "ap": o["alarm_episodes_per_review"],
        "tb": [TOOL_ABBREV.get(t, t) for t in o["tools_after_block"]],
        "d": [TOOL_ABBREV.get(t, t) for t in o["dials_applied"]],
    }
    leaks = r.get("leaks") or leak_scan(r)
    if leaks:
        rec["L"] = leaks
    return "OL1REC " + json.dumps(rec, separators=(",", ":"))


def find_job_file():
    name = os.environ.get("OL1_JOBS")
    files = glob.glob(f"/kaggle/input/**/{name or 'ol1_jobs_*.npz'}", recursive=True)
    if len(files) != 1:
        raise SystemExit(
            f"expected one job file under /kaggle/input, found {files}; set OL1_JOBS"
        )
    return files[0]


def main():
    stage("start", model=MODEL, shard=SHARD)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", f"vllm=={VLLM_VERSION}"],
        check=True,
    )
    stage("pip_done", vllm=VLLM_VERSION)
    job_file = find_job_file()
    modes, windows, jobs, meta = load_job_input(job_file)
    if meta.get("core_digest") and meta["core_digest"] != CORE_DIGEST:
        print("warning: job file was written with another version of ol1_core")
    stage("jobs", file=os.path.basename(job_file), jobs=len(jobs), source=meta.get("source"),
          core_digest_match=meta.get("core_digest") == CORE_DIGEST)  # fmt: skip
    k, n = (int(x) for x in SHARD.split("/"))
    jobs = jobs[k::n]
    spec = OPEN_MODELS[MODEL]
    path = download_model(spec)
    proc = start_server(spec, path)
    out = f"/kaggle/working/ol1_results_{MODEL}_{k}of{n}.jsonl"
    done = set()
    if os.path.exists(out):  # resume
        with open(out) as f:
            for line in f:
                r = json.loads(line)
                done.add((r["mode"], r["seed"], r["condition"], r["arm"]))
    backend = OpenAIBackend(MODEL, max_tokens=spec.get("max_tokens", MAX_TOKENS))
    lock = threading.Lock()
    header = {"model": MODEL, "repo": spec["repo"], "revision": spec["revision"], "vllm": VLLM_VERSION,
              "max_tokens": backend.max_tokens, "source": meta.get("source"), "core_digest": CORE_DIGEST}  # fmt: skip

    def one(job):
        m, s, c, a = job
        if (m, s, c, a) in done:
            return
        ep = Episode(
            modes[m], s, c, a, source=meta.get("source", "dev"), windows=windows[(m, s)]
        )
        r = run_episode(ep, backend)
        r.update({"model": MODEL, "leaks": leak_scan(r), "run": header})
        line = ol1rec(r, ep.carry, MODEL)
        with lock:
            with open(out, "a") as f:
                f.write(json.dumps(r) + "\n")
            print(line, flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(CONCURRENT_EPISODES) as ex:
        list(ex.map(one, jobs))
    with open(out + ".done", "w") as f:
        f.write(json.dumps({**header, "jobs": len(jobs), "seconds": time.time() - t0}))
    proc.terminate()
    with open(out, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(out) as f:
        n_ep = sum(1 for line in f if line.strip())
    print("written", out)
    print("OL1DONE " + json.dumps({"model": MODEL, "shard": SHARD, "episodes": n_ep, "results_sha256": digest,
                                   "seconds": round(time.time() - T_START)}), flush=True)  # fmt: skip


if __name__ == "__main__":
    main()
