"""Tests for observation -> learning synthesis (issue #36) — aged observation
heaps -> embedding clusters -> LLM synthesis -> one learning, originals tagged.

The LLM is a seam (monkeypatched); candidate selection, clustering, cap,
supersede tagging, ratio accounting, and failure isolation are exercised for
real against an in-memory DB.
"""

import json
import struct

import numpy as np
import pytest

import neurostack.synthesize as synth_mod
from neurostack.synthesize import (
    SIBLING_THRESHOLD,
    _cluster_tags,
    _strip_fences,
    cluster_observations,
    observation_learning_ratio,
    synthesize_observations,
)

DIM = 768


def _emb(*components) -> bytes:
    v = [0.0] * DIM
    for i, c in enumerate(components):
        v[i] = c
    return struct.pack(f"{DIM}f", *v)


def _add_memory(conn, content, emb=None, *, entity_type="observation",
                tags=None, workspace=None, age_days=30, expires_at=None):
    cur = conn.execute(
        "INSERT INTO memories (content, entity_type, tags, workspace,"
        " embedding, expires_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?))",
        (content, entity_type, json.dumps(tags or []), workspace, emb,
         expires_at, f"-{age_days} days"),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture
def heap_db(in_memory_db):
    """The acceptance scenario: 7 observations + 2 learnings (3.5:1).

    Four observations share a topic axis (pairwise cosine 1.0), three are
    mutually orthogonal singles — one cluster of 4, nothing else groups.
    """
    conn = in_memory_db
    cluster = [
        _add_memory(conn, f"AKS upgrade step {i} needs the node pool drained",
                    _emb(1.0), tags=["aks", f"t{i}"], workspace="work")
        for i in range(4)
    ]
    singles = [
        _add_memory(conn, "LXC 127 pins num_thread=1", _emb(0.0, 1.0),
                    workspace="homelab"),
        _add_memory(conn, "haproxy cold start takes minutes", _emb(0.0, 0.0, 1.0)),
        _add_memory(conn, "ruff needs the dev extra", _emb(0.0, 0.0, 0.0, 1.0)),
    ]
    for i in range(2):
        _add_memory(conn, f"learning {i}", entity_type="learning")
    return conn, cluster, singles


def _fake_embed(*args, **kwargs):
    return np.array([0.5] * DIM, dtype=np.float32)


class TestHelpers:
    def test_strip_fences(self):
        raw = "<think>hmm</think>```markdown\nthe learning\n```"
        assert _strip_fences(raw) == "the learning"

    def test_cluster_tags_union_ranked_and_marked(self):
        members = [
            {"tags": json.dumps(["aks", "azure", "superseded_by:9", ""])},
            {"tags": json.dumps(["aks", "  "])},
            {"tags": None},
        ]
        tags = _cluster_tags(members)
        assert tags == ["aks", "azure", "synthesized"]

    def test_ratio(self, heap_db):
        conn, *_ = heap_db
        ratio = observation_learning_ratio(conn)
        assert ratio == {"observations": 7, "learnings": 2, "ratio": 3.5}

    def test_ratio_no_learnings(self, in_memory_db):
        assert observation_learning_ratio(in_memory_db)["ratio"] is None


class TestCandidates:
    def test_only_aged_alive_unsuperseded_observations(self, in_memory_db):
        conn = in_memory_db
        ok = _add_memory(conn, "aged observation", _emb(1.0))
        _add_memory(conn, "too young", _emb(1.0), age_days=1)
        _add_memory(conn, "a decision", _emb(1.0), entity_type="decision")
        _add_memory(conn, "expired", _emb(1.0),
                    expires_at="2020-01-01 00:00:00")
        _add_memory(conn, "already superseded", _emb(1.0),
                    tags=["superseded_by:42"])
        rows = synth_mod._candidate_rows(conn, min_age_days=7)
        assert [r["memory_id"] for r in rows] == [ok]

    def test_null_tags_row_still_a_candidate(self, in_memory_db):
        # tags is a nullable column; NULL NOT LIKE excludes silently
        conn = in_memory_db
        cur = conn.execute(
            "INSERT INTO memories (content, entity_type, embedding, created_at)"
            " VALUES ('null tags row', 'observation', ?,"
            " datetime('now', '-30 days'))", (_emb(1.0),))
        conn.commit()
        rows = synth_mod._candidate_rows(conn, min_age_days=7)
        assert [r["memory_id"] for r in rows] == [cur.lastrowid]

    def test_workspace_scoping(self, in_memory_db):
        conn = in_memory_db
        w = _add_memory(conn, "in scope", _emb(1.0), workspace="work/acme")
        _add_memory(conn, "out of scope", _emb(1.0), workspace="homelab")
        rows = synth_mod._candidate_rows(conn, min_age_days=7, workspace="work")
        assert [r["memory_id"] for r in rows] == [w]


class TestClustering:
    def test_groups_topic_heap_ignores_singles(self, heap_db):
        conn, cluster_ids, _singles = heap_db
        clusters, no_emb = cluster_observations(conn)
        assert no_emb == 0
        assert len(clusters) == 1
        assert sorted(m["memory_id"] for m in clusters[0]["members"]) == cluster_ids
        assert clusters[0]["anchor_id"] == cluster_ids[0]  # oldest-first anchor

    def test_min_siblings_enforced(self, heap_db):
        conn, *_ = heap_db
        clusters, _ = cluster_observations(conn, min_siblings=4)
        assert clusters == []

    def test_missing_embeddings_counted_not_dropped(self, in_memory_db):
        conn = in_memory_db
        for i in range(4):
            _add_memory(conn, f"embedded {i}", _emb(1.0))
        _add_memory(conn, "no embedding")
        clusters, no_emb = cluster_observations(conn)
        assert no_emb == 1
        assert len(clusters) == 1

    def test_threshold_default_live_calibrated(self):
        assert SIBLING_THRESHOLD == 0.75

    def test_oversized_cluster_capped_keeps_anchor_and_most_similar(
            self, in_memory_db):
        conn = in_memory_db
        anchor = _add_memory(conn, "anchor", _emb(1.0))
        near = [_add_memory(conn, f"near {i}", _emb(1.0, 0.1))
                for i in range(2)]
        far = [_add_memory(conn, f"far {i}", _emb(1.0, 0.5))
               for i in range(3)]
        clusters, _ = cluster_observations(
            conn, threshold=0.6, max_cluster=3)
        assert len(clusters) == 1
        ids = [m["memory_id"] for m in clusters[0]["members"]]
        # anchor survives the cap; the closest members win the remaining slots
        assert ids == [anchor, *near]
        # overflow stays unassigned and regroups into its own cluster if it
        # can — here the three far rows form one (anchor + 2 siblings fails
        # min_siblings=3), so they were simply left for a later pass
        assert all(f not in ids for f in far)


class TestDryRun:
    def test_dry_run_plans_without_llm_or_writes(self, heap_db, monkeypatch):
        conn, cluster_ids, _ = heap_db

        def boom(*args, **kwargs):
            raise AssertionError("dry run must not call the LLM")
        monkeypatch.setattr(synth_mod, "_synthesize", boom)

        report = synthesize_observations(conn, dry_run=True)

        assert report["dry_run"] is True
        assert report["clusters_found"] == 1
        assert report["synthesized"] == [
            {"anchor_id": cluster_ids[0], "memory_ids": cluster_ids}]
        assert report["ratio_after"] == report["ratio_before"]
        assert conn.execute(
            "SELECT COUNT(*) FROM memories WHERE entity_type='learning'"
        ).fetchone()[0] == 2

    def test_cap_defers_extra_clusters(self, in_memory_db):
        conn = in_memory_db
        for axis in (1, 2):
            emb = _emb(*([0.0] * (axis - 1) + [1.0]))
            for i in range(4):
                _add_memory(conn, f"axis {axis} fact {i}", emb)
        report = synthesize_observations(conn, cap=1, dry_run=True)
        assert report["clusters_found"] == 2
        assert report["clusters_planned"] == 1
        assert len(report["deferred"]) == 1


class TestRealRun:
    def _patch_seams(self, monkeypatch, learning="AKS upgrades need drained pools"):
        import neurostack.embedder as embedder_mod
        monkeypatch.setattr(embedder_mod, "get_embedding", _fake_embed)
        monkeypatch.setattr(
            synth_mod, "_synthesize", lambda members, *a, **kw: learning)

    def test_run_saves_learning_and_tags_originals(self, heap_db, monkeypatch):
        conn, cluster_ids, singles = heap_db
        self._patch_seams(monkeypatch)

        report = synthesize_observations(conn, dry_run=False)

        assert len(report["synthesized"]) == 1
        plan = report["synthesized"][0]
        learning_id = plan["learning_id"]
        row = conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (learning_id,)
        ).fetchone()
        assert row["entity_type"] == "learning"
        assert row["content"] == "AKS upgrades need drained pools"
        assert row["workspace"] == "work"
        tags = json.loads(row["tags"])
        assert "aks" in tags and "synthesized" in tags

        # every original tagged, none deleted
        for mid in cluster_ids:
            orig = conn.execute(
                "SELECT tags FROM memories WHERE memory_id = ?", (mid,)
            ).fetchone()
            assert f"superseded_by:{learning_id}" in json.loads(orig["tags"])
        for mid in singles:
            orig = conn.execute(
                "SELECT tags FROM memories WHERE memory_id = ?", (mid,)
            ).fetchone()
            assert "superseded_by" not in (orig["tags"] or "")

    def test_ratio_reaches_acceptance_target(self, heap_db, monkeypatch):
        """Issue #36 acceptance: ~3.5:1 improves to <=2:1 after synthesis."""
        conn, *_ = heap_db
        self._patch_seams(monkeypatch)

        report = synthesize_observations(conn, dry_run=False)

        assert report["ratio_before"]["ratio"] == 3.5
        assert report["ratio_after"]["ratio"] <= 2.0

    def test_superseded_excluded_from_next_run(self, heap_db, monkeypatch):
        conn, *_ = heap_db
        self._patch_seams(monkeypatch)
        synthesize_observations(conn, dry_run=False)

        again = synthesize_observations(conn, dry_run=True)
        assert again["clusters_found"] == 0

    def test_synthesis_failure_isolated_per_cluster(self, in_memory_db,
                                                    monkeypatch):
        conn = in_memory_db
        for axis in (1, 2):
            emb = _emb(*([0.0] * (axis - 1) + [1.0]))
            for i in range(4):
                _add_memory(conn, f"axis {axis} fact {i}", emb)

        import neurostack.embedder as embedder_mod
        monkeypatch.setattr(embedder_mod, "get_embedding", _fake_embed)
        calls = {"n": 0}

        def flaky(members, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("model gibberish")
            return "the surviving learning"
        monkeypatch.setattr(synth_mod, "_synthesize", flaky)

        report = synthesize_observations(conn, dry_run=False)

        assert len(report["skipped"]) == 1
        assert "synthesis failed" in report["skipped"][0]["error"]
        assert len(report["synthesized"]) == 1
        # failed cluster's originals stay untagged
        failed_ids = report["skipped"][0]["memory_ids"]
        for mid in failed_ids:
            tags = conn.execute(
                "SELECT tags FROM memories WHERE memory_id = ?", (mid,)
            ).fetchone()["tags"]
            assert "superseded_by" not in tags


class TestIndexLlmCommand:
    """A subscription CLI has no HTTP endpoint, so the prompt goes to a shell
    command on stdin and the reply comes back on stdout (issue #184)."""

    def test_command_answers_instead_of_http(self):
        members = [{"memory_id": 1, "created_at": "2026-09-01", "content": "a fact"}]
        out = synth_mod._synthesize(
            members, "http://unused.invalid", "ignored",
            command="cat >/dev/null; printf 'the synthesised learning'",
        )
        assert out == "the synthesised learning"

    def test_command_receives_the_prompt_on_stdin(self, tmp_path):
        seen = tmp_path / "prompt.txt"
        members = [{"memory_id": 7, "created_at": "2026-09-01",
                    "content": "BASSnet needs 8000 MB"}]
        synth_mod._synthesize(
            members, "http://unused.invalid", "ignored",
            command=f"tee {seen} >/dev/null; printf 'ok'",
        )
        prompt = seen.read_text()
        assert "BASSnet needs 8000 MB" in prompt
        assert "memory 7" in prompt

    def test_a_failing_command_raises_so_the_cluster_is_skipped(self):
        members = [{"memory_id": 1, "created_at": "2026-09-01", "content": "a fact"}]
        with pytest.raises(RuntimeError, match="exited 3"):
            synth_mod._synthesize(
                members, "http://unused.invalid", "ignored",
                command="echo 'session limit reached' >&2; exit 3",
            )

    def test_an_empty_reply_still_raises(self):
        members = [{"memory_id": 1, "created_at": "2026-09-01", "content": "a fact"}]
        with pytest.raises(ValueError, match="empty synthesis"):
            synth_mod._synthesize(
                members, "http://unused.invalid", "ignored", command="true",
            )

    def test_fences_are_stripped_from_a_cli_reply(self):
        members = [{"memory_id": 1, "created_at": "2026-09-01", "content": "a fact"}]
        out = synth_mod._synthesize(
            members, "http://unused.invalid", "ignored",
            command="printf '```\\nthe learning\\n```'",
        )
        assert out == "the learning"


def test_config_reads_index_llm_command(tmp_path, monkeypatch):
    import neurostack.config as cfgmod
    path = tmp_path / "config.toml"
    path.write_text('index_llm_command = "claude -p --model haiku"\n'
                    'index_llm_command_timeout_s = 120\n')
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", path)
    cfgmod._config = None
    cfg = cfgmod.get_config()
    assert cfg.index_llm_command == "claude -p --model haiku"
    assert cfg.index_llm_command_timeout_s == 120.0
    cfgmod._config = None
