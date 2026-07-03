"""Tests for community-partition staleness reporting + gated rebuild (issue #65)."""

from datetime import datetime, timedelta, timezone

import pytest

from neurostack.community import community_build_status, maybe_rebuild_communities


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_notes(conn, n: int, updated_at: str):
    for i in range(n):
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            (f"notes/n{i}.md", f"N{i}", "h", updated_at),
        )


def _seed_build(conn, built_at: str, level_stats=True):
    conn.execute(
        "INSERT INTO communities (level, title, summary, updated_at) VALUES (0, 'C', 's', ?)",
        (built_at,),
    )
    if level_stats:
        conn.execute(
            "INSERT INTO community_level_stats "
            "(level, n_communities, min_size, max_size, mean_size, modularity, updated_at) "
            "VALUES (0, 1, 1, 1, 1.0, 0.3, ?)",
            (built_at,),
        )


class TestCommunityBuildStatus:
    def test_never_built(self, in_memory_db):
        _seed_notes(in_memory_db, 5, _iso(datetime.now(timezone.utc)))
        in_memory_db.commit()
        s = community_build_status(in_memory_db)
        assert s["built"] is False
        assert s["stale"] is True
        assert "never built" in s["reason"]

    def test_fresh_partition(self, in_memory_db):
        now = datetime.now(timezone.utc)
        # notes updated before the build; build is recent → not stale
        _seed_notes(in_memory_db, 10, _iso(now - timedelta(days=1)))
        _seed_build(in_memory_db, _iso(now))
        in_memory_db.commit()
        s = community_build_status(in_memory_db)
        assert s["built"] is True
        assert s["stale"] is False
        assert s["notes_changed_since"] == 0
        assert s["drift"] == 0.0

    def test_stale_by_age(self, in_memory_db):
        now = datetime.now(timezone.utc)
        _seed_notes(in_memory_db, 10, _iso(now - timedelta(days=40)))
        _seed_build(in_memory_db, _iso(now - timedelta(days=30)))  # > 14d default
        in_memory_db.commit()
        s = community_build_status(in_memory_db)
        assert s["stale"] is True
        assert s["age_days"] > 14
        assert "old" in s["reason"]

    def test_stale_by_drift(self, in_memory_db):
        now = datetime.now(timezone.utc)
        built = now - timedelta(days=1)
        # 8 old + 2 changed-after-build of 10 = 20% drift > 10% default
        _seed_notes(in_memory_db, 8, _iso(built - timedelta(days=1)))
        for i in range(2):
            in_memory_db.execute(
                "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
                (f"notes/new{i}.md", "new", "h", _iso(now)),
            )
        _seed_build(in_memory_db, _iso(built))
        in_memory_db.commit()
        s = community_build_status(in_memory_db)
        assert s["notes_changed_since"] == 2
        assert s["drift"] == pytest.approx(0.2)
        assert s["stale"] is True
        assert "drift" in s["reason"]

    def test_falls_back_to_communities_timestamp(self, in_memory_db):
        now = datetime.now(timezone.utc)
        _seed_notes(in_memory_db, 5, _iso(now - timedelta(days=1)))
        _seed_build(in_memory_db, _iso(now), level_stats=False)  # only communities row
        in_memory_db.commit()
        s = community_build_status(in_memory_db)
        assert s["built"] is True
        assert s["last_built"] is not None


class TestMaybeRebuild:
    def test_fresh_no_ops(self, in_memory_db, monkeypatch):
        now = datetime.now(timezone.utc)
        _seed_notes(in_memory_db, 10, _iso(now - timedelta(days=1)))
        _seed_build(in_memory_db, _iso(now))
        in_memory_db.commit()

        called = {"detect": False}

        def _detect(conn=None, db_path=None):
            called["detect"] = True
            return (1, 1)

        monkeypatch.setattr("neurostack.attractor.detect_communities", _detect)
        out = maybe_rebuild_communities(in_memory_db)
        assert out["rebuilt"] is False
        assert called["detect"] is False

    def test_force_rebuilds(self, in_memory_db, monkeypatch):
        now = datetime.now(timezone.utc)
        _seed_notes(in_memory_db, 10, _iso(now - timedelta(days=1)))
        _seed_build(in_memory_db, _iso(now))
        in_memory_db.commit()

        def _detect(conn=None, db_path=None):
            return (3, 5)

        monkeypatch.setattr("neurostack.attractor.detect_communities", _detect)
        monkeypatch.setattr(
            "neurostack.community.summarize_all_communities",
            lambda *a, **k: None,
        )
        out = maybe_rebuild_communities(in_memory_db, force=True)
        assert out["rebuilt"] is True
        assert out["coarse"] == 3 and out["fine"] == 5
        assert out["trigger"] == "force"

    def test_stale_rebuilds(self, in_memory_db, monkeypatch):
        now = datetime.now(timezone.utc)
        _seed_notes(in_memory_db, 10, _iso(now - timedelta(days=40)))
        _seed_build(in_memory_db, _iso(now - timedelta(days=30)))
        in_memory_db.commit()

        monkeypatch.setattr(
            "neurostack.attractor.detect_communities",
            lambda conn=None, db_path=None: (2, 4),
        )
        monkeypatch.setattr(
            "neurostack.community.summarize_all_communities",
            lambda *a, **k: None,
        )
        out = maybe_rebuild_communities(in_memory_db)
        assert out["rebuilt"] is True
        assert "old" in out["trigger"]
