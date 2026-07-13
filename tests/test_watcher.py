"""Tests for neurostack.watcher — DebouncedHandler path filtering and debounce logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from neurostack.watcher import DebouncedHandler


def _make_handler(**kwargs):
    defaults = {
        "vault_root": Path("/tmp/vault"),
        "embed_url": "http://localhost:11434",
        "summarize_url": "http://localhost:11434",
        "exclude_dirs": ["node_modules"],
    }
    defaults.update(kwargs)
    return DebouncedHandler(**defaults)


class TestShouldProcess:
    def test_accepts_normal_md_files(self):
        handler = _make_handler()
        assert handler._should_process("/tmp/vault/notes/hello.md") is True
        assert handler._should_process("/tmp/vault/deep/nested/note.md") is True

    def test_rejects_non_md_files(self):
        handler = _make_handler()
        assert handler._should_process("/tmp/vault/script.py") is False
        assert handler._should_process("/tmp/vault/readme.txt") is False
        assert handler._should_process("/tmp/vault/data.json") is False

    def test_rejects_git_paths(self):
        handler = _make_handler()
        assert handler._should_process("/tmp/vault/.git/HEAD.md") is False
        assert handler._should_process("/tmp/vault/.git/refs/note.md") is False

    def test_rejects_obsidian_paths(self):
        handler = _make_handler()
        assert handler._should_process("/tmp/vault/.obsidian/workspace.md") is False

    def test_rejects_trash_paths(self):
        handler = _make_handler()
        assert handler._should_process("/tmp/vault/.trash/old.md") is False

    def test_rejects_custom_exclude_dirs(self):
        handler = _make_handler(exclude_dirs=["node_modules", "vendor"])
        assert handler._should_process("/tmp/vault/node_modules/readme.md") is False
        assert handler._should_process("/tmp/vault/vendor/lib.md") is False

    def test_no_exclude_dirs_still_skips_builtins(self):
        handler = _make_handler(exclude_dirs=None)
        assert handler._should_process("/tmp/vault/.git/note.md") is False
        assert handler._should_process("/tmp/vault/regular.md") is True


class TestOnAnyEvent:
    @patch("neurostack.watcher.Timer")
    def test_debounce_creates_timer(self, MockTimer):
        handler = _make_handler()
        mock_timer_instance = MagicMock()
        MockTimer.return_value = mock_timer_instance

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/vault/test.md"
        event.event_type = "modified"

        handler.on_any_event(event)

        MockTimer.assert_called_once()
        mock_timer_instance.start.assert_called_once()

    @patch("neurostack.watcher.Timer")
    def test_debounce_cancels_previous_timer(self, MockTimer):
        handler = _make_handler()
        first_timer = MagicMock()
        second_timer = MagicMock()
        MockTimer.side_effect = [first_timer, second_timer]

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/vault/test.md"
        event.event_type = "modified"

        handler.on_any_event(event)
        handler.on_any_event(event)

        first_timer.cancel.assert_called_once()
        second_timer.start.assert_called_once()

    @patch("neurostack.watcher.Timer")
    def test_ignores_directory_events(self, MockTimer):
        handler = _make_handler()

        event = MagicMock()
        event.is_directory = True
        event.src_path = "/tmp/vault/subdir"
        event.event_type = "created"

        handler.on_any_event(event)

        MockTimer.assert_not_called()

    @patch("neurostack.watcher.Timer")
    def test_ignores_non_md_events(self, MockTimer):
        handler = _make_handler()

        event = MagicMock()
        event.is_directory = False
        event.src_path = "/tmp/vault/image.png"
        event.event_type = "modified"

        handler.on_any_event(event)

        MockTimer.assert_not_called()


def _raise_triple_error(*a, **k):
    from neurostack.triples import TripleExtractionError
    raise TripleExtractionError("unparseable")


class TestTripleRetryQueue:
    """Triple-extraction failure / retry-queue bookkeeping (issue #28)."""

    def _note(self, conn, path="notes/a.md", content_hash="h1"):
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?,?,?,?)",
            (path, "A", content_hash, "2026-01-01"),
        )
        conn.commit()

    def test_record_then_clear(self, in_memory_db):
        from neurostack.watcher import _clear_triple_failure, _record_triple_failure
        conn = in_memory_db
        self._note(conn)
        _record_triple_failure(conn, "notes/a.md", "h1", "boom")
        row = conn.execute(
            "SELECT attempts, next_retry_at FROM triple_extraction_failed WHERE note_path=?",
            ("notes/a.md",),
        ).fetchone()
        assert row["attempts"] == 1
        assert row["next_retry_at"] is not None
        _clear_triple_failure(conn, "notes/a.md")
        assert conn.execute(
            "SELECT COUNT(*) c FROM triple_extraction_failed"
        ).fetchone()["c"] == 0

    def test_attempts_increment(self, in_memory_db):
        from neurostack.watcher import _record_triple_failure
        conn = in_memory_db
        self._note(conn)
        _record_triple_failure(conn, "notes/a.md", "h1", "e1")
        _record_triple_failure(conn, "notes/a.md", "h1", "e2")
        row = conn.execute(
            "SELECT attempts FROM triple_extraction_failed WHERE note_path=?",
            ("notes/a.md",),
        ).fetchone()
        assert row["attempts"] == 2

    def test_index_records_failure_on_parse_error(self, in_memory_db, monkeypatch):
        import neurostack.watcher as watcher_mod
        conn = in_memory_db
        self._note(conn)
        monkeypatch.setattr(watcher_mod, "extract_triples", _raise_triple_error)
        watcher_mod._index_triples_for_note(
            "notes/a.md", "A", "content", "h1", "2026-01-01",
            conn, "http://e", "http://l",
        )
        row = conn.execute(
            "SELECT attempts FROM triple_extraction_failed WHERE note_path=?",
            ("notes/a.md",),
        ).fetchone()
        assert row is not None and row["attempts"] == 1
        # No triples written for a failed extraction.
        assert conn.execute(
            "SELECT COUNT(*) c FROM triples WHERE note_path=?", ("notes/a.md",)
        ).fetchone()["c"] == 0

    def test_index_clears_failure_on_success(self, in_memory_db, monkeypatch):
        import neurostack.watcher as watcher_mod
        from neurostack.watcher import _record_triple_failure
        conn = in_memory_db
        self._note(conn)
        _record_triple_failure(conn, "notes/a.md", "h1", "old failure")
        monkeypatch.setattr(
            watcher_mod, "extract_triples",
            lambda *a, **k: [{"s": "A", "p": "b", "o": "C"}],
        )
        monkeypatch.setattr(watcher_mod, "HAS_NUMPY", False)
        watcher_mod._index_triples_for_note(
            "notes/a.md", "A", "content", "h1", "2026-01-01",
            conn, "http://e", "http://l",
        )
        assert conn.execute(
            "SELECT COUNT(*) c FROM triple_extraction_failed WHERE note_path=?",
            ("notes/a.md",),
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM triples WHERE note_path=?", ("notes/a.md",)
        ).fetchone()["c"] == 1


class TestReindexPreservesNoteMetadata:
    """A reindex of a *changed* note must not wipe accumulated per-note state.

    Regression: `INSERT OR REPLACE INTO notes` cascade-deleted the note_metadata
    row (ON DELETE CASCADE) before the upsert could preserve it, so status reset
    dormant->active and date_added was bumped on every reindex. The fix updates
    the note row in place via ON CONFLICT so the cascade never fires.
    """

    def _write(self, path, body):
        path.write_text(
            "---\ndate: 2026-01-01\ntags: [x]\ntype: permanent\n---\n\n# N\n\n" + body + "\n"
        )

    def test_status_date_and_usage_survive_reindex(self, in_memory_db, tmp_path, monkeypatch):
        import neurostack.watcher as w

        # Avoid the embedder: chunk embeddings aren't needed to prove metadata survival.
        monkeypatch.setattr(w, "get_embeddings_batch", lambda texts, **k: [None] * len(texts))
        conn = in_memory_db
        note = tmp_path / "n.md"
        self._write(note, "original body")
        w.index_single_note(note, tmp_path, conn, skip_summary=True, skip_triples=True)

        # Accumulate state that only exists post-index: a demotion, a distinct
        # date_added sentinel, and a usage row (hotness).
        conn.execute(
            "UPDATE note_metadata SET status='dormant', date_added='2020-12-25'"
            " WHERE note_path='n.md'"
        )
        conn.execute("INSERT INTO note_usage(note_path,used_at) VALUES('n.md','2026-06-01')")
        conn.commit()

        # Edit the file so content_hash changes, forcing a real reindex.
        self._write(note, "EDITED body now")
        w.index_single_note(note, tmp_path, conn, skip_summary=True, skip_triples=True)

        row = conn.execute(
            "SELECT status, date_added FROM note_metadata WHERE note_path='n.md'"
        ).fetchone()
        assert row["status"] == "dormant", "reindex must preserve dormant status"
        assert row["date_added"] == "2020-12-25", "reindex must preserve date_added"
        # Hotness history (no FK, must be untouched)
        assert conn.execute(
            "SELECT COUNT(*) c FROM note_usage WHERE note_path='n.md'"
        ).fetchone()["c"] == 1
        # ...and the content genuinely updated (chunks reflect the edit)
        chunks = conn.execute(
            "SELECT content FROM chunks WHERE note_path='n.md'"
        ).fetchall()
        assert any("EDITED" in c["content"] for c in chunks)


class TestIncrementalIndex:
    """incremental_index processes only the changed/deleted notes and skips the
    whole-vault global rebuild (graph/co-occurrence/vec) — the cheap path brain-sync
    uses so a small sync doesn't reindex the entire vault."""

    def _write(self, path, body):
        path.write_text(
            "---\ndate: 2026-01-01\ntags: [x]\ntype: permanent\n---\n\n# N\n\n" + body + "\n"
        )

    def test_indexes_changed_deletes_removed_skips_globals(
        self, in_memory_db, tmp_path, monkeypatch
    ):
        import neurostack.watcher as w

        # No real embedder needed to prove routing/CRUD behaviour.
        monkeypatch.setattr(w, "get_embeddings_batch", lambda texts, **k: [None] * len(texts))
        conn = in_memory_db

        # A note already in the index that the sync will delete.
        gone = tmp_path / "gone.md"
        self._write(gone, "obsolete body")
        w.index_single_note(gone, tmp_path, conn, skip_summary=True, skip_triples=True)
        assert conn.execute("SELECT 1 FROM notes WHERE path='gone.md'").fetchone()

        # A new/changed note on disk that incremental_index should pick up.
        changed = tmp_path / "changed.md"
        self._write(changed, "fresh body content")

        n_indexed, n_deleted = w.incremental_index(
            [changed], deleted=["gone.md"], vault_root=tmp_path,
            skip_summary=True, skip_triples=True, conn=conn,
        )

        assert (n_indexed, n_deleted) == (1, 1)
        # changed note indexed, with chunks
        assert conn.execute("SELECT 1 FROM notes WHERE path='changed.md'").fetchone()
        assert conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE note_path='changed.md'"
        ).fetchone()["c"] > 0
        # deleted note removed, and the FK cascade dropped its chunks
        assert conn.execute("SELECT 1 FROM notes WHERE path='gone.md'").fetchone() is None
        assert conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE note_path='gone.md'"
        ).fetchone()["c"] == 0
        # globals deliberately deferred: no wiki-link graph was rebuilt this run
        assert conn.execute("SELECT COUNT(*) c FROM graph_edges").fetchone()["c"] == 0

    def test_unchanged_note_is_a_noop(self, in_memory_db, tmp_path, monkeypatch):
        import neurostack.watcher as w

        monkeypatch.setattr(w, "get_embeddings_batch", lambda texts, **k: [None] * len(texts))
        conn = in_memory_db
        note = tmp_path / "n.md"
        self._write(note, "stable body")
        w.index_single_note(note, tmp_path, conn, skip_summary=True, skip_triples=True)
        before = conn.execute("SELECT updated_at FROM notes WHERE path='n.md'").fetchone()[0]

        # Re-run over the same unchanged file: content-hash short-circuit → no rewrite.
        n_indexed, n_deleted = w.incremental_index(
            [note], vault_root=tmp_path, skip_summary=True, skip_triples=True, conn=conn,
        )
        after = conn.execute("SELECT updated_at FROM notes WHERE path='n.md'").fetchone()[0]
        assert n_indexed == 1 and n_deleted == 0
        assert before == after, "unchanged note must not be rewritten"
