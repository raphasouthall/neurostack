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
from neurostack.cli.hook import (
    _state_path,
    _window_path,
    last_capture_path,
    load_state,
    run_checkpoint,
    run_checkpoint_save,
    run_event,
    sessions_dir,
)
from neurostack.cli.learn_status import load_learn_status, record_ok
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


def _write_window(session, messages, since_index=0):
    """The window file an adapter leaves behind before spawning `--run`."""
    path = _window_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"since_index": since_index, "messages": messages}))
    return path


def _windows():
    return sorted(sessions_dir().glob("*.window.json"))


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
    assert '"--run"' in source
    assert 'messages: seen.slice(submittedStart, submittedEnd)' in source
    assert " any" not in source and ": any" not in source


def test_the_omp_adapter_says_nothing_to_the_session_model(isolated_home):
    """Acceptance 6: no prompt goes in and no reply is watched for."""
    source = _install_omp(isolated_home).read_text()
    for gone in ("sendUserMessage", "message_end", "awaiting",
                 "MAX_REPLY_TRIES", "JSON_SHAPE"):
        assert gone not in source


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

const injected: string[] = [];
const shown: string[] = [];
const handlers: Record<string, (e: unknown, c: unknown) => unknown> = {{}};
const commands: Record<string, {{ handler: () => unknown }}> = {{}};
let intervalMs = 0;

extension({{
  on: (e, h) => {{ handlers[e] = h; }},
  sendMessage: (m: {{ content?: string }}) => {{ shown.push(m.content ?? ""); }},
  sendUserMessage: (t: string) => {{ injected.push(t); }},
  registerCommand: (n: string, c: {{ handler: () => unknown }}) => {{ commands[n] = c; }},
}} as never);

const ctx = {{
  sessionManager: {{ getSessionId: () => "conversation-stable-42" }},
  setInterval: (_f: () => void, ms: number) => {{ intervalMs = ms; }},
}};
await handlers.session_start?.({{}}, ctx);

const settle = () => new Promise((r) => setTimeout(r, 400));
const messages = Array.from({{ length: {count} }}, (_v, i) => ({{
  role: i % 2 === 0 ? "user" : "assistant",
  content: `message ${{i}}`,
}}));
await handlers.context?.({{ messages }}, ctx);
await settle();
{save}
{shutdown}
await settle();
console.log(JSON.stringify({{
  injected: injected.length, shown, timer: intervalMs,
  command: typeof commands.save?.handler,
}}));
"""

_FAKE_BIN = """\
#!/bin/sh
printf '%s\\n' "$*" >>"$NEUROSTACK_TEST_LOG"
cat >/dev/null
case "$*" in
  *session-start*) ;;
  *) printf 'neurostack: saved 1 of 1 checkpoint memories; settled through 40\\n' ;;
esac
"""


def _drive(isolated_home, tmp_path, count, save=False, shutdown=False):
    """Drive the generated extension under Bun with a stub `pi` and CLI."""
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    fake_bin = tmp_path / "neurostack"
    fake_bin.write_text(_FAKE_BIN)
    fake_bin.chmod(0o755)
    adapter = _install_omp(isolated_home, binary=str(fake_bin))
    driver = tmp_path / "driver.ts"
    driver.write_text(_DRIVER.format(
        adapter=adapter, count=count,
        save="await commands.save?.handler();" if save else "",
        shutdown="await handlers.session_shutdown?.({}, ctx);" if shutdown else "",
    ))
    result = subprocess.run(
        [BUN, "run", str(driver)], capture_output=True, text=True, timeout=120,
        env={**os.environ, "NEUROSTACK_TEST_LOG": str(calls)},
    )
    assert result.returncode == 0, result.stderr
    reported = json.loads(result.stdout.strip().splitlines()[-1])
    lines = calls.read_text().splitlines()
    spawned = [line for line in lines if line.startswith("hook checkpoint --run")]
    cursors = [line for line in lines if line == "hook checkpoint-cursor"]
    return reported, spawned, cursors


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_checkpoints_at_forty_messages(isolated_home, tmp_path):
    """Acceptance 1: the frozen window goes to the locked CLI over stdin."""
    reported, spawned, cursors = _drive(isolated_home, tmp_path, 40)
    assert reported["injected"] == 0
    assert reported["shown"] == []
    assert reported["timer"] == 60000
    assert spawned[0].endswith("--session conversation-stable-42")
    assert reported["command"] == "function"
    assert len(spawned) == 1
    assert cursors
    assert _windows() == []


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_leaves_a_short_window_alone(isolated_home, tmp_path):
    reported, spawned, cursors = _drive(isolated_home, tmp_path, 12)
    # 12 messages is under the 40-message rule, so the CLI is never asked.
    assert spawned == []
    assert cursors == ["hook checkpoint-cursor"]
    assert _windows() == []
    assert reported["shown"] == []


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_the_omp_adapter_checkpoints_on_shutdown_instead_of_posting_a_transcript(
    isolated_home, tmp_path,
):
    """Issue #174: shutdown checkpoints the pending window; no session-end poster."""
    reported, spawned, cursors = _drive(isolated_home, tmp_path, 12, shutdown=True)
    assert len(spawned) == 1
    assert spawned[0].endswith("--session conversation-stable-42")
    all_calls = (tmp_path / "calls.txt").read_text()
    assert "session-end" not in all_calls
    assert _windows() == []
    assert reported["shown"] == []


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_save_on_three_messages_spawns_nothing_and_says_so(isolated_home, tmp_path):
    """Acceptance 2: `/save` answers the user even when it saves nothing."""
    reported, spawned, cursors = _drive(isolated_home, tmp_path, 3, save=True)
    assert reported["shown"] == ["NeuroStack: nothing to save yet (3 messages)"]
    assert spawned == []
    assert cursors == ["hook checkpoint-cursor"]
    assert _windows() == []
    assert reported["injected"] == 0


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_save_on_a_worthwhile_window_starts_the_checkpoint(isolated_home, tmp_path):
    reported, spawned, cursors = _drive(isolated_home, tmp_path, 12, save=True)
    assert reported["shown"] == ["NeuroStack: checkpoint started in the background"]
    assert len(spawned) == 1
    assert len(cursors) == 2
    assert _windows() == []


def test_the_claude_stop_entry_checkpoints_in_the_background():
    """Acceptance 5: no exit-2 wrapper, and `--run` does the summarising."""
    stop = claude_hook_entries("/opt/bin/neurostack")["Stop"][0]["hooks"][0]
    assert "hook checkpoint --run --harness claude" in stop["command"]
    assert stop["command"].startswith("nohup ")
    assert stop["command"].endswith("&")
    assert "exit 2" not in stop["command"]
    # Nothing to wait for, so Claude Code is given no timeout to wait out.
    assert "timeout" not in stop


def test_claude_install_writes_the_save_command(isolated_home):
    (isolated_home / ".claude").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        install_claude_adapter()
        install_claude_adapter()
    body = claude_save_command_path().read_text()
    assert "/opt/bin/neurostack hook checkpoint --run --harness claude" in body
    # A slash command has no payload to pipe in and must not wait for one.
    assert "</dev/null" in body
    assert "--save" not in body


# --- checkpoint --run: pipe the prompt through checkpoint_command ------------


def test_run_pipes_the_prompt_through_the_command_and_saves(server, tmp_path):
    """`--run` = prompt, shell command on stdin, save whatever JSON comes back."""
    server.replies["vault_remember"] = {"saved": True, "memory_id": 3}
    seen = tmp_path / "prompt.txt"
    command = (f"{sys.executable} -c \"import sys,pathlib;"
               f"p=sys.stdin.read();pathlib.Path({str(seen)!r}).write_text(p);"
               "print('[{\\\"content\\\":\\\"fact\\\",\\\"tags\\\":[\\\"t\\\"]}]')\"")
    verdict = run_checkpoint(_payload(_messages(20)), "omp",
                             cfg=_cfg(server, checkpoint_command=command))
    assert "saved 1 of 1" in verdict.text
    assert "question 3 about the checkpoint window" in seen.read_text()
    assert _tool_calls(server, "vault_remember")[0]["source_agent"] == "checkpoint/omp"
    assert _state("ck")["since_index"] == 40


def test_run_with_a_failing_command_puts_the_window_back_on_offer(server, capsys):
    verdict = run_checkpoint(_payload(_messages(20)), "omp",
                             cfg=_cfg(server, checkpoint_command="exit 3"))
    # Nothing a `--run` says may reach stdout: a harness injects that.
    assert verdict.text == ""
    assert "command exited 3" in capsys.readouterr().err
    assert _tool_calls(server, "vault_remember") == []
    state = _state("ck")
    assert state["offered_index"] == state["since_index"] == 0


def test_run_without_a_command_says_so(server, capsys):
    """Acceptance 4: one stderr line, and the LEARN line shows the reason."""
    verdict = run_checkpoint(_payload(_messages(20)), "omp", cfg=_cfg(server))
    assert verdict.text == ""
    assert "no checkpoint_command" in capsys.readouterr().err
    assert "no checkpoint_command" in load_learn_status()["last_error"]
    assert _tool_calls(server, "vault_remember") == []


def test_run_refuses_an_outdated_omp_adapter_session(server, capsys):
    """A per-process `omp-<ts>-<pid>` id means the adapter predates #163: no
    lock, no receipts, so it re-saves the same window. Refuse and say why."""
    payload = {**_payload(_messages(20)), "session": "omp-mtsryxg2-437813"}
    verdict = run_checkpoint(payload, "omp", cfg=_cfg(server, checkpoint_command="cat"))
    assert verdict.text == ""
    assert "restart omp" in capsys.readouterr().err
    assert "outdated omp adapter" in load_learn_status()["last_error"]
    assert _tool_calls(server, "vault_remember") == []


def test_run_reads_legacy_window_once_and_leaves_file(server, tmp_path):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 4}
    window = _write_window("s1", _messages(20))
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps([{"content": "one fact"}, {"content": "another"}]))
    verdict = run_checkpoint({"session": "s1"}, "omp",
                             cfg=_cfg(server, checkpoint_command=f"cat {reply}"))
    assert "saved 2 of 2" in verdict.text
    assert window.exists()
    assert run_checkpoint({"session": "s1"}, "omp",
                          cfg=_cfg(server, checkpoint_command=f"cat {reply}")).text == ""
    assert len(_tool_calls(server, "vault_remember")) == 2


def test_a_window_that_saved_nothing_stays_on_disk(server, tmp_path):
    """A dropped reply must leave the window where the next `--run` finds it."""
    window = _write_window("s2", _messages(20))
    reply = tmp_path / "reply.txt"
    reply.write_text("Nothing worth keeping.")
    run_checkpoint({"session": "s2"}, "omp",
                   cfg=_cfg(server, checkpoint_command=f"cat {reply}"))
    assert window.exists()
    assert _state("s2")["offered_index"] == 0


def test_run_without_a_session_takes_the_newest_state_file(server, tmp_path):
    """`/save` cannot pass its own id; the state the Stop hook wrote can."""
    server.replies["vault_remember"] = {"saved": True, "memory_id": 6}
    load_state("s3").save()
    _write_window("s3", _messages(20))
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps([{"content": "a fact worth keeping"}]))
    verdict = run_checkpoint({}, "claude", cfg=_cfg(server, checkpoint_command=f"cat {reply}"))
    assert "saved 1 of 1" in verdict.text
    assert load_learn_status()["session"] == "s3"


def test_cli_checkpoints_legacy_window_once(server, isolated_home, tmp_path):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 7}
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps([{"content": "a fact worth keeping"}]))
    config = isolated_home / ".config" / "neurostack" / "client.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(f'checkpoint_command = "cat {reply}"\n')
    window = _write_window("omp-cli", _messages(20))
    result = _run_cli(["checkpoint", "--run", "--harness", "omp", "--session", "omp-cli"],
                      "", server.url, isolated_home)
    assert result.returncode == 0
    assert "saved 1 of 1" in result.stdout
    assert window.exists()
    again = _run_cli(["checkpoint", "--run", "--harness", "omp", "--session", "omp-cli"],
                     "", server.url, isolated_home)
    assert again.stdout == ""
    assert len(_tool_calls(server, "vault_remember")) == 1


def test_run_executes_the_command_from_home_not_the_project(server):
    """A project's own agent instructions must not shape the extraction."""
    seen = Path.home() / "cwd.txt"
    command = f"pwd > {seen}; echo '[]'"
    run_checkpoint(_payload(_messages(20)), "cli",
                   cfg=_cfg(server, checkpoint_command=command))
    assert seen.read_text().strip() == str(Path.home())


def test_assistant_text_goes_in_whole(server):
    """Decisions and corrections live in the assistant's prose too."""
    long_answer = "decision " * 300  # 2700 chars, past the tool-output clip
    messages = _messages(10) + [
        {"role": "user", "content": "what did we decide about the schema?"},
        {"role": "assistant", "content": long_answer},
    ]
    verdict = run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    assert long_answer.strip() in verdict.text


# ---------------------------------------------------------------------------
# Issue #153 — a save never loses the reply the model already wrote
# ---------------------------------------------------------------------------

def test_a_slow_server_still_saves_on_the_harvest_budget(server):
    """Every memory is embedded server-side, which outlasts the tool timeout."""
    server.delay_s = 0.6
    server.replies["vault_remember"] = {"saved": True, "memory_id": 9}
    cfg = ClientConfig(url=server.url, timeout_s=0.2, harvest_timeout_s=60.0)
    verdict = run_checkpoint_save(REPLY, "ck", "omp", cfg=cfg)
    assert "saved 2 of 2" in verdict.text
    assert len(_tool_calls(server, "vault_remember")) == 2


def test_the_interactive_budget_would_have_lost_the_same_save(server):
    """What the harvest budget buys: the 5 s tool timeout drops both memories."""
    server.delay_s = 0.6
    server.replies["vault_remember"] = {"saved": True, "memory_id": 9}
    cfg = ClientConfig(url=server.url, timeout_s=0.2, harvest_timeout_s=0.2)
    verdict = run_checkpoint_save(REPLY, "ck", "omp", cfg=cfg)
    assert "saved 0 of 2" in verdict.text


def test_prose_records_an_error_and_re_offers_the_window(server):
    messages = _messages(20)
    run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    verdict = run_checkpoint_save("Nothing new here.", "ck", "omp", cfg=_cfg(server))
    assert server.calls == []
    assert "no items" in verdict.text
    state = _state("ck")
    assert state["since_index"] == 0
    assert state["offered_index"] == 0
    assert "no items" in load_learn_status()["last_error"]
    # The window comes back rather than dying with the dropped reply.
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text != ""


def test_a_literal_empty_array_settles_the_window_as_ok(server):
    """`[]` is the model saying nothing here is worth keeping."""
    record_ok("ck", "omp", 3)
    run_event("checkpoint", _payload(_messages(20)), cfg=_cfg(server))
    verdict = run_checkpoint_save("[]", "ck", "omp", cfg=_cfg(server))
    assert "saved 0 of 0" in verdict.text
    assert _state("ck")["since_index"] == 40
    status = load_learn_status()
    assert status["last_error"] is None
    assert status["saved_today"] == 3


def test_an_empty_body_keeps_the_window_without_an_error(server):
    """The adapter sends an empty body when the answer never came."""
    messages = _messages(20)
    run_event("checkpoint", _payload(messages), cfg=_cfg(server))
    verdict = run_checkpoint_save("", "ck", "omp", cfg=_cfg(server))
    assert "saved 0 of 0" in verdict.text
    state = _state("ck")
    assert state["since_index"] == 0
    assert state["offered_index"] == 0
    assert load_learn_status()["last_error"] is None
    assert run_event("checkpoint", _payload(messages), cfg=_cfg(server)).text != ""


def test_every_save_writes_the_reply_to_the_capture_file(server):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 10}
    for reply in (REPLY, "Nothing new here.", ""):
        run_checkpoint_save(reply, "ck", "omp", cfg=_cfg(server))
        assert last_capture_path().read_text(encoding="utf-8") == reply


def test_the_capture_file_holds_the_bytes_the_cli_read(server, isolated_home):
    server.replies["vault_remember"] = {"saved": True, "memory_id": 11}
    _run_cli(["checkpoint", "--session", "cap-1"],
             json.dumps({"messages": _messages(20), "since_index": 0}),
             server.url, isolated_home)
    saved = _run_cli(["checkpoint", "--save"], REPLY, server.url, isolated_home)
    assert saved.returncode == 0
    assert last_capture_path().read_bytes() == REPLY.encode()


def test_partial_retry_skips_acknowledged_item(server):
    run_event("checkpoint", _payload(_messages(20)), cfg=_cfg(server))
    calls = 0
    def reply(_args):
        nonlocal calls
        calls += 1
        return {"memory_id": calls} if calls != 2 else None
    server.replies["vault_remember"] = reply
    run_checkpoint_save(REPLY, "ck", "omp", cfg=_cfg(server))
    server.replies["vault_remember"] = {"memory_id": 3}
    retried = run_checkpoint_save("[]", "ck", "omp", cfg=_cfg(server))
    assert "skipped 1 acknowledged" in retried.text
    assert len(_tool_calls(server, "vault_remember")) == 3
    assert _state("ck")["since_index"] == 40


def test_exact_receipts_keep_a_corrected_fact(server):
    server.replies["vault_remember"] = {"memory_id": 1}
    run_event("checkpoint", _payload(_messages(20), session="receipt"), cfg=_cfg(server))
    run_checkpoint_save('[{"content":"service uses port 1433"}]', "receipt", cfg=_cfg(server))
    run_event("checkpoint", _payload(_messages(25), session="receipt"), cfg=_cfg(server))
    run_checkpoint_save('[{"content":"service uses port 1435"}]', "receipt", cfg=_cfg(server))
    assert [call["content"] for call in _tool_calls(server, "vault_remember")] == [
        "service uses port 1433", "service uses port 1435"]


def test_newer_window_survives_old_completion(server):
    server.replies["vault_remember"] = {"memory_id": 1}
    old = _messages(20)
    run_event("checkpoint", _payload(old, session="race"), cfg=_cfg(server))
    _write_window("race", old + _messages(5))
    run_checkpoint_save('[{"content":"old window fact"}]', "race", cfg=_cfg(server))
    assert _window_path("race").exists()
    assert _state("race")["since_index"] == 40


def test_ordinary_hook_write_preserves_checkpoint_progress(server):
    server.replies["vault_remember"] = {"memory_id": 1}
    run_event("checkpoint", _payload(_messages(20), session="merge"), cfg=_cfg(server))
    stale = load_state("merge")
    run_checkpoint_save('[{"content":"saved fact"}]', "merge", cfg=_cfg(server))
    stale.calls += 1
    stale.save()
    assert load_state("merge").since_index == 40


def test_same_session_busy_while_other_session_runs(isolated_home):
    import fcntl

    from neurostack.cli.hook import _lock_path
    lock = _lock_path("held")
    lock.parent.mkdir(parents=True, exist_ok=True)
    cfg = ClientConfig(url="http://127.0.0.1:1/mcp", checkpoint_command="exit 9")
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        busy = run_checkpoint({"session": "held"}, cfg=cfg)
        other = run_checkpoint({"session": "other"}, cfg=cfg)
    assert "already running" in busy.text
    assert other.text == ""


def test_stale_lock_filename_does_not_block_recovery(server):
    from neurostack.cli.hook import _lock_path
    lock = _lock_path("stale")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("dead process")
    verdict = run_checkpoint(_payload(_messages(20), session="stale"), cfg=_cfg(
        server, checkpoint_command=f"{sys.executable} -c \"print('[]')\""))
    assert "skipped 0" in verdict.text


def test_checkpoint_save_does_not_resurrect_settled_trigger(server):
    state = load_state("trigger-race")
    state.pending[7] = {"kind": "calling", "remaining": 1}
    state.save()
    checkpoint = load_state("trigger-race")
    latest = load_state("trigger-race")
    latest.pending.pop(7)
    latest.save()
    checkpoint.checkpoint_end = 4
    checkpoint.save(checkpoint=True)
    assert load_state("trigger-race").pending == {}


def test_frozen_payload_survives_abandoned_runner(server):
    state = load_state("frozen")
    normalized = [m for m in (_messages(20))]
    run_event("checkpoint", _payload(normalized, session="frozen"), cfg=_cfg(server))
    state = load_state("frozen")
    assert len(state.checkpoint_messages) == 40
    state.offered_index = state.checkpoint_end
    state.save(checkpoint=True)
    server.replies["vault_remember"] = {"memory_id": 1}
    command = f"{sys.executable} -c \"print('[]')\""
    run_checkpoint({"session": "frozen"}, cfg=_cfg(server, checkpoint_command=command))
    assert load_state("frozen").since_index == 40


def test_checkpoint_state_with_transcript_is_owner_only(server):
    run_event("checkpoint", _payload(_messages(20), session="private"), cfg=_cfg(server))
    assert _state_path("private").stat().st_mode & 0o777 == 0o600


def test_success_clears_reply_and_accepts_distinct_next_save(server):
    server.replies["vault_remember"] = {"memory_id": 1}
    run_event("checkpoint", _payload(_messages(20), session="next"), cfg=_cfg(server))
    run_checkpoint_save('[{"content":"first fact"}]', "next", cfg=_cfg(server))
    assert load_state("next").checkpoint_reply == ""
    run_event("checkpoint", _payload(_messages(25), session="next"), cfg=_cfg(server))
    run_checkpoint_save('[{"content":"second corrected fact"}]', "next", cfg=_cfg(server))
    assert [call["content"] for call in _tool_calls(server, "vault_remember")] == [
        "first fact", "second corrected fact"]
