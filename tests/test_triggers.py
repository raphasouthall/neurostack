# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for trigger tags (issue #131)."""

import json

import pytest

from neurostack import config as nsconfig
from neurostack.triggers import match_triggers, parse_trigger


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _add_memory(conn, content, tags=None, workspace=None, expires_at=None):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, tags, workspace, expires_at)"
        " VALUES (?, 'learning', ?, ?, ?)",
        (content, json.dumps(tags) if tags is not None else None, workspace, expires_at),
    )
    conn.commit()
    return cur.lastrowid


def test_parse_trigger_accepts_three_prefixes_only():
    assert parse_trigger("when-editing:src/**/*.ts") == ("editing", "src/**/*.ts")
    assert parse_trigger("when-calling:vault_write_file") == ("calling", "vault_write_file")
    assert parse_trigger("when-error:bastion-unavailable") == ("error", "bastion-unavailable")
    # Non-goal and malformed shapes are plain tags.
    assert parse_trigger("when-writing:loop-with-bound") is None
    assert parse_trigger("when-editing:") is None
    assert parse_trigger("when-editing") is None
    assert parse_trigger("promotion-debt") is None
    assert parse_trigger(None) is None


def test_editing_glob_matches_absolute_path(db):
    mid = _add_memory(db, "never bump row_version server-side",
                      tags=["when-editing:strake/src/**/*.ts"])
    hits = match_triggers(db, "editing", "/home/r/strake/src/svc/vessel.ts")
    assert [h["memory_id"] for h in hits] == [mid]
    assert hits[0]["trigger"] == "when-editing:strake/src/**/*.ts"
    assert match_triggers(db, "editing", "/home/r/strake/test/vessel.test.ts") == []
    assert match_triggers(db, "editing", "/home/r/other/src/x.ts") == []


def test_calling_matches_tool_name_case_insensitive(db):
    mid = _add_memory(db, "vault_write_file commits and pushes",
                      tags=["when-calling:vault_write_file"])
    assert [h["memory_id"] for h in match_triggers(db, "calling", "Vault_Write_File")] == [mid]
    assert match_triggers(db, "calling", "vault_read_file") == []


def test_error_matches_substring_of_error_text(db):
    mid = _add_memory(db, "use ssh-proxy-chain when bastion is down",
                      tags=["when-error:bastion-unavailable"])
    text = "az network bastion ssh: ERROR Bastion-Unavailable (503) retry later"
    assert [h["memory_id"] for h in match_triggers(db, "error", text)] == [mid]
    assert match_triggers(db, "error", "connection refused") == []


def test_untagged_expired_and_wrong_event_are_ignored(db):
    _add_memory(db, "plain memory mentioning when-calling:x in content", tags=None)
    _add_memory(db, "plain tags", tags=["notes", "when-writing:loop"])
    _add_memory(db, "expired trigger", tags=["when-calling:x"],
                expires_at="2000-01-01T00:00:00+00:00")
    _add_memory(db, "other event", tags=["when-editing:x"])
    assert match_triggers(db, "calling", "x") == []
    assert match_triggers(db, "bogus", "x") == []
    assert match_triggers(db, "calling", "") == []


def test_workspace_scope_and_limit(db):
    a = _add_memory(db, "a", tags=["when-calling:t"], workspace="home/projects/neurostack")
    b = _add_memory(db, "b", tags=["when-calling:t"], workspace="work/other")
    hits = match_triggers(db, "calling", "t", workspace="home/projects")
    assert [h["memory_id"] for h in hits] == [a]
    assert len(match_triggers(db, "calling", "t")) == 2
    assert len(match_triggers(db, "calling", "t", limit=1)) == 1
    assert b  # created


def test_vault_remember_stores_trigger_tags_verbatim(db):
    from neurostack.memories import save_memory

    m = save_memory(db, content="trigger via public path",
                    tags=["when-calling:vault_write_file", "when-bogus:x"])
    row = db.execute("SELECT tags FROM memories WHERE memory_id = ?", (m.memory_id,)).fetchone()
    tags = json.loads(row["tags"])
    assert "when-calling:vault_write_file" in tags
    assert "when-bogus:x" in tags
    hits = match_triggers(db, "calling", "vault_write_file")
    assert [h["memory_id"] for h in hits] == [m.memory_id]


@pytest.mark.parametrize("tag", [
    "when-calling:Bash", "when-calling:read", "when-calling:vault_search",
    "when-error:404", "when-error:traceback (most recent call last):",
    "when-error:error", "when-editing:*", "when-editing:**/*",
])
def test_is_broad_trigger_rejects_catch_alls(tag):
    from neurostack.triggers import is_broad_trigger
    assert is_broad_trigger(tag)


@pytest.mark.parametrize("tag", [
    "when-calling:az rest", "when-calling:vault_write_file",
    "when-error:OAuth session expired", "when-editing:*.drawio",
    "when-editing:models.yml", "plain-tag", "when-writing:x",
])
def test_is_broad_trigger_keeps_specific_and_non_triggers(tag):
    from neurostack.triggers import is_broad_trigger
    assert not is_broad_trigger(tag)


def test_remember_args_drops_broad_triggers_from_field_and_tags():
    from neurostack.cli.hook import _remember_args
    item = {"content": "x", "tags": ["azure", "when-calling:Bash"],
            "trigger": "when-error:404"}
    assert _remember_args(item, "omp", None)["tags"] == ["azure"]
    item = {"content": "x", "tags": ["azure"], "trigger": "when-calling:az rest"}
    assert _remember_args(item, "omp", None)["tags"] == ["azure", "when-calling:az rest"]


def test_remember_args_coerces_unknown_entity_type():
    from neurostack.cli.hook import _remember_args
    made_up = {"content": "x", "entity_type": "correction"}
    assert _remember_args(made_up, "omp", None)["entity_type"] == "observation"
    real = {"content": "x", "entity_type": "bug"}
    assert _remember_args(real, "omp", None)["entity_type"] == "bug"


def test_calling_command_trigger_matches_the_command_line(db):
    mid = _add_memory(db, "az rest needs --uri with an api-version",
                      tags=["when-calling:az rest"])
    hits = match_triggers(db, "calling", "az rest --method get --uri /subscriptions")
    assert [h["memory_id"] for h in hits] == [mid]
    # A different command, and the bare shell tool, stay quiet.
    assert match_triggers(db, "calling", "az network watcher show") == []
    assert match_triggers(db, "calling", "bash") == []


def test_calling_matches_across_mcp_name_spellings(db):
    mid = _add_memory(db, "vault_write_file commits and pushes",
                      tags=["when-calling:mcp__neurostack__vault_write_file"])
    for spelling in ("vault_write_file", "mcp__neurostack__vault_write_file",
                     "neurostack_vault_write_file"):
        assert [h["memory_id"] for h in match_triggers(db, "calling", spelling)] == [mid]
    assert match_triggers(db, "calling", "vault_delete_file") == []


def test_is_broad_trigger_sees_through_mcp_prefixes():
    from neurostack.triggers import is_broad_trigger
    assert is_broad_trigger("when-calling:mcp__neurostack__vault_read_file")
    assert is_broad_trigger("when-calling:neurostack_vault_search")
    assert not is_broad_trigger("when-calling:mcp__neurostack__vault_write_file")


def test_edited_paths_drop_read_selectors_and_split_lists():
    from neurostack.cli.hook import _edited_paths
    assert _edited_paths({}, "read", {"path": "diagrams/a.png?q=is it clear"}) == [
        "diagrams/a.png"]
    assert _edited_paths({}, "read", {"path": "src/hook.py:335-360"}) == ["src/hook.py"]
    assert _edited_paths({}, "grep", {"path": "src/a.py;tests/b.py"}) == [
        "src/a.py", "tests/b.py"]
    assert _edited_paths({}, "write", {"path": "xd://lsp"}) == []


def test_editing_glob_matches_a_path_carrying_a_selector(db):
    mid = _add_memory(db, "Helvetica on every cell",
                      tags=["when-editing:*.drawio"])
    from neurostack.cli.hook import _edited_paths
    (path,) = _edited_paths({}, "read", {"path": "diagrams/knowledge.drawio:raw"})
    assert [h["memory_id"] for h in match_triggers(db, "editing", path)] == [mid]


def test_tool_names_include_the_shell_command():
    from neurostack.cli.hook import _tool_names
    assert _tool_names("bash", {"command": " az rest --uri /x "}) == [
        "bash", "az rest --uri /x"]
    assert _tool_names("write", {"path": "xd://mcp__neurostack__vault_remember"}) == [
        "write", "vault_remember"]
