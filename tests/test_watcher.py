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
