# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Markdown renderings of MCP tool replies (issue #318)."""

import json

from neurostack.tools.render import render


def _triple(note, s):
    return {"note": note, "title": note.upper(), "s": s, "p": "uses", "o": "x",
            "score": 0.91234}


def test_triples_are_grouped_under_one_heading_per_note():
    reply = {"triples": [_triple("a.md", "s1"), _triple("b.md", "s2"), _triple("a.md", "s3")]}
    text = render("vault_triples", reply)
    assert text.count("### A.MD (a.md)") == 1
    assert text.count("### B.MD (b.md)") == 1
    # Both of a.md's facts sit under its heading, before b.md starts.
    block_a = text.split("### B.MD")[0]
    assert "- s1 → uses → x" in block_a and "- s3 → uses → x" in block_a
    assert "0.91234" not in text


def test_memory_drops_bookkeeping_tags_and_keeps_topics():
    reply = {"memories": [{
        "memory_id": 8252, "content": "Picked SQLite.", "entity_type": "decision",
        "tags": ["storage", "session:41", "promoted", "when-editing:db.py"],
        "created_at": "2026-10-08T12:00:00", "workspace": "home/projects/neurostack",
        "source_agent": "claude-code", "score": 0.73123,
    }]}
    lines = render("vault_memories", reply).splitlines()
    assert lines[0] == "#8252 decision · 2026-10-08 · home/projects/neurostack"
    assert lines[1] == "Picked SQLite."
    assert lines[2] == "tags: storage"
    assert len(lines) == 3


def test_truncated_reply_ends_by_pointing_at_max_tokens():
    reply = {"depth_used": "summaries", "triples": [], "chunks": [], "truncated": True,
             "summaries": [{"note": "a.md", "title": "A", "summary": "About A.", "score": 0.5}]}
    text = render("vault_search", reply)
    assert "### A (a.md)\nAbout A." in text
    assert "max_tokens" in text.splitlines()[-1]


def test_error_reply_is_one_line():
    assert render("vault_summary", {"error": "Note not found"}) == "Error: Note not found"


def test_unknown_shape_falls_back_to_compact_json():
    reply = {"surprise": [1, 2]}
    text = render("vault_search", reply)
    assert json.loads(text) == reply
    assert "\n" not in text
