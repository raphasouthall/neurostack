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
