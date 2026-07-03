"""Tests for neurostack.tune — coordinate-ascent weight tuning (issue #66).

Three layers:
  * ascent *mechanics* with a synthetic objective (monkeypatched) — no DB, so the
    accept / decline / convergence logic is tested in isolation;
  * the split helper and the input guards;
  * a faithfulness pass on a real corpus proving the parametrized blends in
    hybrid_search reduce to the old behaviour at their defaults, and to the
    ablation no-op at weight 0.
"""

import numpy as np
import pytest

from neurostack import tune
from neurostack.config import RankingWeights
from neurostack.embedder import embedding_to_blob
from neurostack.eval import EvalQuery, cached_query_embeddings
from neurostack.schema import get_db
from neurostack.search import hybrid_search

# ── ascent mechanics (synthetic objective, no DB) ──────────────────────────


def test_coordinate_ascent_moves_toward_optimum(monkeypatch):
    # Objective peaks at convergence_weight = 0.45 (a grid point), flat elsewhere.
    def fake_eval(queries, w, *, db_path, k, metric, embed_url=None):
        return 1.0 - abs(w.convergence_weight - 0.45)

    monkeypatch.setattr(tune, "evaluate_weights", fake_eval)
    res = tune.coordinate_ascent(
        [EvalQuery("q", ["t"])], db_path=None, metric="ndcg", cache=None
    )
    assert res.best_weights.convergence_weight == 0.45
    assert res.best_score > res.baseline_score
    assert res.changed_params == {"convergence_weight": (0.3, 0.45)}
    assert res.n_evals > 0


def test_coordinate_ascent_declines_when_baseline_optimal(monkeypatch):
    # Flat objective: no candidate beats the baseline, so nothing is accepted and
    # the ascent stops after a single unproductive round.
    monkeypatch.setattr(tune, "evaluate_weights", lambda *a, **k: 0.5)
    res = tune.coordinate_ascent([EvalQuery("q", ["t"])], db_path=None, cache=None)
    assert not res.improved
    assert res.changed_params == {}
    assert res.rounds == 1


def test_coordinate_ascent_reports_baseline_score(monkeypatch):
    monkeypatch.setattr(tune, "evaluate_weights", lambda *a, **k: 0.73)
    res = tune.coordinate_ascent([EvalQuery("q", ["t"])], db_path=None, cache=None)
    assert res.baseline_score == pytest.approx(0.73)
    assert res.best_score == pytest.approx(0.73)


def test_bad_metric_raises():
    with pytest.raises(ValueError, match="metric must be one of"):
        tune.coordinate_ascent(
            [EvalQuery("q", ["t"])], db_path=None, metric="f1", cache=None
        )


def test_cache_coverage_guard():
    # A query with no cached embedding must fail loud, not silently degrade to
    # FTS-only mid-sweep (the same guarantee run_eval gives).
    with pytest.raises(KeyError, match="No cached embedding"):
        tune.coordinate_ascent(
            [EvalQuery("uncached", ["t"])], db_path=None, cache={}, metric="ndcg"
        )


# ── split helper ───────────────────────────────────────────────────────────


def test_interleaved_split_even_odd():
    qs = [EvalQuery(f"q{i}", ["t"]) for i in range(5)]
    train, test = tune.interleaved_split(qs)
    assert [q.query for q in train] == ["q0", "q2", "q4"]
    assert [q.query for q in test] == ["q1", "q3"]


# ── faithfulness on a real corpus ──────────────────────────────────────────

DIM = 6


def _axis(i: int, scale: float = 1.0) -> np.ndarray:
    v = np.full(DIM, 0.03, dtype=np.float32)
    v[i] = scale
    return v


@pytest.fixture
def signal_corpus(tmp_path):
    """A corpus that actually fires the parametrized signals:

    * ``alpha`` has 3 chunks with slightly varied embeddings → the convergence
      stage computes a real blend rather than short-circuiting on a single chunk;
    * ``beta`` carries recorded usage → the hotness blend is non-zero;
    * all notes share FTS vocabulary so the pre-filter returns every note and the
      signals decide the order.
    """
    db_file = tmp_path / "signal.db"
    conn = get_db(db_file)

    def _add_note(path, title, chunk_vecs):
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, '{}', 'h', '2026-01-01T00:00:00+00:00')",
            (path, title),
        )
        for pos, vec in enumerate(chunk_vecs):
            conn.execute(
                "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
                "position, embedding) VALUES (?, ?, ?, 'h', ?, ?)",
                (path, "", "signal ranking probe body text", pos,
                 embedding_to_blob(vec)),
            )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, 'active')",
            (path,),
        )

    _add_note("notes/alpha.md", "Alpha",
              [_axis(0), _axis(0, 0.85) + _axis(2, 0.2), _axis(0, 0.7) + _axis(3, 0.25)])
    _add_note("notes/beta.md", "Beta", [_axis(0, 0.9)])
    _add_note("notes/gamma.md", "Gamma", [_axis(1)])

    # Give beta recorded usage so its hotness blend is non-trivial.
    for _ in range(4):
        conn.execute("INSERT INTO note_usage (note_path) VALUES ('notes/beta.md')")
    conn.commit()
    conn.close()

    query = "signal ranking probe alpha"
    qvec = [float(x) for x in _axis(0, 0.95)]
    return db_file, query, {query: qvec}


def _scores(db_file, query, cache, **kwargs):
    """Final per-note scores for one hybrid_search config, record-free."""
    with cached_query_embeddings(cache):
        results = hybrid_search(
            query, top_k=10, db_path=db_file, record=False, **kwargs
        )
    return {r.note_path: round(r.score, 6) for r in results}


def test_none_weights_equal_explicit_defaults(signal_corpus):
    db_file, query, cache = signal_corpus
    a = _scores(db_file, query, cache, weights=None)
    b = _scores(db_file, query, cache, weights=RankingWeights())
    assert a == b
    assert len(a) == 3  # all three notes surfaced, so the blends really ran


def test_convergence_weight_zero_equals_ablation(signal_corpus):
    # Blending in 0×convergence must be identical to skipping the stage entirely.
    db_file, query, cache = signal_corpus
    zeroed = _scores(db_file, query, cache, weights=RankingWeights(convergence_weight=0.0))
    ablated = _scores(db_file, query, cache, ablate={"convergence"})
    assert zeroed == ablated


def test_hotness_weight_zero_equals_ablation(signal_corpus):
    db_file, query, cache = signal_corpus
    zeroed = _scores(db_file, query, cache, weights=RankingWeights(hotness_weight=0.0))
    ablated = _scores(db_file, query, cache, ablate={"hotness"})
    assert zeroed == ablated


def test_default_weights_differ_from_zeroed_signals(signal_corpus):
    # Sanity: the signals are live on this corpus, so zeroing them actually moves
    # scores — otherwise the equivalence tests above would be vacuous.
    db_file, query, cache = signal_corpus
    default = _scores(db_file, query, cache, weights=RankingWeights())
    no_conv = _scores(db_file, query, cache, weights=RankingWeights(convergence_weight=0.0))
    no_hot = _scores(db_file, query, cache, weights=RankingWeights(hotness_weight=0.0))
    assert default != no_conv or default != no_hot


def test_coordinate_ascent_end_to_end(signal_corpus):
    # The real evaluate_config path, offline via the cache: must run, stay in
    # range, and never return worse than baseline.
    db_file, query, cache = signal_corpus
    queries = [EvalQuery(query, ["notes/alpha"], category="pinpoint")]
    res = tune.coordinate_ascent(
        queries, db_path=db_file, k=5, cache=cache, metric="ndcg"
    )
    assert res.n_evals > 0
    assert res.best_score >= res.baseline_score
    assert 0.0 <= res.best_score <= 1.0
