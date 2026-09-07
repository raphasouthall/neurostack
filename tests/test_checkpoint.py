# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the idle checkpoint (issue #143).

The checkpoint hands the summarising back to the harness's own model, so the
Python side has two halves worth proving: the prompt it prints, and what it
does with the JSON that comes back. Both run against the fake MCP endpoint in
`conftest.py` — no live server, and never an LLM.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from neurostack.adapters import (
    claude_hook_entries,
    claude_save_command_path,
    install_claude_adapter,
    install_omp_adapter,
)
from neurostack.cli.hook import _state_path, run_checkpoint_save, run_event
from neurostack.client import ClientConfig

LONG_OUTPUT = "x" * 2000


@pytest.fixture(autouse=True)
def _throwaway_home(isolated_home):
    """Every test here writes state and adapters into a throwaway HOME."""
    return isolated_home


def _cfg(server, **kwargs):
    return ClientConfig(url=server.url, timeout_s=5.0, **kwargs)


def _tool_calls(server, name):
    return [args for called, args in server.calls if called == name]


def _turn(i: int) -> list[dict]:
    """One user turn and the assistant turn that answers it with a tool call."""
    return [
        {"role": "user", "content": f"question {i} about the checkpoint window"},
        {"role": "assistant", "content": [
            {"type": "text", "text": f"answer {i}"},
            {"type": "tool_use", "name": f"tool_{i}", "input": {}},
            {"type": "tool_result", "content": LONG_OUTPUT},
        ]},
    ]


def _messages(turns: int) -> list[dict]:
    out: list[dict] = []
    for i in range(turns):
        out += _turn(i)
    return out


def _payload(messages, session="ck", **extra):
    return {"session": session, "messages": messages, "since_index": 0, **extra}


def _state(session):
    return json.loads(_state_path(session).read_text())


def _run_cli(args, stdin, server_url, home):
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home.parent / "cache"),
        "NEUROSTACK_URL": server_url,
    }
    return subprocess.run(
        [sys.executable, "-m", "neurostack", "hook", *args],
        input=stdin, capture_output=True, text=True, env=env, timeout=120,
    )


# ---------------------------------------------------------------------------
# Acceptance 1 — a short window is not worth a model call
# ---------------------------------------------------------------------------

def test_three_messages_print_nothing_and_exit_zero(server, isolated_home):
    messages = _messages(1) + [{"role": "user", "content": "and one more"}]
    result = _run_cli(["checkpoint"], json.dumps(_payload(messages)),
                      server.url, isolated_home)
    assert result.returncode == 0
    assert result.stdout == ""
    assert server.calls == []


def test_chat_without_tools_or_a_long_prompt_is_skipped(server):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"ok {i}"}
                for i in range(12)]
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text == ""


def test_a_long_user_message_alone_earns_a_checkpoint(server):
    messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": "ok"}
                for i in range(12)]
    messages[0]["content"] = "why " * 100
    verdict = run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    assert "NeuroStack checkpoint" in verdict.text


# ---------------------------------------------------------------------------
# Acceptance 2 — the prompt carries the session, clipped
# ---------------------------------------------------------------------------

def test_forty_messages_print_a_prompt_with_every_user_message(server):
    messages = _messages(20)
    verdict = run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    assert len(messages) == 40
    for i in range(20):
        assert f"question {i} about the checkpoint window" in verdict.text
        assert f"[tool] tool_{i}" in verdict.text
    outputs = [line.removeprefix("[tool output] ")
               for line in verdict.text.splitlines() if line.startswith("[tool output] ")]
    assert len(outputs) == 20
    assert all(len(output) <= 500 for output in outputs)
    assert LONG_OUTPUT not in verdict.text
    # The prompt names the reply shape and every trigger prefix.
    for token in ('"entity_type"', "when-calling:", "when-editing:", "when-error:",
                  "checkpoint --save"):
        assert token in verdict.text


def test_the_prompt_never_calls_the_server(server):
    run_event("checkpoint", _payload(_messages(20)), cfg=_cfg(server))
    assert server.calls == []


def test_a_claude_stop_reads_the_window_out_of_the_transcript(server, tmp_path):
    transcript = tmp_path / "sess.jsonl"
    transcript.write_text("\n".join(
        json.dumps({"type": role, "message": {"role": role, "content": [
            {"type": "text", "text": f"{role} line {i}"},
            {"type": "tool_use", "name": "read"},
        ]}})
        for i, role in enumerate(["user", "assistant"] * 5)
    ))
    verdict = run_event(
        "checkpoint",
        {"session": "stopped", "transcript_path": str(transcript), "format": "claude-code"},
        cfg=_cfg(server),
    )
    assert "user line 0" in verdict.text
    assert "[tool] read" in verdict.text
    assert _state("stopped")["offered_index"] == 10


def test_a_second_stop_in_the_same_turn_is_ignored(server):
    payload = _payload(_messages(20))
    payload["stop_hook_active"] = True
    assert run_event("checkpoint", payload, cfg=_cfg(server)).text == ""


# ---------------------------------------------------------------------------
# Acceptance 3 — --save writes one memory per item and moves the index
# ---------------------------------------------------------------------------

REPLY = json.dumps([
    {"content": "The gate is ruff plus pytest; basedpyright strict noise is ignored.",
     "entity_type": "convention", "tags": ["neurostack", "gate"]},
    {"content": "vault_write_file commits and pushes; there is no dry run.",
     "entity_type": "learning", "tags": ["vault"],
     "trigger": "when-calling:vault_write_file"},
])


def test_save_writes_one_memory_per_item_and_advances_the_index(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 1}
    run_event("checkpoint", _payload(_messages(20)), cfg=_cfg(server))
    assert _state("ck")["since_index"] == 0

    verdict = run_checkpoint_save(REPLY, "ck", "omp", cfg=_cfg(server))
    calls = _tool_calls(server, "vault_remember")
    assert len(calls) == 2
    assert "saved 2 of 2" in verdict.text
    assert calls[0]["source_agent"] == "checkpoint/omp"
    assert calls[0]["entity_type"] == "convention"
    # A trigger is a tag, not a column (#131), so it joins the tag list.
    assert calls[1]["tags"] == ["vault", "when-calling:vault_write_file"]
    state = _state("ck")
    assert state["since_index"] == 40
    assert state["last_checkpoint_at"] > 0


def test_a_malformed_trigger_is_dropped_rather_than_saved(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 2}
    reply = json.dumps([{"content": "a fact", "tags": ["x"], "trigger": "when-writing:foo"}])
    run_checkpoint_save(reply, "ck", "cli", cfg=_cfg(server))
    assert _tool_calls(server, "vault_remember")[0]["tags"] == ["x"]


def test_a_failed_save_puts_the_window_back_on_offer(server):
    messages = _messages(20)
    run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    dead = ClientConfig(url="http://127.0.0.1:1/mcp", timeout_s=1.0)
    verdict = run_checkpoint_save(REPLY, "ck", "omp", cfg=dead)
    assert "saved 0 of 2" in verdict.text
    state = _state("ck")
    assert state["since_index"] == 0
    assert state["offered_index"] == 0
    # The same window is offered again rather than lost with the server.
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text != ""


def test_save_accepts_a_fenced_array_a_bare_object_and_prose(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 3}
    fenced = '```json\n[{"content": "fenced fact"}]\n```'
    bare = '{"content": "bare object fact"}'
    prose = 'Here is what I kept:\n[{"content": "prose fact"}]\nThat is all.'
    for reply in (fenced, bare, prose):
        run_checkpoint_save(reply, "ck", "cli", cfg=_cfg(server))
    assert [c["content"] for c in _tool_calls(server, "vault_remember")] == [
        "fenced fact", "bare object fact", "prose fact",
    ]


def test_an_empty_reply_saves_nothing(server):
    verdict = run_checkpoint_save("[]", "ck", "cli", cfg=_cfg(server))
    assert server.calls == []
    assert "saved 0 of 0" in verdict.text


def test_save_through_the_cli_uses_the_newest_session_state(server, isolated_home):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 4}
    prompt = _run_cli(["checkpoint", "--session", "herdr-7"],
                      json.dumps({"messages": _messages(20), "since_index": 0}),
                      server.url, isolated_home)
    assert "NeuroStack checkpoint" in prompt.stdout
    saved = _run_cli(["checkpoint", "--save"], REPLY, server.url, isolated_home)
    assert saved.returncode == 0
    assert "saved 2 of 2" in saved.stdout
    assert len(_tool_calls(server, "vault_remember")) == 2
    assert _state("herdr-7")["since_index"] == 40


# ---------------------------------------------------------------------------
# Acceptance 4 — dedup by index
# ---------------------------------------------------------------------------

def test_the_same_window_is_not_offered_twice(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 5}
    messages = _messages(20)
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text != ""
    run_checkpoint_save(REPLY, "ck", "omp", cfg=_cfg(server))
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text == ""


def test_a_declined_window_is_not_re_offered_either(server):
    """Claude Code's Stop hook fires every turn; one refusal must settle it."""
    messages = _messages(20)
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text != ""
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text == ""


def test_new_messages_after_a_save_start_a_new_window(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 6}
    run_event("checkpoint", _payload(_messages(20)), cfg=_cfg(server))
    run_checkpoint_save(REPLY, "ck", "omp", cfg=_cfg(server))
    later = _payload(_messages(20) + _messages(5))
    verdict = run_event("checkpoint", later, cfg=_cfg(server))
    assert "question 4 about the checkpoint window" in verdict.text
    assert _state("ck")["offered_index"] == 50


# ---------------------------------------------------------------------------
# Acceptance 5 — redaction runs before the save
# ---------------------------------------------------------------------------

def test_a_value_shaped_secret_is_redacted_before_the_save(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 7}
    reply = json.dumps([{
        "content": 'The importer needs password="h0rs3-b4tt3ry-st4pl3" '
                   "and the key sk-proj-" + "a" * 40,
        "tags": ["import"],
    }])
    run_checkpoint_save(reply, "ck", "cli", cfg=_cfg(server))
    saved = _tool_calls(server, "vault_remember")[0]["content"]
    assert "h0rs3-b4tt3ry-st4pl3" not in saved
    assert "a" * 40 not in saved
    assert saved.count("***REDACTED***") == 2
    # The sentence still says which kind of credential went.
    assert "password=" in saved


def test_a_placeholder_password_survives(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 8}
    reply = json.dumps([{"content": 'Set password="${VAULT_PASSWORD}" in the unit file.'}])
    run_checkpoint_save(reply, "ck", "cli", cfg=_cfg(server))
    assert "${VAULT_PASSWORD}" in _tool_calls(server, "vault_remember")[0]["content"]


# ---------------------------------------------------------------------------
# Acceptance 6 — the generated adapters carry the cadence
# ---------------------------------------------------------------------------

def _find_bun() -> str | None:
    """Resolve bun before HOME is patched — the fixture moves it out of reach."""
    on_path = shutil.which("bun")
    if on_path:
        return on_path
    bundled = Path.home() / ".bun" / "bin" / "bun"
    return str(bundled) if bundled.exists() else None


BUN = _find_bun()


def _install_omp(isolated_home, binary="/opt/bin/neurostack"):
    (isolated_home / ".omp").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary", return_value=binary):
        status, path = install_omp_adapter()
    assert status == "installed"
    return path


def test_the_omp_adapter_carries_the_cadence_and_a_save_command(isolated_home):
    source = _install_omp(isolated_home).read_text()
    assert "EVERY_MESSAGES = 40" in source
    assert "QUIET_MS = 30 * 60_000" in source
    assert "MIN_MESSAGES = 5" in source
    assert 'registerCommand("save"' in source
    assert 'hook("checkpoint"' in source
    assert '"--save"' in source
    assert " any" not in source and ": any" not in source


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_transpiles_under_bun(isolated_home, tmp_path):
    path = _install_omp(isolated_home)
    result = subprocess.run(
        [BUN, "build", str(path), "--target=bun", "--outfile", str(tmp_path / "out.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out.js").exists()


_DRIVER = """\
import extension from "{adapter}";

const log: string[] = [];
const injected: string[] = [];
const handlers: Record<string, (e: unknown, c: unknown) => unknown> = {{}};
const commands: Record<string, {{ handler: () => unknown }}> = {{}};
let intervalMs = 0;

extension({{
  on: (e, h) => {{ handlers[e] = h; }},
  sendMessage: () => {{}},
  sendUserMessage: (t: string) => {{ injected.push(t); }},
  registerCommand: (n: string, c: {{ handler: () => unknown }}) => {{ commands[n] = c; }},
}} as never);

const ctx = {{ setInterval: (_f: () => void, ms: number) => {{ intervalMs = ms; }} }};
await handlers.session_start?.({{}}, ctx);

const settle = () => new Promise((r) => setTimeout(r, 400));
const messages = Array.from({{ length: {count} }}, (_v, i) => ({{
  role: i % 2 === 0 ? "user" : "assistant",
  content: `message ${{i}}`,
}}));
await handlers.context?.({{ messages }}, ctx);
await settle();
log.push(`injected=${{injected.length}}`);
log.push(`tagged=${{injected[0]?.includes("neurostack-checkpoint") ?? false}}`);
log.push(`timer=${{intervalMs}}`);
log.push(`command=${{typeof commands.save?.handler}}`);

const reply = {{ role: "assistant", content: '[{{"content": "x"}}]' }};
handlers.message_end?.({{ message: reply }}, ctx);
await settle();
console.log(log.join("\\n"));
"""

_FAKE_BIN = """\
#!/bin/sh
printf '%s\\n' "$*" >>"$NEUROSTACK_TEST_LOG"
cat >/dev/null
case "$2 $3" in
  "checkpoint --save") ;;
  checkpoint*) echo "a checkpoint prompt" ;;
esac
"""


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_checkpoints_at_forty_messages(isolated_home, tmp_path):
    """Drive the generated extension under Bun with a stub `pi` and CLI."""
    calls = tmp_path / "calls.txt"
    fake_bin = tmp_path / "neurostack"
    fake_bin.write_text(_FAKE_BIN)
    fake_bin.chmod(0o755)
    adapter = _install_omp(isolated_home, binary=str(fake_bin))
    driver = tmp_path / "driver.ts"
    driver.write_text(_DRIVER.format(adapter=adapter, count=40))

    result = subprocess.run(
        [BUN, "run", str(driver)], capture_output=True, text=True, timeout=120,
        env={**os.environ, "NEUROSTACK_TEST_LOG": str(calls)},
    )
    assert result.returncode == 0, result.stderr
    reported = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert reported == {"injected": "1", "tagged": "true",
                        "timer": "60000", "command": "function"}
    argv = calls.read_text().splitlines()
    assert "hook checkpoint" in argv
    assert "hook checkpoint --save --harness omp --session" in " ".join(argv)


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_leaves_a_short_window_alone(isolated_home, tmp_path):
    calls = tmp_path / "calls.txt"
    fake_bin = tmp_path / "neurostack"
    fake_bin.write_text(_FAKE_BIN)
    fake_bin.chmod(0o755)
    adapter = _install_omp(isolated_home, binary=str(fake_bin))
    driver = tmp_path / "driver.ts"
    driver.write_text(_DRIVER.format(adapter=adapter, count=12))

    result = subprocess.run(
        [BUN, "run", str(driver)], capture_output=True, text=True, timeout=120,
        env={**os.environ, "NEUROSTACK_TEST_LOG": str(calls)},
    )
    assert result.returncode == 0, result.stderr
    assert "injected=0" in result.stdout
    # 12 messages is under the 40-message rule, so the CLI is never asked.
    assert "hook checkpoint" not in calls.read_text().splitlines()


def test_the_claude_stop_entry_hands_the_prompt_to_the_model():
    command = claude_hook_entries("/opt/bin/neurostack")["Stop"][0]["hooks"][0]["command"]
    assert "hook checkpoint --harness claude" in command
    # Only exit 2 reaches the model; exit 0 would show the prompt to the user.
    assert "exit 2" in command


def test_claude_install_writes_the_save_command(isolated_home):
    (isolated_home / ".claude").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        install_claude_adapter()
        install_claude_adapter()
    body = claude_save_command_path().read_text()
    assert "/opt/bin/neurostack hook checkpoint --harness claude" in body
    assert "hook checkpoint --save --harness claude" in body
