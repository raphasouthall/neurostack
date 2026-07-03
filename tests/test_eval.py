"""Tests for neurostack.eval — the retrieval benchmark + ablation harness (#63).

Two layers:
  * pure metric functions (recall@k / MRR / NDCG / match rule) on hand-built
    rankings — no DB, no embeddings;
  * an end-to-end run over a tiny on-disk corpus with deterministic embeddings
    and an injected query-embedding cache, so the whole harness exercises
    ``hybrid_search`` offline (no Ollama) and stays side-effect-free.
"""

from pathlib import Path

import numpy as np
import pytest

from neurostack.embedder import embedding_to_blob
from neurostack.eval import (
    EvalQuery,
    configs,
    load_queries,
    matches,
    mrr,
    ndcg_at_k,
    recall_at_k,
    run_eval,
)
from neurostack.schema import get_db
from neurostack.search import ABLATABLE_SIGNALS

# ── pure metric functions ──────────────────────────────────────────────────


class TestMatchRule:
    # Synthetic paths only — these assert the match rule, not any real vault.
    def test_prefix_match(self):
        assert matches("guides/database-pooling.md", "guides/database-pooling")

    def test_directory_target(self):
        assert matches("projects/example/setup.md", "projects/example")

    def test_substring_match(self):
        assert matches("ops/x/data-export/data-export.md", "data-export")

    def test_case_insensitive(self):
        assert matches("Guides/Setup/Foo.md", "guides/setup/foo")

    def test_no_match(self):
        assert not matches("guides/database-pooling.md", "ops/backup-restore")


class TestRecall:
    def test_hit_in_topk(self):
        ranked = ["a.md", "target.md", "c.md"]
        assert recall_at_k(ranked, ["target"], k=5) == 1.0

    def test_miss_outside_k(self):
        ranked = ["a.md", "b.md", "target.md"]
        assert recall_at_k(ranked, ["target"], k=2) == 0.0

    def test_partial_multi_target(self):
        ranked = ["one.md", "x.md"]
        assert recall_at_k(ranked, ["one", "two"], k=5) == 0.5

    def test_no_targets(self):
        assert recall_at_k(["a.md"], [], k=5) == 0.0


class TestMRR:
    def test_first_rank(self):
        assert mrr(["target.md", "b.md"], ["target"]) == 1.0

    def test_third_rank(self):
        assert mrr(["a.md", "b.md", "target.md"], ["target"]) == pytest.approx(1 / 3)

    def test_none_found(self):
        assert mrr(["a.md", "b.md"], ["target"]) == 0.0


class TestNDCG:
    def test_ideal_ranking(self):
        # single relevant doc at rank 1 → perfect
        assert ndcg_at_k(["target.md", "b.md", "c.md"], ["target"], k=5) == pytest.approx(1.0)

    def test_demoted_relevant(self):
        # relevant at rank 2 → 1/log2(3) discounted, idcg = 1.0
        got = ndcg_at_k(["a.md", "target.md"], ["target"], k=5)
        assert got == pytest.approx(1.0 / np.log2(3))

    def test_none_relevant(self):
        assert ndcg_at_k(["a.md", "b.md"], ["target"], k=5) == 0.0


# ── labelled query set ships and parses ────────────────────────────────────


def test_sample_query_set_loads():
    # Only the public synthetic sample ships; real labels are vault-specific and
    # gitignored (generate them with `neurostack eval --autolabel`).
    path = Path(__file__).parent / "eval" / "queries.sample.yaml"
    queries = load_queries(path)
    assert queries, "queries.sample.yaml should ship as the format template"
    for q in queries:
        assert q.query
        assert q.targets, f"{q.query!r} has no target"
        assert q.category in {"pinpoint", "thematic", "crossref", "adversarial"}


def test_configs_cover_every_signal():
    names = configs()
    assert names[0][0] == "full" and names[0][1] == set()
    ablated = {c[0] for c in names[1:]}
    assert ablated == {f"-{s}" for s in ABLATABLE_SIGNALS}


# ── end-to-end over a synthetic corpus ─────────────────────────────────────

FRUITS = ["apple", "banana", "cherry", "date"]


def _unit(i: int, dim: int = 4) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture
def eval_corpus(tmp_path):
    """A 4-note on-disk vault: each note is a distinct fruit with a near-
    orthogonal embedding, all sharing 'fruit harvest' vocabulary so FTS returns
    every note and the cosine rerank (plus signals) decides the order."""
    db_file = tmp_path / "eval.db"
    conn = get_db(db_file)
    for i, fruit in enumerate(FRUITS):
        path = f"notes/{fruit}.md"
        content = f"{fruit} fruit harvest notes. The {fruit} orchard season report."
        conn.execute(
            "INSERT INTO notes (path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (path, fruit.title(), "{}", "h", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO chunks (note_path, heading_path, content, content_hash, "
            "position, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (path, "", content, "h", 0, embedding_to_blob(_unit(i))),
        )
        conn.execute(
            "INSERT INTO note_metadata (note_path, status) VALUES (?, 'active')",
            (path,),
        )
    conn.commit()
    conn.close()

    # Query per fruit; cached embedding points mostly at that fruit's axis.
    queries = []
    cache = {}
    for i, fruit in enumerate(FRUITS):
        q = f"{fruit} fruit harvest"
        queries.append(EvalQuery(query=q, targets=[f"notes/{fruit}"], category="pinpoint"))
        vec = _unit(i) * 0.9 + np.full(4, 0.05, dtype=np.float32)
        cache[q] = [float(x) for x in vec]
    return db_file, queries, cache


def test_run_eval_full_finds_targets(eval_corpus):
    db_file, queries, cache = eval_corpus
    rows = run_eval(queries, db_path=db_file, k=5, cache=cache, ablation=False)
    full = rows[0]
    assert full.name == "full"
    # deterministic space: every query's own fruit is the nearest note
    assert full.recall == pytest.approx(1.0)
    assert full.mrr == pytest.approx(1.0)


def test_ablation_produces_a_row_per_signal(eval_corpus):
    db_file, queries, cache = eval_corpus
    rows = run_eval(queries, db_path=db_file, k=5, cache=cache, ablation=True)
    assert len(rows) == 1 + len(ABLATABLE_SIGNALS)
    names = {r.name for r in rows}
    assert names == {"full"} | {f"-{s}" for s in ABLATABLE_SIGNALS}
    for r in rows:
        assert 0.0 <= r.recall <= 1.0
        assert 0.0 <= r.mrr <= 1.0
        assert 0.0 <= r.ndcg <= 1.0


def test_eval_is_side_effect_free(eval_corpus):
    """record=False must not write usage rows — else an ablation sweep would
    poison hotness for every configuration after the first."""
    db_file, queries, cache = eval_corpus
    run_eval(queries, db_path=db_file, k=5, cache=cache, ablation=True)
    conn = get_db(db_file)
    usage = conn.execute("SELECT COUNT(*) FROM note_usage").fetchone()[0]
    errors = conn.execute("SELECT COUNT(*) FROM prediction_errors").fetchone()[0]
    conn.close()
    assert usage == 0
    assert errors == 0


def test_missing_cached_embedding_raises(eval_corpus):
    db_file, queries, _ = eval_corpus
    with pytest.raises(KeyError, match="No cached embedding"):
        run_eval(queries, db_path=db_file, k=5, cache={}, ablation=False)
