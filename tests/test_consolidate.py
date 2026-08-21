"""Tests for consolidation replay (issue #96) — promotion queue -> basin
clusters -> synthesis -> note write -> archive.

The LLM and the git-backed write path are seams (monkeypatched); clustering,
planning, cap, archive bookkeeping, and failure isolation are exercised for
real against an in-memory DB.
"""

import json
import struct

import pytest

import neurostack.consolidate as consolidate_mod
from neurostack.consolidate import (
    EXTEND_SIM_FLOOR,
    _extended_content,
    _new_note_content,
    _slugify,
    _strip_fences,
    cluster_candidates,
    consolidate_replay,
)

DIM = 768


def _emb(*components) -> bytes:
    v = [0.0] * DIM
    for i, c in enumerate(components):
        v[i] = c
    return struct.pack(f"{DIM}f", *v)


def _add_note(conn, path, emb=None):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        (path, path, f"h_{path}", "2026-01-01"),
    )
    if emb is not None:
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
            "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (path, "## H", "body", f"hc_{path}", 0, emb),
        )


def _add_memory(conn, content, emb, *, entity_type="decision", tags=None,
                workspace=None):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, tags, workspace, embedding)"
        " VALUES (?, ?, ?, ?, ?)",
        (content, entity_type, json.dumps(tags or []), workspace, emb),
    )
    conn.commit()
    return cur.lastrowid


def _add_community(conn, note_paths, level=0):
    cur = conn.execute(
        "INSERT INTO communities (level, entity_count, member_notes, updated_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        (level, len(note_paths), len(note_paths)),
    )
    cid = cur.lastrowid
    conn.executemany(
        "INSERT INTO community_members (community_id, entity) VALUES (?, ?)",
        [(cid, p) for p in note_paths],
    )
    conn.commit()
    return cid


@pytest.fixture
def vault_db(in_memory_db):
    """Two notes: covered.md (basin c1), lonely.md (no community).

    Memory A: promotion-debt, embedding identical to covered.md's chunk
    (sim 1.0 -> extend). Memory B: durable, cosine 0.5 to lonely.md and 0 to
    covered.md -> uncovered, no basin -> workspace-keyed create cluster.
    """
    conn = in_memory_db
    _add_note(conn, "covered.md", emb=_emb(1.0))
    _add_note(conn, "lonely.md", emb=_emb(0.0, 1.0))
    cid = _add_community(conn, ["covered.md"])
    a = _add_memory(conn, "Debt fact: pipeline 231 deploys the dashboard",
                    _emb(1.0), tags=["promotion-debt"], workspace="work")
    b = _add_memory(conn, "Uncovered fact: LXC 127 pins num_thread=1",
                    _emb(0.0, 0.5, 0.86603), workspace="homelab")
    conn.commit()
    return conn, cid, a, b


class TestHelpers:
    def test_slugify(self):
        assert _slugify("Ollama CPU fallback: num_thread=1!") == \
            "ollama-cpu-fallback-num-thread-1"
        assert _slugify("???") == "consolidated"

    def test_strip_fences_and_think(self):
        raw = "<think>hmm</think>```json\n{\"a\": 1}\n```"
        assert _strip_fences(raw) == '{"a": 1}'

    def test_new_note_has_frontmatter_and_sources(self):
        members = [{"memory_id": 7, "entity_type": "decision",
                    "created_at": "2026-01-01"}]
        content = _new_note_content("T", "body", members)
        assert content.startswith("---\ndate:")
        assert "# T" in content and "- memory 7 (decision, 2026-01-01)" in content

    def test_extended_content_appends_section(self):
        members = [{"memory_id": 7, "entity_type": "bug", "created_at": "x"}]
        out = _extended_content("---\n---\n\n# Old\n\nbody\n", "New facts",
                                "synth", members)
        assert out.startswith("---\n---\n\n# Old")
        assert "## New facts (consolidated" in out
        assert "- memory 7 (bug, x)" in out


class TestClustering:
    def test_clusters_split_by_basin_and_action(self, vault_db):
        conn, cid, a, b = vault_db
        clusters = cluster_candidates(conn)

        assert len(clusters) == 2
        by_basin = {str(c["basin"]): c for c in clusters}
        extend = by_basin[str(cid)]
        create = by_basin["ws:homelab"]
        assert extend["action"] == "extend"
        assert extend["target"] == "covered.md"
        assert [m["memory_id"] for m in extend["members"]] == [a]
        assert create["action"] == "create"
        assert create["target"] is None
        assert create["target_folder"] == "homelab"
        assert [m["memory_id"] for m in create["members"]] == [b]

    def test_no_candidates_no_clusters(self, in_memory_db):
        assert cluster_candidates(in_memory_db) == []

    def test_extend_floor_matches_promotion_floor(self):
        assert EXTEND_SIM_FLOOR == 0.55


class TestDryRun:
    def test_dry_run_plans_without_llm_or_writes(self, vault_db, monkeypatch):
        conn, cid, a, b = vault_db

        def boom(*args, **kwargs):
            raise AssertionError("dry run must not call the LLM")
        monkeypatch.setattr(consolidate_mod, "_synthesize", boom)

        report = consolidate_replay(conn, dry_run=True)

        assert report["dry_run"] is True
        assert report["clusters_found"] == 2
        assert len(report["consolidated"]) == 2
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM memories_archive").fetchone()[0] == 0

    def test_cap_defers_extra_clusters(self, vault_db):
        conn, *_ = vault_db
        report = consolidate_replay(conn, cap=1, dry_run=True)
        assert report["clusters_planned"] == 1
        assert len(report["deferred"]) == 1


class TestRealRun:
    def _patch_write(self, monkeypatch, tmp_path, pushed=True):
        from neurostack.tools import file_tools

        (tmp_path / "covered.md").write_text(
            "---\ndate: 2026-01-01\n---\n\n# Covered\n\nold body\n")
        writes = []

        def fake_write(path, content, commit_message=None):
            writes.append({"path": path, "content": content,
                           "commit_message": commit_message})
            return {"pushed": pushed, "commit_sha": "abc123def",
                    "git_error": None if pushed else "push failed"}

        monkeypatch.setattr(file_tools, "_vault_root", lambda: tmp_path)
        monkeypatch.setattr(file_tools, "vault_write_file", fake_write)
        return writes

    def _patch_llm(self, monkeypatch):
        monkeypatch.setattr(
            consolidate_mod, "_synthesize",
            lambda members, *a, **kw: {"title": "Synth Title",
                                       "synthesis": "the consolidated facts"},
        )

    def test_run_writes_and_archives_with_pointer(self, vault_db, tmp_path,
                                                  monkeypatch):
        conn, cid, a, b = vault_db
        writes = self._patch_write(monkeypatch, tmp_path)
        self._patch_llm(monkeypatch)

        report = consolidate_replay(conn, dry_run=False)

        assert len(report["consolidated"]) == 2
        assert report["skipped"] == []
        paths = {w["path"] for w in writes}
        assert "covered.md" in paths
        assert "homelab/synth-title.md" in paths
        extended = next(w for w in writes if w["path"] == "covered.md")
        assert "old body" in extended["content"]  # extend keeps the note
        assert "## Synth Title (consolidated" in extended["content"]
        created = next(w for w in writes if w["path"] != "covered.md")
        assert created["content"].startswith("---\ndate:")

        # both memories archived with a pointer to the absorbing note
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
        rows = conn.execute(
            "SELECT memory_id, archive_reason FROM memories_archive").fetchall()
        reasons = {r["memory_id"]: r["archive_reason"] for r in rows}
        assert reasons[a] == "promoted:covered.md"
        assert reasons[b] == "promoted:homelab/synth-title.md"

    def test_failed_push_skips_and_keeps_memories(self, vault_db, tmp_path,
                                                  monkeypatch):
        conn, cid, a, b = vault_db
        self._patch_write(monkeypatch, tmp_path, pushed=False)
        self._patch_llm(monkeypatch)

        report = consolidate_replay(conn, dry_run=False)

        assert report["consolidated"] == []
        assert len(report["skipped"]) == 2
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM memories_archive").fetchone()[0] == 0

    def test_synthesis_failure_isolated_per_cluster(self, vault_db, tmp_path,
                                                    monkeypatch):
        conn, cid, a, b = vault_db
        self._patch_write(monkeypatch, tmp_path)
        calls = {"n": 0}

        def flaky(members, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("model gibberish")
            return {"title": "OK", "synthesis": "facts"}
        monkeypatch.setattr(consolidate_mod, "_synthesize", flaky)

        report = consolidate_replay(conn, dry_run=False)

        assert len(report["skipped"]) == 1
        assert "synthesis failed" in report["skipped"][0]["error"]
        assert len(report["consolidated"]) == 1  # the other cluster proceeded
        assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
