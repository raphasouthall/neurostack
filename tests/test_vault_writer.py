"""Tests for neurostack.vault_writer — issue #20 vault write-back."""

from __future__ import annotations

import json
import uuid as _uuid

import pytest

from neurostack import config as nsconfig
from neurostack.memories import (
    Memory,
    forget_memory,
    merge_memories,
    save_memory,
    update_memory,
)
from neurostack.vault_writer import (
    VaultWriter,
    WriteBackError,
    _body_hash,
    get_vault_writer,
    migrate_writeback,
    sync_writeback,
)

# --------------------------- fixtures ----------------------------------------


@pytest.fixture
def wb_vault(tmp_path, monkeypatch):
    """A temp vault with write-back enabled via env; resets the config singleton."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(vault))
    monkeypatch.setenv("NEUROSTACK_WRITEBACK_ENABLED", "1")
    monkeypatch.delenv("NEUROSTACK_WRITEBACK_INCLUDE_OBSERVATIONS", raising=False)
    # Point embeddings at a dead port so save_memory fails fast and offline.
    monkeypatch.setenv("NEUROSTACK_EMBED_URL", "http://127.0.0.1:1")
    nsconfig._config = None
    yield vault
    nsconfig._config = None


def _mem(content="Decision body", entity_type="decision", expires_at=None,
         tags=None, memory_id=1, created_at="2026-06-13 12:00:00", uuid=None):
    return Memory(
        memory_id=memory_id,
        content=content,
        tags=tags or [],
        entity_type=entity_type,
        source_agent="test",
        workspace=None,
        created_at=created_at,
        expires_at=expires_at,
        uuid=uuid or str(_uuid.uuid4()),
    )


def _insert(conn, content, entity_type="decision", expires_at=None,
            tags=None, workspace=None, uuid=None):
    """Raw INSERT that bypasses the write-back hook (clean DB-only state)."""
    uid = uuid or str(_uuid.uuid4())
    cur = conn.execute(
        "INSERT INTO memories (content, tags, entity_type, source_agent, "
        "workspace, embedding, expires_at, session_id, uuid, embed_pending) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (content, json.dumps(tags or []), entity_type, "test", workspace,
         None, expires_at, None, uid),
    )
    conn.commit()
    return cur.lastrowid


# --------------------------- policy ------------------------------------------


def test_should_write_persistent_types(tmp_path):
    w = VaultWriter(tmp_path / "v", include_observations=False)
    for t in ("decision", "convention", "learning", "bug"):
        assert w.should_write(_mem(entity_type=t)) is True


def test_should_write_excludes_ttl(tmp_path):
    w = VaultWriter(tmp_path / "v")
    assert w.should_write(_mem(expires_at="2026-12-01 00:00:00")) is False


def test_should_write_observation_gated(tmp_path):
    off = VaultWriter(tmp_path / "v", include_observations=False)
    on = VaultWriter(tmp_path / "v", include_observations=True)
    for t in ("observation", "context"):
        assert off.should_write(_mem(entity_type=t)) is False
        assert on.should_write(_mem(entity_type=t)) is True


def test_should_write_requires_uuid(tmp_path):
    w = VaultWriter(tmp_path / "v")
    m = _mem()
    m.uuid = None
    assert w.should_write(m) is False


# --------------------------- paths & safety ----------------------------------


def test_shallow_vault_root_rejected():
    with pytest.raises(WriteBackError):
        VaultWriter("/")


def test_invalid_writeback_path_rejected(tmp_path):
    with pytest.raises(WriteBackError):
        VaultWriter(tmp_path / "v", writeback_path="../escape")


def test_relpath_layout_and_uuid_validation(tmp_path):
    w = VaultWriter(tmp_path / "v")
    uid = "0123abcd-0000-0000-0000-000000000000"
    m = _mem(entity_type="learning", created_at="2026-03-09 08:00:00", uuid=uid)
    assert w.relpath(m) == f".neurostack/memories/learning/2026-03/{uid}.md"

    m.uuid = "not-a-uuid"
    with pytest.raises(ValueError):
        w.relpath(m)


# --------------------------- render / write ----------------------------------


def test_write_produces_frontmatter_body_and_hash(tmp_path):
    w = VaultWriter(tmp_path / "v")
    m = _mem(content="# Heading\n\nThe decision text.", tags=["a", "b"])
    relpath = w.write(m)
    abs_path = w.vault_root / relpath
    assert abs_path.is_file()

    parsed = w.parse_file(abs_path)
    fm = parsed["frontmatter"]
    assert fm["neurostack_id"] == m.uuid
    assert fm["entity_type"] == "decision"
    assert fm["tags"] == ["a", "b"]
    assert fm["title"] == "Heading"  # first non-empty line, '#' stripped
    assert parsed["body"] == "# Heading\n\nThe decision text."
    # Stored hash matches the body content.
    assert fm["neurostack_hash"] == _body_hash(parsed["body"])


def test_write_is_atomic_overwrite(tmp_path):
    w = VaultWriter(tmp_path / "v")
    m = _mem(content="v1")
    w.write(m)
    m.content = "v2 longer content"
    w.write(m)
    abs_path = w.vault_root / w.relpath(m)
    assert w.parse_file(abs_path)["body"] == "v2 longer content"
    # No stray .tmp left behind.
    assert not list(abs_path.parent.glob("*.tmp"))


def test_gitignore_self_ignores(tmp_path):
    w = VaultWriter(tmp_path / "v")
    w.write(_mem())
    gi = w.writeback_dir / ".gitignore"
    assert gi.is_file()
    assert gi.read_text().strip().endswith("*")


def test_delete_prunes_empty_dirs(tmp_path):
    w = VaultWriter(tmp_path / "v")
    m = _mem()
    relpath = w.write(m)
    assert w.delete(relpath) is True
    assert not (w.vault_root / relpath).exists()
    # type/month dirs pruned, but memories_dir survives.
    assert not (w.memories_dir / "decision").exists()
    assert w.delete(relpath) is False  # idempotent


# --------------------------- CRUD integration --------------------------------


def test_save_memory_writes_file(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "A real decision", entity_type="decision",
                    dedup=False)
    assert m.file_path is not None
    assert (wb_vault / m.file_path).is_file()
    # DB column populated too.
    row = in_memory_db.execute(
        "SELECT file_path FROM memories WHERE memory_id = ?", (m.memory_id,)
    ).fetchone()
    assert row["file_path"] == m.file_path


def test_save_ttl_memory_not_written(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "ephemeral", entity_type="decision",
                    ttl_hours=1, dedup=False)
    assert m.file_path is None
    assert not list((wb_vault / ".neurostack").rglob("*.md"))


def test_save_observation_gated(tmp_path, monkeypatch, in_memory_db):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(vault))
    monkeypatch.setenv("NEUROSTACK_WRITEBACK_ENABLED", "1")
    monkeypatch.setenv("NEUROSTACK_EMBED_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("NEUROSTACK_WRITEBACK_INCLUDE_OBSERVATIONS", "1")
    nsconfig._config = None
    try:
        m = save_memory(in_memory_db, "an observation",
                        entity_type="observation", dedup=False)
        assert m.file_path is not None
        assert "/observation/" in m.file_path
    finally:
        nsconfig._config = None


def test_update_moves_file_on_type_change(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "starts as learning",
                    entity_type="learning", dedup=False)
    old = m.file_path
    assert "/learning/" in old

    updated = update_memory(in_memory_db, m.memory_id, entity_type="decision")
    assert updated.file_path is not None
    assert "/decision/" in updated.file_path
    assert not (wb_vault / old).exists()         # stale file removed
    assert (wb_vault / updated.file_path).is_file()


def test_update_adding_ttl_removes_file(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "permanent then ephemeral",
                    entity_type="decision", dedup=False)
    assert (wb_vault / m.file_path).exists()

    updated = update_memory(in_memory_db, m.memory_id, ttl_hours=2)
    assert updated.file_path is None
    assert not list((wb_vault / ".neurostack").rglob("*.md"))


def test_update_content_rewrites_and_bumps_hash(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "original", entity_type="bug", dedup=False)
    w = get_vault_writer()
    before = w.parse_file(wb_vault / m.file_path)["frontmatter"]["neurostack_hash"]

    update_memory(in_memory_db, m.memory_id, content="rewritten body")
    after_fm = w.parse_file(wb_vault / m.file_path)["frontmatter"]
    assert after_fm["neurostack_hash"] != before
    assert after_fm["revision_count"] == 2


def test_forget_deletes_file(wb_vault, in_memory_db):
    m = save_memory(in_memory_db, "to be forgotten",
                    entity_type="decision", dedup=False)
    path = wb_vault / m.file_path
    assert path.exists()
    assert forget_memory(in_memory_db, m.memory_id) is True
    assert not path.exists()


def test_merge_deletes_source_keeps_target(wb_vault, in_memory_db):
    target = save_memory(in_memory_db, "short", entity_type="decision",
                         dedup=False)
    source = save_memory(
        in_memory_db,
        "a much longer and more detailed decision body that should win",
        entity_type="decision", dedup=False,
    )
    src_path = wb_vault / source.file_path
    assert src_path.exists()

    merged = merge_memories(in_memory_db, target.memory_id, source.memory_id)
    assert not src_path.exists()                  # source file gone
    assert merged.file_path is not None
    merged_file = wb_vault / merged.file_path
    assert merged_file.is_file()
    body = get_vault_writer().parse_file(merged_file)["body"]
    assert "longer and more detailed" in body     # target absorbed source body


def test_writeback_disabled_writes_nothing(tmp_path, monkeypatch, in_memory_db):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(vault))
    monkeypatch.delenv("NEUROSTACK_WRITEBACK_ENABLED", raising=False)
    monkeypatch.setenv("NEUROSTACK_EMBED_URL", "http://127.0.0.1:1")
    nsconfig._config = None
    try:
        m = save_memory(in_memory_db, "decision", entity_type="decision",
                        dedup=False)
        assert m.file_path is None
        assert get_vault_writer() is None
        assert not (vault / ".neurostack").exists()
    finally:
        nsconfig._config = None


# --------------------------- migrate -----------------------------------------


def test_migrate_dry_run_writes_nothing(wb_vault, in_memory_db):
    _insert(in_memory_db, "d1", "decision")
    _insert(in_memory_db, "l1", "learning")
    _insert(in_memory_db, "ttl", "decision", expires_at="2026-12-01 00:00:00")
    _insert(in_memory_db, "obs", "observation")

    w = get_vault_writer()
    report = migrate_writeback(in_memory_db, w, dry_run=True)
    assert report["dry_run"] is True
    assert len(report["written"]) == 2          # decision + learning only
    assert report["skipped"]["ttl"] == 1
    assert report["skipped"]["type"] == 1       # the observation
    assert not list((wb_vault / ".neurostack").rglob("*.md"))


def test_migrate_isolates_bad_rows(wb_vault, in_memory_db):
    good = _insert(in_memory_db, "good", "decision")
    # A qualifying row with a corrupt uuid: should_write passes (uuid truthy)
    # but relpath() rejects it — the batch must survive and report the error.
    _insert(in_memory_db, "bad", "decision", uuid="not-a-real-uuid")

    w = get_vault_writer()
    report = migrate_writeback(in_memory_db, w, dry_run=False)
    assert len(report["written"]) == 1
    assert len(report["errors"]) == 1
    row = in_memory_db.execute(
        "SELECT file_path FROM memories WHERE memory_id = ?", (good,)
    ).fetchone()
    assert row["file_path"] is not None


def test_migrate_real_writes_qualifying_only(wb_vault, in_memory_db):
    d = _insert(in_memory_db, "d1", "decision")
    _insert(in_memory_db, "ttl", "bug", expires_at="2026-12-01 00:00:00")

    w = get_vault_writer()
    report = migrate_writeback(in_memory_db, w, dry_run=False)
    assert len(report["written"]) == 1
    files = list((wb_vault / ".neurostack").rglob("*.md"))
    assert len(files) == 1
    row = in_memory_db.execute(
        "SELECT file_path FROM memories WHERE memory_id = ?", (d,)
    ).fetchone()
    assert row["file_path"] is not None


# --------------------------- sync --------------------------------------------


def test_sync_creates_missing(wb_vault, in_memory_db):
    _insert(in_memory_db, "d1", "decision")
    w = get_vault_writer()
    report = sync_writeback(in_memory_db, w)
    assert len(report["created"]) == 1
    assert report["in_sync"] == 0


def test_sync_conflict_db_wins(wb_vault, in_memory_db):
    mid = _insert(in_memory_db, "the canonical body", "decision")
    w = get_vault_writer()
    sync_writeback(in_memory_db, w)  # create the file

    relpath = in_memory_db.execute(
        "SELECT file_path FROM memories WHERE memory_id = ?", (mid,)
    ).fetchone()["file_path"]
    abs_path = wb_vault / relpath
    # Simulate a user editing the file body in Obsidian.
    edited = abs_path.read_text().replace("the canonical body", "user edit")
    abs_path.write_text(edited)

    report = sync_writeback(in_memory_db, w)
    assert relpath in report["conflicts"]
    # DB content wins.
    assert w.parse_file(abs_path)["body"] == "the canonical body"


def test_sync_removes_orphan(wb_vault, in_memory_db):
    w = get_vault_writer()
    orphan = w.memories_dir / "decision" / "2026-06" / "deadbeef.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("---\ntitle: x\n---\n\norphan\n")

    report = sync_writeback(in_memory_db, w)
    assert len(report["removed"]) == 1
    assert not orphan.exists()


def test_sync_in_sync_noop(wb_vault, in_memory_db):
    _insert(in_memory_db, "stable", "decision")
    w = get_vault_writer()
    sync_writeback(in_memory_db, w)
    report = sync_writeback(in_memory_db, w)
    assert report["in_sync"] == 1
    assert report["created"] == []
    assert report["updated"] == []


# --------------------------- watcher exclusion -------------------------------


def test_watcher_excludes_writeback_dir(wb_vault):
    from neurostack import watcher

    parts = watcher._base_skip_parts()
    assert ".neurostack" in parts
