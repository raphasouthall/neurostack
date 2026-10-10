# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""vault_memories reply budget (issue #322) and workspace lean (#324)."""

import pytest

from neurostack import config as nsconfig


@pytest.fixture
def db(tmp_path, monkeypatch):
    # Default DB path so registry tools (which open get_db(DB_PATH)) share the file.
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    # Twenty memories of ~600 chars, about 3,000 tokens with their JSON keys.
    conn.executemany(
        "INSERT INTO memories (content, tags) VALUES (?, '[]')",
        [(f"memory {i} " + "x" * 600,) for i in range(20)],
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


def test_default_budget_holds_more_than_1500_tokens(db):
    # Issue #324: 1,500 tokens cut replies short.
    from neurostack.tools.memory_tools import vault_memories

    assert len(vault_memories()["memories"]) > len(vault_memories(max_tokens=1500)["memories"])


def test_memory_in_the_query_workspace_ranks_first(db, monkeypatch):
    # Issue #324: an equally relevant memory from another workspace came first.
    import numpy as np

    import neurostack.embedder as embedder
    from neurostack.tools.memory_tools import vault_memories

    monkeypatch.setattr(embedder, "get_embedding",
                        lambda q, base_url=None: np.ones(3, dtype=np.float32))
    for path in ("work/acme/projects/remote-desktop/hosts.md",
                 "work/acme/resources/pool.md", "home/notes/misc.md"):
        db.execute("INSERT INTO notes (path, title, content_hash, updated_at)"
                   " VALUES (?, 'T', ?, '2026-01-01')", (path, path))
        db.execute("INSERT INTO chunks (note_path, content)"
                   " VALUES (?, 'sessionhost pool HOST01')", (path,))
    # Inserted first, so it wins the tie without the lean.
    db.execute("INSERT INTO memories (content, workspace, tags)"
               " VALUES ('sessionhost drained', 'home/projects/tooling', '[]')")
    db.execute("INSERT INTO memories (content, workspace, tags)"
               " VALUES ('sessionhost rebooted', 'work/acme', '[]')")
    db.commit()

    memories = vault_memories(query="sessionhost")["memories"]

    assert [m["workspace"] for m in memories] == ["work/acme", "home/projects/tooling"]
