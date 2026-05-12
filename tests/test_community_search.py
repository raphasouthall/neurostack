"""Tests for neurostack.community_search — cache key hashing and global_query."""

import hashlib
import sqlite3
from unittest.mock import MagicMock, patch

from neurostack.community_search import _MAP_CACHE, _map_cache_key, global_query


class TestMapCacheKey:
    def test_deterministic(self):
        key1 = _map_cache_key("title", "summary", "query")
        key2 = _map_cache_key("title", "summary", "query")
        assert key1 == key2

    def test_returns_16_char_hex(self):
        key = _map_cache_key("title", "summary", "query")
        assert len(key) == 16
        # Ensure it's valid hex
        int(key, 16)

    def test_matches_expected_sha256(self):
        content = "title|summary|query"
        expected = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert _map_cache_key("title", "summary", "query") == expected

    def test_different_inputs_different_hashes(self):
        key_a = _map_cache_key("title_a", "summary", "query")
        key_b = _map_cache_key("title_b", "summary", "query")
        assert key_a != key_b

        key_c = _map_cache_key("title", "summary_a", "query")
        key_d = _map_cache_key("title", "summary_b", "query")
        assert key_c != key_d

        key_e = _map_cache_key("title", "summary", "query_a")
        key_f = _map_cache_key("title", "summary", "query_b")
        assert key_e != key_f

    def test_empty_strings(self):
        key = _map_cache_key("", "", "")
        expected = hashlib.sha256("||".encode()).hexdigest()[:16]
        assert key == expected


class TestMapCache:
    def test_cache_is_module_level_dict(self):
        assert isinstance(_MAP_CACHE, dict)

    def test_cache_can_be_manipulated(self):
        _MAP_CACHE["test_key"] = (0.0, "result")
        assert _MAP_CACHE["test_key"] == (0.0, "result")
        del _MAP_CACHE["test_key"]
        assert "test_key" not in _MAP_CACHE


class TestGlobalQueryRawHits:
    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_use_map_reduce_false_returns_raw_hits(self, mock_search, mock_config):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg

        fake_hits = [
            {
                "community_id": 1,
                "level": 0,
                "title": "Topic A",
                "summary": "About topic A",
                "entity_count": 5,
                "member_notes": "note1.md,note2.md",
                "score": 0.9,
            },
            {
                "community_id": 2,
                "level": 0,
                "title": "Topic B",
                "summary": "About topic B",
                "entity_count": 3,
                "member_notes": "note3.md",
                "score": 0.7,
            },
        ]
        mock_search.return_value = fake_hits

        result = global_query(
            "test question",
            top_k=6,
            level=0,
            use_map_reduce=False,
            conn=MagicMock(),
        )

        assert result["answer"] is None
        assert result["communities_used"] == 2
        assert result["community_hits"] == fake_hits

    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_no_hits_returns_build_message(self, mock_search, mock_config):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg

        mock_search.return_value = []

        result = global_query(
            "test question",
            use_map_reduce=False,
            conn=MagicMock(),
        )

        assert "No community summaries found" in result["answer"]
        assert result["communities_used"] == 0
        assert result["community_hits"] == []


class TestGlobalQueryWorkspaceFilter:
    """Regression: workspace filter must match community_members.entity (note paths)
    directly, not via triples.subject/object (free-text entity names)."""

    def _make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE community_members (community_id INTEGER, entity TEXT)"
        )
        conn.executemany(
            "INSERT INTO community_members(community_id, entity) VALUES (?, ?)",
            [
                (1, "work/acme-cloud/projects/index.md"),
                (1, "work/acme-cloud/notes/foo.md"),
                (2, "home/recipes/lasagna.md"),
                (3, "research/cognition/attention.md"),
            ],
        )
        conn.commit()
        return conn

    def _hit(self, cid: int, title: str) -> dict:
        return {
            "community_id": cid,
            "level": 0,
            "title": title,
            "summary": f"summary {cid}",
            "entity_count": 2,
            "member_notes": "",
            "score": 0.9,
        }

    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_workspace_keeps_only_communities_with_members_under_prefix(
        self, mock_search, mock_config
    ):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg
        mock_search.return_value = [
            self._hit(1, "Acme"),
            self._hit(2, "Recipes"),
            self._hit(3, "Cognition"),
        ]

        result = global_query(
            "test",
            use_map_reduce=False,
            conn=self._make_conn(),
            workspace="work/acme-cloud",
        )

        assert result["communities_used"] == 1
        assert [h["community_id"] for h in result["community_hits"]] == [1]

    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_workspace_normalised_slashes(self, mock_search, mock_config):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg
        mock_search.return_value = [self._hit(1, "Acme"), self._hit(2, "Recipes")]

        result = global_query(
            "test",
            use_map_reduce=False,
            conn=self._make_conn(),
            workspace="/work/acme-cloud/",
        )

        assert [h["community_id"] for h in result["community_hits"]] == [1]

    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_no_workspace_returns_all_hits(self, mock_search, mock_config):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg
        mock_search.return_value = [self._hit(1, "Acme"), self._hit(2, "Recipes")]

        result = global_query(
            "test",
            use_map_reduce=False,
            conn=self._make_conn(),
        )

        assert [h["community_id"] for h in result["community_hits"]] == [1, 2]

    @patch("neurostack.community_search.get_config")
    @patch("neurostack.community_search.search_communities")
    def test_workspace_with_no_matches_returns_build_message(
        self, mock_search, mock_config
    ):
        cfg = MagicMock()
        cfg.embed_url = "http://localhost:11434"
        cfg.llm_url = "http://localhost:11434"
        cfg.llm_model = "phi3.5"
        mock_config.return_value = cfg
        mock_search.return_value = [self._hit(2, "Recipes")]

        result = global_query(
            "test",
            use_map_reduce=False,
            conn=self._make_conn(),
            workspace="work/acme-cloud",
        )

        assert result["communities_used"] == 0
        assert result["community_hits"] == []
