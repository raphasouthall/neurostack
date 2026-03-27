"""Tests for neurostack.brief — session brief generator."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from neurostack.brief import (
    generate_brief,
    get_external_memories,
    get_git_recent,
    get_recent_vault_changes,
    get_top_notes,
)


class TestGetRecentVaultChanges:
    def test_returns_notes_from_populated_db(self, populated_db):
        results = get_recent_vault_changes(populated_db)
        assert len(results) > 0
        assert "path" in results[0]
        assert "title" in results[0]
        assert "updated_at" in results[0]

    def test_respects_limit(self, populated_db):
        results = get_recent_vault_changes(populated_db, limit=1)
        assert len(results) == 1

    def test_workspace_filtering(self, populated_db):
        results = get_recent_vault_changes(populated_db, workspace="research/")
        assert len(results) > 0
        for r in results:
            assert r["path"].startswith("research/")

    def test_workspace_filtering_no_match(self, populated_db):
        results = get_recent_vault_changes(populated_db, workspace="nonexistent/")
        assert results == []

    def test_empty_db_returns_empty(self, in_memory_db):
        results = get_recent_vault_changes(in_memory_db)
        assert results == []


class TestGetGitRecent:
    def test_returns_git_log_lines(self, tmp_path):
        fake_output = "abc1234 Initial commit\ndef5678 Add feature"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch("neurostack.brief.subprocess.run", return_value=mock_result) as mock_run:
            result = get_git_recent(tmp_path, limit=5)

        assert result == ["abc1234 Initial commit", "def5678 Add feature"]
        mock_run.assert_called_once_with(
            ["git", "log", "--max-count=5", "--oneline", "--no-decorate"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_returns_empty_on_timeout(self, tmp_path):
        with patch(
            "neurostack.brief.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            result = get_git_recent(tmp_path)
        assert result == []

    def test_returns_empty_on_file_not_found(self, tmp_path):
        with patch(
            "neurostack.brief.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = get_git_recent(tmp_path)
        assert result == []

    def test_returns_empty_on_nonzero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("neurostack.brief.subprocess.run", return_value=mock_result):
            result = get_git_recent(tmp_path)
        assert result == []

    def test_respects_limit_parameter(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc1234 Commit one"

        with patch("neurostack.brief.subprocess.run", return_value=mock_result) as mock_run:
            get_git_recent(tmp_path, limit=3)

        args = mock_run.call_args[0][0]
        assert "--max-count=3" in args


class TestGetExternalMemories:
    def test_returns_empty_when_db_missing(self, tmp_path):
        fake_path = tmp_path / "does_not_exist.db"
        with patch("neurostack.brief.EXTERNAL_MEMORY_DB", fake_path):
            result = get_external_memories()
        assert result == []


class TestGetTopNotes:
    @pytest.fixture
    def db_with_graph_stats(self, populated_db):
        """Insert graph_stats rows for notes in the populated DB."""
        conn = populated_db
        # Get existing note paths
        rows = conn.execute("SELECT path FROM notes").fetchall()
        paths = [r["path"] for r in rows]

        for i, path in enumerate(paths):
            conn.execute(
                "INSERT INTO graph_stats (note_path, in_degree, out_degree, pagerank) "
                "VALUES (?, ?, ?, ?)",
                (path, (i + 1) * 2, (i + 1), 0.1 * (i + 1)),
            )
        conn.commit()
        return conn

    def test_returns_top_notes(self, db_with_graph_stats):
        results = get_top_notes(db_with_graph_stats)
        assert len(results) > 0
        assert "note_path" in results[0]
        assert "title" in results[0]
        assert "pagerank" in results[0]
        assert "in_degree" in results[0]

    def test_ordered_by_pagerank_desc(self, db_with_graph_stats):
        results = get_top_notes(db_with_graph_stats)
        pageranks = [r["pagerank"] for r in results]
        assert pageranks == sorted(pageranks, reverse=True)

    def test_respects_limit(self, db_with_graph_stats):
        results = get_top_notes(db_with_graph_stats, limit=1)
        assert len(results) == 1

    def test_workspace_filtering(self, db_with_graph_stats):
        results = get_top_notes(db_with_graph_stats, workspace="research/")
        assert len(results) > 0
        for r in results:
            assert r["note_path"].startswith("research/")

    def test_workspace_filtering_no_match(self, db_with_graph_stats):
        results = get_top_notes(db_with_graph_stats, workspace="nonexistent/")
        assert results == []

    def test_empty_graph_stats(self, populated_db):
        results = get_top_notes(populated_db)
        assert results == []


class TestGenerateBrief:
    def test_output_contains_expected_sections(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief()

        assert "Session Brief" in brief
        assert "Vault:" in brief
        assert "notes" in brief

    def test_includes_recent_changes(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief()

        assert "Recent changes" in brief

    def test_includes_git_history(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=["abc123 Fix typo"]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief()

        assert "Recent commits" in brief
        assert "abc123 Fix typo" in brief

    def test_includes_external_memories(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path
        fake_memories = [{"topic_key": "test-topic", "content": "Some observation"}]

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=fake_memories),
        ):
            brief = generate_brief()

        assert "Recent memories" in brief
        assert "test-topic" in brief

    def test_with_workspace(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief(workspace="research")

        assert "[research]" in brief

    def test_explicit_vault_root(self, populated_db, tmp_path):
        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief(vault_root=tmp_path)

        assert "Session Brief" in brief

    def test_note_count_in_stats(self, populated_db, tmp_path):
        mock_config = MagicMock()
        mock_config.vault_root = tmp_path

        note_count = populated_db.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]

        with (
            patch("neurostack.brief.get_db", return_value=populated_db),
            patch("neurostack.brief.get_config", return_value=mock_config),
            patch("neurostack.brief.get_git_recent", return_value=[]),
            patch("neurostack.brief.get_external_memories", return_value=[]),
        ):
            brief = generate_brief()

        assert f"{note_count} notes" in brief
