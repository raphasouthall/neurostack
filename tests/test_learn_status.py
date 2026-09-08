# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for LEARN visibility (issue #151).

The checkpoint writes memories where nobody looks, so every attempt leaves a
health file behind and the session brief and `neurostack status` read it back.
What is worth proving here is the file after each kind of attempt, the four
states of the line, and that the line still prints when the server is dead —
all against the fake MCP endpoint in `conftest.py`.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from neurostack.cli.hook import (
    _state_path,
    load_state,
    run_checkpoint,
    run_checkpoint_save,
    run_event,
    sessions_behind,
)
from neurostack.cli.learn_status import (
    learn_line,
    learn_status_path,
    load_learn_status,
)
from neurostack.client import ClientConfig

TWO_ITEMS = json.dumps([
    {"content": "the checkpoint writes learn-status.json after every attempt"},
    {"content": "the brief prints the LEARN line before anything else"},
])


@pytest.fixture(autouse=True)
def _throwaway_home(isolated_home):
    """Every test here writes a health file into a throwaway HOME."""
    return isolated_home


def _cfg(server, **kwargs):
    return ClientConfig(url=server.url, timeout_s=5.0, **kwargs)


def _messages(turns: int) -> list[dict]:
    """A window the checkpoint will not skip: tool calls and real user text."""
    out: list[dict] = []
    for i in range(turns):
        out.append({"role": "user", "content": f"question {i} about the window"})
        out.append({"role": "assistant", "content": [
            {"type": "text", "text": f"answer {i}"},
            {"type": "tool_use", "name": f"tool_{i}", "input": {}},
        ]})
    return out


def _save_two(server, session="s-learn", harness="omp"):
    server.replies["vault_remember"] = {"memory_id": 4242}
    return run_checkpoint_save(TWO_ITEMS, session, harness, cfg=_cfg(server))


def _fail_run(server, session="s-learn", harness="omp"):
    return run_checkpoint(
        {"session": session, "messages": _messages(4)},
        harness, cfg=_cfg(server, checkpoint_command="exit 3"),
    )


# ---------------------------------------------------------------------------
# Acceptance 1 — a save that reached the server
# ---------------------------------------------------------------------------

def test_save_records_two_memories_and_no_error(server):
    _save_two(server)

    status = json.loads(learn_status_path().read_text())
    assert status["last_ok_at"]
    assert status["saved_today"] == 2
    assert status["last_error"] is None
    assert status["session"] == "s-learn"
    assert status["harness"] == "omp"


def test_saves_accumulate_within_the_day(server):
    _save_two(server)
    _save_two(server)

    assert load_learn_status()["saved_today"] == 4


def test_a_count_from_yesterday_is_not_reported_as_today(server):
    _save_two(server)
    status = load_learn_status()
    yesterday = datetime.now().astimezone() - timedelta(days=1)
    status["last_ok_at"] = yesterday.isoformat(timespec="seconds")
    learn_status_path().write_text(json.dumps(status))

    _save_two(server)

    assert load_learn_status()["saved_today"] == 2


def test_an_unreachable_server_is_recorded_as_a_failure(server):
    server.replies["vault_remember"] = {"memory_id": 1}
    dead = ClientConfig(url="http://127.0.0.1:1/mcp", timeout_s=0.5)

    run_checkpoint_save(TWO_ITEMS, "s-dead", "cli", cfg=dead)

    status = load_learn_status()
    assert status["last_error"]
    assert status["last_ok_at"] is None


# ---------------------------------------------------------------------------
# Acceptance 2 — a `--run` whose command fails
# ---------------------------------------------------------------------------

def test_failed_run_records_the_exit_code_and_keeps_last_ok(server):
    _save_two(server)
    ok_at = load_learn_status()["last_ok_at"]

    _fail_run(server)

    status = load_learn_status()
    assert "exited 3" in status["last_error"]
    assert status["last_ok_at"] == ok_at
    assert status["saved_today"] == 2


def test_a_missing_checkpoint_command_is_a_failure(server):
    run_checkpoint({"session": "s-nocmd", "messages": _messages(4)},
                   "cli", cfg=_cfg(server))

    assert "no checkpoint_command" in load_learn_status()["last_error"]


def test_the_error_line_is_one_line_of_at_most_200_chars(server):
    noisy = f"{sys.executable} -c \"import sys; sys.stderr.write('e' * 500); raise SystemExit(1)\""
    run_checkpoint(
        {"session": "s-long", "messages": _messages(4)},
        "cli", cfg=_cfg(server, checkpoint_command=noisy),
    )
    error = load_learn_status()["last_error"]

    assert "\n" not in error
    assert len(error) <= 200


# ---------------------------------------------------------------------------
# Acceptance 3 — the brief leads with the line
# ---------------------------------------------------------------------------

def _brief(server, text="recent vault changes"):
    server.replies["session_brief"] = {"brief": text}
    return run_event("session-start", {"session": "s-brief"}, cfg=_cfg(server)).text


def test_session_start_leads_with_ok_then_the_brief(server):
    _save_two(server)

    text = _brief(server)

    assert text.startswith("LEARN: ok, 2 memories today, last ")
    assert "recent vault changes" in text


def test_session_start_leads_with_failing_after_a_failed_run(server):
    _save_two(server)
    _fail_run(server)

    text = _brief(server)

    assert text.startswith("LEARN: FAILING since ")
    assert "exited 3" in text.splitlines()[0]


# ---------------------------------------------------------------------------
# Acceptance 4 — the states that need no attempt at all
# ---------------------------------------------------------------------------

def test_session_start_says_never_ran_without_a_health_file(server):
    assert not learn_status_path().exists()

    assert _brief(server).startswith("LEARN: never ran")


def test_an_old_success_with_no_error_reads_stale(server):
    three_days_ago = datetime.now().astimezone() - timedelta(days=3)
    learn_status_path().parent.mkdir(parents=True, exist_ok=True)
    learn_status_path().write_text(json.dumps({
        "last_ok_at": three_days_ago.isoformat(timespec="seconds"),
        "last_error": None, "saved_today": 5,
    }))

    text = _brief(server)

    assert text.startswith("LEARN: stale, no checkpoint since ")
    assert three_days_ago.strftime("%Y-%m-%d") in text.splitlines()[0]


def test_a_success_just_inside_the_window_is_still_ok():
    fresh = datetime.now().astimezone() - timedelta(hours=47)
    line = learn_line({"last_ok_at": fresh.isoformat(timespec="seconds"),
                       "saved_today": 3})

    assert line == f"LEARN: ok, 0 memories today, last {fresh.strftime('%H:%M')}"


# ---------------------------------------------------------------------------
# Acceptance 5 — a dead server still prints the line, through the real CLI
# ---------------------------------------------------------------------------

def test_session_start_prints_the_line_with_both_urls_dead(server, isolated_home):
    _save_two(server)
    config = isolated_home / ".config" / "neurostack"
    config.mkdir(parents=True)
    # Top level, not inside a table: a key written after a [section] header
    # would be read as part of that section.
    (config / "client.toml").write_text(
        'url = "http://127.0.0.1:1/mcp"\n'
        'fallback_url = "http://127.0.0.1:2/mcp"\n'
        "timeout_s = 1.0\n"
    )

    proc = _run_cli("session-start", {"session": "s-dead"}, isolated_home)

    assert proc.returncode == 0
    assert proc.stdout.startswith("LEARN: ok, 2 memories today, last ")


def _run_cli(event, payload, home, extra_env=None):
    env = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home.parent / "cache")}
    env.pop("NEUROSTACK_URL", None)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-m", "neurostack", "hook", event],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=120,
    )


# ---------------------------------------------------------------------------
# Acceptance 6 — the LEARN block in `neurostack status`
# ---------------------------------------------------------------------------

def test_status_prints_the_line_and_a_row_per_source(server, isolated_home):
    _save_two(server)
    server.replies["vault_stats"] = {"memories": {"total": 9, "by_source_7d": {
        "checkpoint/omp": 7, "checkpoint/claude": 2, "harvest/claude-code": 4,
    }}}

    proc = _run_status(isolated_home, server.url)

    assert proc.returncode == 0
    assert "LEARN: ok, 2 memories today, last " in proc.stdout
    assert "checkpoint/omp        7" in proc.stdout
    assert "harvest/claude-code   4" in proc.stdout
    assert "checkpoint/claude     2" in proc.stdout
    assert "Sessions behind: 0" in proc.stdout


def test_status_says_so_when_the_server_has_no_counts(server, isolated_home):
    server.replies["vault_stats"] = {"memories": {"total": 9}}

    proc = _run_status(isolated_home, server.url)

    assert "unavailable" in proc.stdout
    assert "issue #151" in proc.stdout


def test_status_json_carries_the_learn_block(server, isolated_home):
    _save_two(server)
    server.replies["vault_stats"] = {"memories": {"by_source_7d": {"checkpoint/cli": 3}}}

    proc = _run_status(isolated_home, server.url, "--json")
    learn = json.loads(proc.stdout)["learn"]

    assert learn["by_source"] == {"checkpoint/cli": 3}
    assert learn["sessions_behind"] == 0
    assert learn["error"] is None
    assert learn["warn"] is None


# ---------------------------------------------------------------------------
# The WARN line — did the trigger warnings change anything (issue #159)
# ---------------------------------------------------------------------------

def test_status_prints_the_warn_line_from_the_server(server, isolated_home):
    server.replies["vault_stats"] = {
        "memories": {"by_source_7d": {"checkpoint/omp": 2}},
        "triggers": {"last_30d": {"days": 30, "fired": 7, "followed": 4,
                                  "ignored": 2, "pending": 1,
                                  "followed_rate": 4 / 6}},
    }

    proc = _run_status(isolated_home, server.url)

    assert proc.returncode == 0
    assert "WARN: 7 fired, 4 followed, 2 ignored (30d)" in proc.stdout


def test_status_says_so_when_the_server_has_no_trigger_counts(server, isolated_home):
    server.replies["vault_stats"] = {"memories": {"by_source_7d": {"checkpoint/omp": 2}}}

    proc = _run_status(isolated_home, server.url)

    assert "WARN: unavailable (the server predates issue #159)" in proc.stdout


def test_status_json_carries_the_warn_counts(server, isolated_home):
    server.replies["vault_stats"] = {
        "memories": {"by_source_7d": {"checkpoint/cli": 3}},
        "triggers": {"last_30d": {"days": 7, "fired": 3, "followed": 1,
                                  "ignored": 1, "pending": 1}},
    }

    proc = _run_status(isolated_home, server.url, "--json")

    assert json.loads(proc.stdout)["learn"]["warn"] == {
        "days": 7, "fired": 3, "followed": 1, "ignored": 1, "pending": 1,
    }


def _run_status(home, url, *flags):
    env = {**os.environ, "HOME": str(home), "XDG_CACHE_HOME": str(home.parent / "cache"),
           "NEUROSTACK_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "neurostack", *flags, "status"],
        capture_output=True, text=True, env=env, timeout=120,
    )


# ---------------------------------------------------------------------------
# Sessions behind — the backlog the LEARN line alone cannot show
# ---------------------------------------------------------------------------

def _transcript(home, session: str, messages: int) -> None:
    path = home / ".claude" / "projects" / "proj" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(
        json.dumps({"type": "user", "message": {"role": "user", "content": f"turn {i}"}})
        for i in range(messages)
    ))


def test_a_session_whose_transcript_outran_the_offer_counts_as_behind(isolated_home):
    _transcript(isolated_home, "s-behind", 6)
    state = load_state("s-behind")
    state.offered_index = 2
    state.save()

    assert sessions_behind() == 1


def test_a_session_the_model_has_seen_is_not_behind(isolated_home):
    _transcript(isolated_home, "s-caught-up", 6)
    state = load_state("s-caught-up")
    state.offered_index = 6
    state.save()

    assert sessions_behind() == 0


def test_a_state_file_older_than_a_week_is_not_counted(isolated_home):
    _transcript(isolated_home, "s-old", 6)
    state = load_state("s-old")
    state.offered_index = 0
    state.save()
    old = _state_path("s-old")
    stale = os.stat(old).st_mtime - 8 * 86400
    os.utime(old, (stale, stale))

    assert sessions_behind() == 0
