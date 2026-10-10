# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""vault_memories reply budget (issue #322)."""

import pytest

from neurostack import config as nsconfig


@pytest.fixture
def db(tmp_path, monkeypatch):
    # Default DB path so registry tools (which open get_db(DB_PATH)) share the file.
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    # Twenty memories of ~400 chars, about 2,000 tokens with their JSON keys.
    conn.executemany(
        "INSERT INTO memories (content, tags) VALUES (?, '[]')",
        [(f"memory {i} " + "x" * 400,) for i in range(20)],
    )
    conn.commit()
    yield conn
    conn.close()
    nsconfig._config = None


def test_default_budget_drops_the_tail_and_says_so(db):
    from neurostack.tools.memory_tools import vault_memories

    reply = vault_memories()

    assert 0 < len(reply["memories"]) < 20
    assert reply["truncated"] is True


def test_explicit_max_tokens_wins(db):
    from neurostack.tools.memory_tools import vault_memories

    full = vault_memories(max_tokens=100_000)
    small = vault_memories(max_tokens=300)

    assert len(full["memories"]) == 20
    assert "truncated" not in full
    assert len(small["memories"]) < len(vault_memories()["memories"])
    assert small["truncated"] is True
