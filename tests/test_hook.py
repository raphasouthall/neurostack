# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for the harness-neutral hook CLI (issue #141).

Every server call goes to the fake MCP endpoint in `conftest.py`: the hook
must be provable without a live server, and the fake records what it was
asked so outcome reporting can be asserted.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from neurostack.adapters import (
    install_claude_adapter,
    install_omp_adapter,
    omp_extension_path,
)
from neurostack.cli.hook import _state_path, run_event
from neurostack.client import ClientConfig, McpClient, load_client_config

TRIGGER_HIT = {
    "memory_id": 2164,
    "content": "vault_write_file commits and pushes the vault",
    "trigger": "when-calling:vault_write_file",
}



@pytest.fixture(autouse=True)
def _throwaway_home(isolated_home):
    """Every test here writes state and adapters into a throwaway HOME."""
    return isolated_home


def _cfg(server, **kwargs):
    return ClientConfig(url=server.url, timeout_s=5.0, **kwargs)


def _dead_port() -> int:
    """A port nothing is listening on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tool_calls(server, name):
    return [args for called, args in server.calls if called == name]


def _triggers(mapping):
    """vault_triggers reply keyed by (event, value)."""
    def reply(args):
        return {"hits": mapping.get((args.get("event"), args.get("value")), [])}
    return reply


# ---------------------------------------------------------------------------
# Acceptance 1 — blocks once per session, through the real CLI
# ---------------------------------------------------------------------------

def _run_cli(payload, server_url, home, event="tool-call", extra_env=None):
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "NEUROSTACK_URL": server_url,
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "neurostack", "hook", event],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=120,
    )


def test_tool_call_blocks_once_then_allows(server, isolated_home):
    server.replies["vault_triggers"] = _triggers(
        {("calling", "vault_write_file"): [TRIGGER_HIT]}
    )
    payload = {"session": "s1", "tool": "vault_write_file", "paths": [], "input": {}}

    first = _run_cli(payload, server.url, isolated_home)
    assert first.returncode == 2
    assert "2164" in first.stdout

    second = _run_cli(payload, server.url, isolated_home)
    assert second.returncode == 0
    assert "2164" not in second.stdout


def test_state_file_lands_in_the_cache_dir(server, isolated_home):
    server.replies["vault_triggers"] = _triggers({})
    run_event("tool-call", {"session": "s-cache", "tool": "read"}, cfg=_cfg(server))
    path = _state_path("s-cache")
    assert path.exists()
    assert path.parent == Path(os.environ["XDG_CACHE_HOME"]) / "neurostack" / "sessions"
    assert json.loads(path.read_text())["calls"] == 1


def test_session_id_cannot_escape_the_state_dir():
    path = _state_path("../../etc/passwd")
    assert path.name == "______etc_passwd.json"
    assert path.parent.name == "sessions"


# ---------------------------------------------------------------------------
# Acceptance 2 — omp's xd:// device naming
# ---------------------------------------------------------------------------

def test_xd_device_name_matches_when_calling_tag(server):
    server.replies["vault_triggers"] = _triggers(
        {("calling", "vault_write_file"): [TRIGGER_HIT]}
    )
    verdict = run_event(
        "tool-call",
        {"session": "s2", "tool": "xd://mcp__neurostack_vault_write_file", "input": {}},
        cfg=_cfg(server),
    )
    assert verdict.block is True
    assert "memory 2164" in verdict.text
    assert [a["value"] for a in _tool_calls(server, "vault_triggers")] == ["vault_write_file"]


def test_write_to_an_xd_device_also_matches(server):
    server.replies["vault_triggers"] = _triggers(
        {("calling", "vault_write_file"): [TRIGGER_HIT]}
    )
    verdict = run_event(
        "tool-call",
        {"session": "s3", "tool": "write",
         "input": {"path": "xd://mcp__neurostack_vault_write_file", "content": "{}"}},
        cfg=_cfg(server),
    )
    assert verdict.block is True
    assert [a["value"] for a in _tool_calls(server, "vault_triggers")] == [
        "write", "vault_write_file",
    ]


def test_edited_paths_come_from_payload_and_edit_body(server):
    hit = {"memory_id": 91, "content": "bump the schema version too",
           "trigger": "when-editing:src/**/*.py"}
    server.replies["vault_triggers"] = _triggers({("editing", "src/neurostack/schema.py"): [hit]})
    verdict = run_event(
        "tool-call",
        {"session": "s4", "tool": "edit",
         "input": {"input": "[src/neurostack/schema.py#A1B2]\nPUT 1.=1:\n+x = 1\n"}},
        cfg=_cfg(server),
    )
    assert verdict.block is True
    assert "memory 91" in verdict.text


# ---------------------------------------------------------------------------
# Acceptance 3 — when-error hits, then the outcome after a quiet window
# ---------------------------------------------------------------------------

def test_error_trigger_then_followed_after_quiet_window(server):
    error_hit = {"memory_id": 1808, "content": "bastion is down, use the proxy chain",
                 "trigger": "when-error:connection refused"}
    error_text = "ssh: connect to host bastion port 22: connection refused"
    server.replies["vault_triggers"] = _triggers({("error", error_text): [error_hit]})

    verdict = run_event(
        "tool-result",
        {"session": "s5", "tool": "bash", "error": error_text},
        cfg=_cfg(server),
    )
    assert verdict.block is False
    assert "memory 1808" in verdict.text

    for i in range(5):
        run_event("tool-call", {"session": "s5", "tool": f"read-{i}"}, cfg=_cfg(server))
        outcomes = _tool_calls(server, "vault_trigger_outcome")
        assert len(outcomes) == (1 if i == 4 else 0), f"after {i + 1} calls"

    assert outcomes == [{"memory_id": 1808, "followed": True,
                         "note": "window elapsed without a repeat"}]
    assert json.loads(_state_path("s5").read_text())["pending"] == {}


def test_identical_reissue_reports_ignored(server):
    server.replies["vault_triggers"] = _triggers(
        {("calling", "vault_write_file"): [TRIGGER_HIT]}
    )
    call = {"session": "s6", "tool": "vault_write_file", "input": {"path": "a.md"}}
    assert run_event("tool-call", call, cfg=_cfg(server)).block is True
    run_event("tool-call", call, cfg=_cfg(server))
    assert _tool_calls(server, "vault_trigger_outcome") == [
        {"memory_id": 2164, "followed": False,
         "note": "re-issued vault_write_file unchanged"},
    ]


def test_recurring_error_reports_ignored(server):
    error_hit = {"memory_id": 55, "content": "port 1435, not 1433",
                 "trigger": "when-error:login failed"}
    text = "login failed for user sa"
    server.replies["vault_triggers"] = _triggers({("error", text): [error_hit]})
    run_event("tool-result", {"session": "s7", "error": text}, cfg=_cfg(server))
    run_event("tool-result", {"session": "s7", "error": text}, cfg=_cfg(server))
    assert _tool_calls(server, "vault_trigger_outcome") == [
        {"memory_id": 55, "followed": False, "note": "same error recurred"},
    ]


def test_successful_tool_result_asks_nothing(server):
    server.replies["vault_triggers"] = _triggers({})
    verdict = run_event(
        "tool-result",
        {"session": "s8", "tool": "read", "tool_response": {"content": "fine"}},
        cfg=_cfg(server),
    )
    assert verdict.text == ""
    assert server.calls == []


# ---------------------------------------------------------------------------
# Acceptance 4 — fallback, then fail open
# ---------------------------------------------------------------------------

def test_fallback_url_answers_when_primary_is_down(server):
    server.replies["session_brief"] = {"brief": "716 notes, 10190 chunks"}
    cfg = ClientConfig(url=f"http://127.0.0.1:{_dead_port()}/mcp",
                       fallback_url=server.url, timeout_s=5.0)
    verdict = run_event("session-start", {"session": "s9"}, cfg=cfg)
    assert "716 notes" in verdict.text


def test_both_urls_down_exits_zero_with_one_stderr_line(isolated_home):
    config = isolated_home / ".config" / "neurostack"
    config.mkdir(parents=True)
    (config / "client.toml").write_text(
        f'url = "http://127.0.0.1:{_dead_port()}/mcp"\n'
        f'fallback_url = "http://127.0.0.1:{_dead_port()}/mcp"\n'
        "timeout_s = 2\n"
    )
    started = time.monotonic()
    result = _run_cli({"session": "s10", "tool": "vault_write_file"}, "", isolated_home,
                      extra_env={"NEUROSTACK_URL": ""})
    elapsed = time.monotonic() - started
    assert result.returncode == 0
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "127.0.0.1" in result.stderr
    # The whole run, imports included, stays inside a couple of seconds of the
    # 2s budget: a dead primary must not spend a second budget on the fallback.
    assert elapsed < 6


def test_budget_is_shared_across_urls():
    cfg = ClientConfig(url=f"http://127.0.0.1:{_dead_port()}/mcp",
                       fallback_url=f"http://127.0.0.1:{_dead_port()}/mcp",
                       timeout_s=1.0)
    client = McpClient(cfg)
    started = time.monotonic()
    assert client.call("session_brief", {}) is None
    assert time.monotonic() - started < 1.5
    assert len(client.errors) == 2


def test_malformed_stdin_exits_zero(server, isolated_home):
    result = subprocess.run(
        [sys.executable, "-m", "neurostack", "hook", "tool-call"],
        input="not json", capture_output=True, text=True, timeout=120,
        env={**os.environ, "HOME": str(isolated_home),
             "XDG_CACHE_HOME": str(isolated_home / ".cache"),
             "NEUROSTACK_URL": server.url},
    )
    assert result.returncode == 0
    assert "not JSON" in result.stderr
    assert server.calls == []


# ---------------------------------------------------------------------------
# Acceptance 5 — generated adapters
# ---------------------------------------------------------------------------

def _find_bun() -> str | None:
    """Resolve bun before HOME is patched — the fixture moves it out of reach."""
    on_path = shutil.which("bun")
    if on_path:
        return on_path
    bundled = Path.home() / ".bun" / "bin" / "bun"
    return str(bundled) if bundled.exists() else None


BUN = _find_bun()


def test_omp_adapter_is_generated_without_an_address(isolated_home, tmp_path):
    (isolated_home / ".omp").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        status, path = install_omp_adapter()
    assert status == "installed"
    assert path == omp_extension_path()
    source = path.read_text()
    assert "/opt/bin/neurostack" in source
    assert "__NEUROSTACK_BIN__" not in source
    assert not any(part.replace(".", "").isdigit() and part.count(".") == 3
                   for part in source.split())
    # The adapter maps events and nothing more; every retrieval rule and the
    # whole checkpoint stay in the CLI. The ceiling rose once for the note on
    # what omp's message API cannot hide (issue #153).
    assert len(source.splitlines()) < 150


@pytest.mark.skipif(BUN is None, reason="bun not installed")
def test_omp_adapter_transpiles_under_bun(isolated_home, tmp_path):
    (isolated_home / ".omp").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        _status, path = install_omp_adapter()
    result = subprocess.run(
        [BUN, "build", str(path), "--target=bun", "--outfile", str(tmp_path / "out.js")],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out.js").exists()


def test_claude_adapter_writes_entries_that_invoke_the_hook(isolated_home):
    (isolated_home / ".claude").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        status, path = install_claude_adapter()
    assert status == "installed"
    hooks = json.loads(path.read_text())["hooks"]
    commands = {
        event: hooks[event][0]["hooks"][0]["command"]
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse",
                      "PostToolUse", "Stop", "SessionEnd")
    }
    assert commands["SessionStart"] == "/opt/bin/neurostack hook session-start --harness claude"
    assert commands["UserPromptSubmit"].endswith("hook prompt --harness claude")
    assert commands["PreToolUse"].endswith("hook tool-call --harness claude")
    assert commands["PostToolUse"].endswith("hook tool-result --harness claude")
    assert "hook session-end --harness claude" in commands["SessionEnd"]
    assert commands["SessionEnd"].startswith("nohup ")
    # The checkpoint summarises itself in the background now (issue #155).
    assert "hook checkpoint --run --harness claude" in commands["Stop"]
    assert commands["Stop"].startswith("nohup ")


# ---------------------------------------------------------------------------
# Acceptance 6 — the generated adapter replaces the hand-written clients
# ---------------------------------------------------------------------------

def test_claude_install_replaces_the_hand_written_hooks(isolated_home):
    settings = isolated_home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({
        "model": "opus",
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": "*", "hooks": [
                    {"type": "command", "command": "sh '/home/u/.claude/hooks/adhd.sh'"},
                    {"type": "command",
                     "command": "python3 '/home/u/.claude/hooks/neurostack-rag.py'"},
                ]},
            ],
            "SessionEnd": [
                {"hooks": [{"type": "command",
                            "command": "nohup python3 $HOME/scripts/"
                                       "neurostack-post-sessions.py --stdin-hook &"}]},
            ],
        },
    }))
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        install_claude_adapter()
    data = json.loads(settings.read_text())
    prompt_commands = [
        h["command"] for m in data["hooks"]["UserPromptSubmit"] for h in m["hooks"]
    ]
    assert "sh '/home/u/.claude/hooks/adhd.sh'" in prompt_commands
    assert not any("neurostack-rag.py" in c for c in prompt_commands)
    assert sum("neurostack hook" in c for c in prompt_commands) == 1
    session_end = [h["command"] for m in data["hooks"]["SessionEnd"] for h in m["hooks"]]
    assert not any("neurostack-post-sessions.py" in c for c in session_end)
    assert data["model"] == "opus"


def test_claude_install_is_idempotent(isolated_home):
    (isolated_home / ".claude").mkdir()
    with patch("neurostack.adapters._resolve_neurostack_binary",
               return_value="/opt/bin/neurostack"):
        install_claude_adapter()
        _status, path = install_claude_adapter()
    hooks = json.loads(path.read_text())["hooks"]
    assert [len(hooks[event]) for event in hooks] == [1, 1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Events: session-start, prompt, session-end
# ---------------------------------------------------------------------------

def test_session_start_prints_the_brief(server):
    server.replies["session_brief"] = {"brief": "## Session Brief\n\n716 notes"}
    verdict = run_event("session-start", {"session": "s11"}, cfg=_cfg(server))
    assert "716 notes" in verdict.text
    assert verdict.block is False


def test_session_start_clears_stale_state(server):
    server.replies["vault_triggers"] = _triggers(
        {("calling", "vault_write_file"): [TRIGGER_HIT]}
    )
    call = {"session": "s12", "tool": "vault_write_file", "input": {}}
    assert run_event("tool-call", call, cfg=_cfg(server)).block is True
    server.replies["session_brief"] = {"brief": "fresh"}
    run_event("session-start", {"session": "s12"}, cfg=_cfg(server))
    # A restarted session re-fires: nothing is remembered from the last run.
    assert run_event("tool-call", call, cfg=_cfg(server)).block is True


def test_prompt_injects_context_once_per_prompt(server):
    server.replies["vault_context"] = {"notes": ["a"], "text": "some context"}
    prompt = "How does the trigger outcome loop decide a memory was ignored?"
    payload = {"session": "s13", "prompt": prompt, "cwd": "/home/u/projects/neurostack"}
    first = run_event("prompt", payload, cfg=_cfg(server))
    assert "some context" in first.text
    assert run_event("prompt", payload, cfg=_cfg(server)).text == ""
    args = _tool_calls(server, "vault_context")[0]
    assert args["task"] == prompt
    assert args["token_budget"] == 1500
    assert args["context"] == "neurostack"


def test_prompt_skips_short_prompts_and_slash_commands(server):
    server.replies["vault_context"] = {"text": "context"}
    assert run_event("prompt", {"session": "s14", "prompt": "do it"}, cfg=_cfg(server)).text == ""
    assert run_event(
        "prompt",
        {"session": "s14", "prompt": "/handoff please write the handoff document now"},
        cfg=_cfg(server),
    ).text == ""
    assert server.calls == []


def test_workspace_map_scopes_the_lookup(server):
    server.replies["session_brief"] = {"brief": "scoped"}
    cfg = _cfg(server, workspace_map={"/home/u/projects/neurostack": "home/projects/neurostack"})
    run_event(
        "session-start",
        {"session": "s15", "workspace": "/home/u/projects/neurostack/src"},
        cfg=cfg,
    )
    assert _tool_calls(server, "session_brief") == [{"workspace": "home/projects/neurostack"}]


def test_session_end_posts_the_transcript(server, tmp_path):
    transcript = tmp_path / "abc123.jsonl"
    transcript.write_text('{"role":"user","content":"hi"}\n')
    server.replies["vault_harvest_transcript"] = {"messages": 1, "saved": [1], "skipped": []}
    verdict = run_event(
        "session-end",
        {"session": "abc123", "transcript_path": str(transcript), "format": "claude-code"},
        cfg=_cfg(server),
    )
    assert "messages=1" in verdict.text
    posted = _tool_calls(server, "vault_harvest_transcript")[0]
    assert posted["transcript"] == '{"role":"user","content":"hi"}\n'
    assert posted["session_id"] == "abc123"
    assert posted["source_agent"] == "claude-code"


def test_session_end_finds_an_omp_transcript_by_session_id(server, isolated_home):
    sessions = isolated_home / ".omp" / "agent" / "sessions" / "-projects-neurostack"
    sessions.mkdir(parents=True)
    (sessions / "20260907_sess-9.jsonl").write_text('{"role":"user"}\n')
    server.replies["vault_harvest_transcript"] = {"messages": 1, "saved": [], "skipped": []}
    verdict = run_event(
        "session-end", {"session": "sess-9", "format": "omp"}, cfg=_cfg(server),
    )
    assert "20260907_sess-9.jsonl" in verdict.text
    assert _tool_calls(server, "vault_harvest_transcript")[0]["source_agent"] == "omp"


def test_session_end_without_a_transcript_says_so(server, capsys):
    run_event("session-end", {"session": "nope", "format": "omp"}, cfg=_cfg(server))
    assert "no transcript found" in capsys.readouterr().err
    assert server.calls == []


# ---------------------------------------------------------------------------
# Client config
# ---------------------------------------------------------------------------

def test_client_config_defaults_to_localhost(isolated_home):
    cfg = load_client_config()
    assert cfg.url == "http://localhost:8001/mcp"
    assert cfg.timeout_s == 5.0
    assert cfg.fallback_url is None


def test_client_config_reads_toml_and_env_override(isolated_home, monkeypatch):
    path = isolated_home / "client.toml"
    path.write_text(
        'url = "http://server:8001/mcp"\n'
        'fallback_url = "http://backup:8001/mcp"\n'
        'token = "secret"\n'
        "timeout_s = 3\n"
        "[workspace_map]\n"
        '"~/projects/neurostack" = "home/projects/neurostack"\n'
    )
    cfg = load_client_config(path)
    assert cfg.fallback_url == "http://backup:8001/mcp"
    assert cfg.token == "secret"
    assert cfg.timeout_s == 3.0
    assert cfg.workspace_for(str(isolated_home / "projects/neurostack/src")) == (
        "home/projects/neurostack"
    )
    monkeypatch.setenv("NEUROSTACK_URL", "http://override:8001/mcp")
    assert load_client_config(path).url == "http://override:8001/mcp"


def test_token_is_sent_as_a_bearer_header(server):
    seen = {}

    def reply(args):
        seen["args"] = args
        return {"brief": "ok"}

    server.replies["session_brief"] = reply
    handler = server.RequestHandlerClass
    original = handler.do_POST

    def spy(self):
        seen.setdefault("auth", self.headers.get("authorization"))
        return original(self)

    handler.do_POST = spy
    try:
        run_event("session-start", {"session": "s16"}, cfg=_cfg(server, token="t0ken"))
    finally:
        handler.do_POST = original
    assert seen["auth"] == "Bearer t0ken"
