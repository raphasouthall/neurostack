"""Tests for the prediction-error detection branch and the gating that surfaces it.

The writer ``log_prediction_error`` (insert + rate-limit) is covered in test_search.py.
What's exercised here is the *decision* logic — when ``hybrid_search`` actually flags a
result (search.py detection branch) — plus the occurrence/similarity gates that decide
which flags get surfaced and which demote notes in later retrieval.

Style mirrors TestCooccurrenceBoost in test_search.py: a real in-memory sqlite DB with
``get_db``/``get_embedding`` monkeypatched, never MagicMock — see
[[community-workspace-filter-fix-2026-05-12]] for why that matters.
"""

import struct

import numpy as np
import pytest

from neurostack.search import (
    CONTEXTUAL_MISMATCH_MAX_SIM,
    PREDICTION_ERROR_MIN_OCCURRENCES,
    PREDICTION_ERROR_SIM_THRESHOLD,
    classify_retrieval_error,
    hybrid_search,
)

DIM = 768


def _emb(a: float, b: float, dim: int = DIM) -> bytes:
    """Embedding blob with components (a, b, 0, 0, ...).

    Against the query vector e0 = (1, 0, 0, ...) the cosine similarity is
    a / sqrt(a^2 + b^2); pick (a, b) on the unit circle and cosine == a.
    """
    v = [0.0] * dim
    v[0] = a
    v[1] = b
    return struct.pack(f"{dim}f", *v)


def _query_emb() -> np.ndarray:
    """Query vector e0 — cosine with _emb(a, b) is exactly a when a^2 + b^2 == 1."""
    q = np.zeros(DIM, dtype=np.float32)
    q[0] = 1.0
    return q


def _add_note(conn, path, *, content="predtoken body text", emb=None, title="N"):
    """Insert a note plus (optionally) a single chunk with an embedding."""
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
        (path, title, f"h_{path}", "2026-01-01"),
    )
    if emb is not None:
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
            "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (path, "## H", content, f"hc_{path}", 0, emb),
        )
    conn.commit()


def _patch_search(monkeypatch, conn):
    """Route hybrid_search at the in-memory conn and a deterministic query vector."""
    import neurostack.search as search_mod

    monkeypatch.setattr(search_mod, "get_db", lambda path: conn)
    monkeypatch.setattr(search_mod, "get_embedding", lambda q, base_url=None: _query_emb())


def _errors(conn, error_type=None):
    sql = "SELECT note_path, error_type, cosine_distance FROM prediction_errors"
    params: list = []
    if error_type:
        sql += " WHERE error_type = ?"
        params.append(error_type)
    return conn.execute(sql, params).fetchall()


# --- cosines chosen relative to the thresholds (a^2 + b^2 == 1, so cosine == a) ---
_LOW = (0.10, 0.99499)                  # sim 0.10  < 0.38  -> low_overlap
_STRONG = (0.95, 0.31225)               # sim 0.95  -> no flag at all
_BAND = (0.40, 0.91652)                 # sim 0.40  in [0.38, 0.45) -> contextual_mismatch
_MID = (0.60, 0.80)                     # sim 0.60  >= 0.45 -> NOT a contextual_mismatch


class TestLowOverlapDetection:
    def test_fires_below_threshold(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _add_note(conn, "stale.md", emb=_emb(*_LOW))
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake")

        # Nothing close was returned, so the query has no home in the vault.
        rows = _errors(conn, "coverage_gap")
        assert len(rows) == 1
        assert rows[0]["note_path"] == "stale.md"
        # distance stored is 1 - sim
        assert rows[0]["cosine_distance"] == pytest.approx(1.0 - _LOW[0], abs=1e-3)

    def test_no_flag_above_threshold(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _add_note(conn, "good.md", emb=_emb(*_STRONG))
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake")

        assert _errors(conn) == []

    def test_fts_only_hit_not_flagged(self, in_memory_db, monkeypatch):
        """A note that FTS-matches but has no chunk embedding is dropped before
        the rerank, so it never reaches the detection branch — no flag."""
        conn = in_memory_db
        _add_note(conn, "noembed.md", emb=None)
        # the note row alone has no chunk; give it an FTS-matchable chunk WITHOUT an embedding
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, position) "
            "VALUES (?, ?, ?, ?, ?)",
            ("noembed.md", "## H", "predtoken body text", "hc_noembed", 0),
        )
        conn.commit()
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake")

        assert _errors(conn) == []

    def test_only_top_result_checked(self, in_memory_db, monkeypatch):
        """Detection inspects deduped[0] only. A strong #1 result shields a weak
        #2 from being flagged."""
        conn = in_memory_db
        _add_note(conn, "winner.md", emb=_emb(*_STRONG))   # cosine 0.95 -> ranks #1
        _add_note(conn, "loser.md", emb=_emb(*_LOW))        # cosine 0.10 -> ranks #2
        _patch_search(monkeypatch, conn)

        results = hybrid_search("predtoken", top_k=5, embed_url="http://fake")

        assert results[0].note_path == "winner.md"
        assert _errors(conn) == []


class TestContextualMismatchDetection:
    def _setup(self, conn, target_emb):
        # decoy lives under the context substring -> populates in_context_notes
        _add_note(conn, "azure-decoy.md", emb=None, title="Decoy")
        # target FTS-matches the query, is NOT in the context set
        _add_note(conn, "target.md", emb=target_emb)

    def test_fires_in_weak_band(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        self._setup(conn, _emb(*_BAND))
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake", context="azure")

        rows = _errors(conn, "contextual_mismatch")
        assert len(rows) == 1
        assert rows[0]["note_path"] == "target.md"

    def test_suppressed_for_strong_hit(self, in_memory_db, monkeypatch):
        """The fix: a strong semantic hit outside the context boost set is NOT a
        mismatch. Without the CONTEXTUAL_MISMATCH_MAX_SIM ceiling this flagged
        correct retrievals (exact-title hits)."""
        conn = in_memory_db
        self._setup(conn, _emb(*_MID))   # sim 0.60 >= ceiling
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake", context="azure")

        assert _errors(conn) == []

    def test_no_context_no_mismatch(self, in_memory_db, monkeypatch):
        """Without a context argument the mismatch branch can't fire; a band-sim
        result above the low_overlap floor produces no flag at all."""
        conn = in_memory_db
        self._setup(conn, _emb(*_BAND))
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake")  # no context

        assert _errors(conn) == []


class TestSurfacingGate:
    """vault_prediction_errors surfaces a note only once it has surprised
    PREDICTION_ERROR_MIN_OCCURRENCES distinct retrieval events."""

    def _seed(self, conn, note, n):
        for i in range(n):
            conn.execute(
                "INSERT INTO prediction_errors (note_path, query, cosine_distance, error_type) "
                "VALUES (?, ?, ?, ?)",
                (note, f"q{i}", 0.7, "low_overlap"),
            )
        conn.commit()

    def test_single_occurrence_not_surfaced(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        self._seed(conn, "oneshot.md", 1)
        self._seed(conn, "recurrent.md", PREDICTION_ERROR_MIN_OCCURRENCES)

        import neurostack.schema as schema_mod
        from neurostack.tools.search_tools import vault_prediction_errors

        monkeypatch.setattr(schema_mod, "get_db", lambda path: conn)

        out = vault_prediction_errors()
        surfaced = {e["note_path"] for e in out["errors"]}

        assert "recurrent.md" in surfaced
        assert "oneshot.md" not in surfaced
        assert out["total_flagged_notes"] == 1


def test_thresholds_ordered():
    """Sanity: the mismatch ceiling sits above the low-overlap floor, leaving a
    real band for contextual_mismatch to occupy, and occurrences gate is >= 2."""
    assert PREDICTION_ERROR_SIM_THRESHOLD < CONTEXTUAL_MISMATCH_MAX_SIM < 1.0
    assert PREDICTION_ERROR_MIN_OCCURRENCES >= 2


class TestGapVersusMisfit:
    """A distant top hit means either "no note fits" or "ranking misfired".
    Those need different fixes, so they are recorded as different types."""

    def test_all_results_distant_is_a_coverage_gap(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        _add_note(conn, "far-a.md", emb=_emb(*_LOW))
        _add_note(conn, "far-b.md", emb=_emb(0.12, 0.99277))
        _patch_search(monkeypatch, conn)

        hybrid_search("predtoken", top_k=5, embed_url="http://fake")

        rows = _errors(conn)
        assert len(rows) == 1
        assert rows[0]["error_type"] == "coverage_gap"

    def test_close_note_ranked_below_a_distant_one_is_low_overlap(self):
        # Ranking, not the classifier, decides order; feed the two cosines it
        # would see when a closer note was returned below a distant winner.
        assert classify_retrieval_error(0.10, 0.95) == "low_overlap"

    def test_nothing_close_anywhere_is_a_gap(self):
        assert classify_retrieval_error(0.10, 0.12) == "coverage_gap"

    def test_close_top_hit_is_not_flagged(self):
        assert classify_retrieval_error(0.95, 0.95) is None

    def test_out_of_context_top_hit_in_the_band_is_a_mismatch(self):
        assert classify_retrieval_error(0.40, 0.40, top_in_context=False) == (
            "contextual_mismatch")

    def test_no_context_means_no_mismatch_flag(self):
        assert classify_retrieval_error(0.40, 0.40, top_in_context=None) is None


class TestVerify:
    """Flags are frozen observations. Re-indexing or a new note can make them
    wrong, and nothing re-checked them, so the report filled with noise."""

    class _Args:
        json = False
        verify = True

    def _verify(self, conn, monkeypatch, results_by_query):
        import neurostack.cli.search as cli_search

        class R:
            def __init__(self, path):
                self.note_path = path

        monkeypatch.setattr(
            cli_search, "cmd_prediction_errors", cli_search.cmd_prediction_errors)
        import neurostack.search as search_mod
        monkeypatch.setattr(
            search_mod, "hybrid_search",
            lambda q, **kw: [R(p) for p in results_by_query.get(q, [])])
        cli_search._verify_prediction_errors(conn, self._Args())

    def test_flag_whose_note_no_longer_tops_the_query_is_resolved(
        self, in_memory_db, monkeypatch, capsys
    ):
        conn = in_memory_db
        conn.execute(
            "INSERT INTO prediction_errors (note_path, query, cosine_distance, error_type)"
            " VALUES ('index.md', 'herdr restart omp', 0.71, 'low_overlap')")
        conn.commit()

        self._verify(conn, monkeypatch, {"herdr restart omp": ["oh-my-pi-setup.md"]})

        row = conn.execute(
            "SELECT resolved_at FROM prediction_errors").fetchone()
        assert row["resolved_at"] is not None
        assert "oh-my-pi-setup.md" in capsys.readouterr().out

    def test_reproducing_flag_is_kept(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        conn.execute(
            "INSERT INTO prediction_errors (note_path, query, cosine_distance, error_type)"
            " VALUES ('stale.md', 'some query', 0.71, 'coverage_gap')")
        conn.commit()

        self._verify(conn, monkeypatch, {"some query": ["stale.md", "other.md"]})

        row = conn.execute("SELECT resolved_at FROM prediction_errors").fetchone()
        assert row["resolved_at"] is None

    def test_memory_drift_flags_are_left_alone(self, in_memory_db, monkeypatch):
        conn = in_memory_db
        conn.execute("INSERT INTO memories (content, entity_type) VALUES ('m', 'observation')")
        mid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute(
            "INSERT INTO prediction_errors (note_path, memory_id, query, cosine_distance,"
            " error_type) VALUES ('a.md', ?, 'q', 0.8, 'memory_drift')", (mid,))
        conn.commit()

        self._verify(conn, monkeypatch, {})

        row = conn.execute("SELECT resolved_at FROM prediction_errors").fetchone()
        assert row["resolved_at"] is None
