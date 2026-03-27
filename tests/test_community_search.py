"""Tests for neurostack.community_search — cache key hashing and global_query."""

import hashlib
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
