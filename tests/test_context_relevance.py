"""vault_context leaves out weak hits and bookkeeping clutter (issue #316).

The auto-RAG hook injects this output on every prompt, so an off-topic triple
or a session id costs the reader attention for nothing.
"""

import json
import re

import pydantic_core

from neurostack.cli.hook import _fence
from neurostack.context import build_vault_context
from neurostack.memories import Memory
from neurostack.search import TripleResult


def _memory(memory_id, content, score, tags=(), created_at="2026-10-10 13:03:44"):
    return Memory(
        memory_id=memory_id, content=content, tags=list(tags), entity_type="decision",
        source_agent=None, workspace=None, created_at=created_at, expires_at=None,
        score=score,
    )


def _triple(subject, score):
    return TripleResult(note_path=f"{subject}.md", subject=subject, predicate="is",
                        object="thing", score=score)


def _serve(monkeypatch, memories=(), triples=()):
    import neurostack.memories as memories_mod
    import neurostack.search as search_mod

    monkeypatch.setattr(memories_mod, "search_memories", lambda *a, **k: list(memories))
    monkeypatch.setattr(search_mod, "search_triples", lambda *a, **k: list(triples))
    monkeypatch.setattr(search_mod, "hybrid_search", lambda *a, **k: [])


def test_weak_hits_left_out_best_kept(in_memory_db, monkeypatch):
    _serve(
        monkeypatch,
        memories=[_memory(1, "search ranking weights", 0.80),
                  _memory(2, "search page shipped", 0.78),
                  _memory(3, "a blogger's posting schedule", 0.50)],
        triples=[_triple("search results", 0.70),
                 _triple("vault_search", 0.68),
                 _triple("One Outbound", 0.40)],
    )

    ctx = build_vault_context(in_memory_db, task="improve search UX")["context"]

    assert [m["memory_id"] for m in ctx["memories"]] == [1, 2]
    assert [t["s"] for t in ctx["triples"]] == ["search results", "vault_search"]


def test_lone_weak_hit_still_shown(in_memory_db, monkeypatch):
    _serve(monkeypatch, memories=[_memory(1, "only match", 0.2)],
           triples=[_triple("only triple", 0.1)])

    ctx = build_vault_context(in_memory_db, task="anything")["context"]

    assert [m["memory_id"] for m in ctx["memories"]] == [1]
    assert [t["s"] for t in ctx["triples"]] == ["only triple"]


def test_unscored_hits_not_filtered(in_memory_db, monkeypatch):
    """Keyword-only fallbacks carry no score; there is nothing to compare."""
    _serve(monkeypatch, triples=[_triple("a", 0.0), _triple("b", 0.0)])

    ctx = build_vault_context(in_memory_db, task="anything")["context"]

    assert [t["s"] for t in ctx["triples"]] == ["a", "b"]


def test_no_bookkeeping_or_escaping(in_memory_db, monkeypatch):
    content = 'use <tenant> & "scope" flags'
    _serve(monkeypatch, memories=[_memory(
        1, content, 0.9,
        tags=["azure", "session:01a0", "when-calling:az login",
              "superseded_by:4801", "promoted", "promoted-2026-09-11"],
    )])

    memory = build_vault_context(in_memory_db, task="az login")["context"]["memories"][0]

    assert memory["tags"] == ["azure"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", memory["created_at"])
    # The server's JSON keeps the text raw and the hook escapes it once.
    text = pydantic_core.to_json(memory, indent=2).decode()
    assert json.loads(text)["content"] == content
    fenced = _fence(text)
    assert "&lt;tenant&gt; &amp;" in fenced
    assert "&amp;lt;" not in fenced
