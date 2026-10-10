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


def test_repeated_fact_renders_once():
    # The live index held one fact five times over for one note (#320).
    reply = {"triples": [_triple("a.md", "s1")] * 5 + [_triple("a.md", "s2")]}
    text = render("vault_triples", reply)
    assert text.count("- s1 → uses → x") == 1
    assert "- s2 → uses → x" in text


def test_read_file_sends_the_note_as_markdown():
    note = "---\ntitle: \"A\"\n---\n# A\n\nBody.\n"
    reply = {"path": "a.md", "exists": True, "size_bytes": len(note), "content": note}
    head, body = render("vault_read_file", reply).split("\n", 1)
    assert "a.md" in head and str(len(note)) in head
    assert body == note


def test_read_file_page_names_the_next_offset():
    reply = {"path": "a.md", "exists": True, "size_bytes": 10, "size_chars": 10,
             "offset": 2, "content": "234", "truncated": True}
    head, body = render("vault_read_file", reply).split("\n", 1)
    assert "next offset 5" in head
    assert body == "234"


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
