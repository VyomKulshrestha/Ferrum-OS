"""Serving fixes of the Kaggle runner: the Granite 3.3 chat template and the tool-calling self-check."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from test_ol1_kaggle import load_built  # noqa: E402

INSTRUCTION = "respond only with <|tool_call|> followed by a JSON list of tools used"


def render(K, messages, tools):
    """Render as vLLM does: the template from --chat-template, OpenAI-format tools, tool-call arguments
    already parsed to objects (vllm/renderers/chat_utils.py, _postprocess_messages)."""
    sandbox = pytest.importorskip("jinja2.sandbox")
    env = sandbox.ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = lambda x, indent=None: json.dumps(x, indent=indent)
    return env.from_string(K.GRANITE_TEMPLATE).render(
        messages=messages, tools=tools, add_generation_prompt=True
    )


def test_granite_template_carries_the_instruction_and_the_calls():
    K = load_built()
    msgs, fn = K.to_openai(
        "You are the alarm operator.",
        K.TOOLS,
        [
            {"role": "user", "content": "Review 1."},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "a1",
                        "name": "read_configuration",
                        "input": {},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "a1",
                        "content": "Configuration: ...",
                    }
                ],
            },
        ],
    )
    for m in msgs:  # what vLLM hands the template
        for c in m.get("tool_calls", []):
            c["function"]["arguments"] = json.loads(c["function"]["arguments"])
    out = render(K, msgs, fn)
    system = out.split("<|end_of_text|>")[0]
    assert system.startswith(
        "<|start_of_role|>system<|end_of_role|>You are the alarm operator."
    )
    assert INSTRUCTION in system
    assert (
        '<|start_of_role|>available_tools<|end_of_role|>[\n    {\n        "type": "function"'
        in out
    )
    assert (
        '<|start_of_role|>assistant<|end_of_role|><|tool_call|>[{"name": "read_configuration", "arguments": {}}]'
        in out
    )
    assert (
        "<|start_of_role|>tool<|end_of_role|>Configuration: ...<|end_of_text|>" in out
    )
    assert out.endswith("<|start_of_role|>assistant<|end_of_role|>")
    assert out.count("<|start_of_role|>system") == 1


def test_only_granite_gets_the_template(tmp_path):
    K = load_built()
    for name, spec in K.OPEN_MODELS.items():
        cmd = K.server_command(spec, "/model", template_dir=str(tmp_path))
        if name == "granite-3.3-8b":
            path = cmd[cmd.index("--chat-template") + 1]
            assert Path(path).read_text() == K.GRANITE_TEMPLATE
            assert cmd[cmd.index("--tool-call-parser") + 1] == "granite"
        else:
            assert "--chat-template" not in cmd


class Reply:
    def __init__(self, turns):
        self.turns, self.calls = list(turns), 0

    def complete(self, system, tools, messages):
        self.calls += 1
        assert system and tools[0]["name"] == "record_value"
        return self.turns.pop(0)


def tool_turn(value):
    return {
        "content": [
            {
                "type": "tool_use",
                "id": "x",
                "name": "record_value",
                "input": {"value": value},
            }
        ],
        "stop_reason": "tool_use",
    }


PROSE = {
    "content": [{"type": "text", "text": "Action: use record_value with 7."}],
    "stop_reason": "end_turn",
}


def test_self_check_passes_on_a_parsed_call(capsys):
    K = load_built()
    b = Reply([PROSE, tool_turn(7)])
    assert K.self_check(b) and b.calls == 2
    assert "OL1STAGE tool_check_ok" in capsys.readouterr().out


def test_self_check_stops_a_model_that_answers_in_prose(capsys):
    K = load_built()
    assert not K.self_check(Reply([PROSE, PROSE, tool_turn(8)]))
    out = capsys.readouterr().out
    assert out.startswith("OL1FAIL tool_calling ") and "Action: use record_value" in out
