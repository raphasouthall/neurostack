# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for orphan reconciliation (pruning notes deleted from disk)."""

from neurostack.watcher import reconcile_deletions


def _insert_note(conn, path, *, with_chunk=False):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (path, path, "h", "2026-01-15T00:00:00+00:00"),
    )
    if with_chunk:
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, "
            "content_hash, position) VALUES (?, ?, ?, ?, ?)",
            (path, "", "body", "h", 0),
        )
    conn.commit()


def _make_file(vault, rel):
    f = vault / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# note\n")
    return f


def test_prunes_orphan_and_cascades_chunks(in_memory_db, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_file(vault, "keep.md")
    _insert_note(in_memory_db, "keep.md")
    _insert_note(in_memory_db, "ghost.md", with_chunk=True)

    pruned = reconcile_deletions(in_memory_db, vault)

    assert pruned == 1
    paths = {r["path"] for r in in_memory_db.execute("SELECT path FROM notes")}
    assert paths == {"keep.md"}
    # FK cascade should have removed the orphan's chunk
    chunk_rows = in_memory_db.execute(
        "SELECT COUNT(*) FROM chunks WHERE note_path = 'ghost.md'"
    ).fetchone()[0]
    assert chunk_rows == 0


def test_no_orphans_returns_zero(in_memory_db, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_file(vault, "keep.md")
    _insert_note(in_memory_db, "keep.md")

    assert reconcile_deletions(in_memory_db, vault) == 0


def test_empty_scan_is_a_no_op_safety_guard(in_memory_db, tmp_path):
    """An empty scan (unmounted/misconfigured vault) must not wipe the index."""
    vault = tmp_path / "vault"
    vault.mkdir()  # no .md files on disk
    _insert_note(in_memory_db, "ghost.md")

    pruned = reconcile_deletions(in_memory_db, vault)

    assert pruned == 0
    paths = {r["path"] for r in in_memory_db.execute("SELECT path FROM notes")}
    assert paths == {"ghost.md"}  # preserved despite not being on disk


def test_excluded_dir_notes_are_pruned(in_memory_db, tmp_path):
    """Excluded dirs aren't managed by the indexer, so stale rows pointing
    into them are reconciled away — same exclusion the scan applies."""
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_file(vault, "keep.md")
    _make_file(vault, "archive/old.md")
    _insert_note(in_memory_db, "keep.md")
    _insert_note(in_memory_db, "archive/old.md")

    # 'archive' excluded: its file is skipped in the scan, so the DB row for
    # archive/old.md would look orphaned. Confirm current behaviour is explicit.
    pruned = reconcile_deletions(in_memory_db, vault, exclude_dirs=["archive"])

    assert pruned == 1
    paths = {r["path"] for r in in_memory_db.execute("SELECT path FROM notes")}
    assert paths == {"keep.md"}
