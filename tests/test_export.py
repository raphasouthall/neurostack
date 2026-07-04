# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Tests for neurostack.export — JSON index export (issue #4)."""

import argparse
import json

from neurostack.export import export_notes


def _add_note(conn, path, title, pagerank=None, summary=None):
    conn.execute(
        "INSERT INTO notes (path, title, content_hash, updated_at) "
        "VALUES (?, ?, ?, ?)",
        (path, title, "hash", "2026-01-01"),
    )
    if pagerank is not None:
        conn.execute(
            "INSERT INTO graph_stats (note_path, pagerank) VALUES (?, ?)",
            (path, pagerank),
        )
    if summary is not None:
        conn.execute(
            "INSERT INTO summaries (note_path, summary_text, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (path, summary, "hash", "2026-01-01"),
        )
    conn.commit()


def _add_triple(conn, note_path, subject, predicate, obj):
    conn.execute(
        "INSERT INTO triples (note_path, subject, predicate, object, triple_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (note_path, subject, predicate, obj, f"{subject} {predicate} {obj}"),
    )
    conn.commit()


def test_export_basic(in_memory_db):
    """Each note exports path, title, pagerank, summary."""
    conn = in_memory_db
    _add_note(conn, "a.md", "Note A", pagerank=0.42, summary="Summary of A")
    _add_note(conn, "b.md", "Note B")

    notes = export_notes(conn)

    assert [n["path"] for n in notes] == ["a.md", "b.md"]
    a, b = notes
    assert a == {
        "path": "a.md",
        "title": "Note A",
        "pagerank": 0.42,
        "summary": "Summary of A",
    }
    # No graph stats / summary computed → defaults
    assert b["pagerank"] == 0.0
    assert b["summary"] is None
    assert "triples" not in b


def test_export_empty_index(in_memory_db):
    assert export_notes(in_memory_db) == []


def test_export_include_triples(in_memory_db):
    conn = in_memory_db
    _add_note(conn, "a.md", "Note A")
    _add_note(conn, "b.md", "Note B")
    _add_triple(conn, "a.md", "Alpha", "relates_to", "Beta")
    _add_triple(conn, "a.md", "Alpha", "part_of", "Gamma")

    notes = export_notes(conn, include_triples=True)

    a = next(n for n in notes if n["path"] == "a.md")
    b = next(n for n in notes if n["path"] == "b.md")
    assert a["triples"] == [
        {"subject": "Alpha", "predicate": "relates_to", "object": "Beta"},
        {"subject": "Alpha", "predicate": "part_of", "object": "Gamma"},
    ]
    assert b["triples"] == []


def test_export_is_json_serialisable(in_memory_db):
    conn = in_memory_db
    _add_note(conn, "a.md", "Note A", pagerank=0.1, summary="s")
    _add_triple(conn, "a.md", "X", "is", "Y")

    text = json.dumps(export_notes(conn, include_triples=True))

    assert json.loads(text)[0]["path"] == "a.md"


def test_cmd_export_stdout_and_file(tmp_path, monkeypatch, capsys):
    """CLI wrapper: stdout by default, --output writes a file."""
    from neurostack.cli.index import cmd_export
    from neurostack.schema import get_db

    db_path = tmp_path / "test.db"
    conn = get_db(db_path)
    _add_note(conn, "a.md", "Note A", pagerank=0.5)
    conn.close()
    monkeypatch.setenv("NEUROSTACK_DB_PATH", str(db_path))

    args = argparse.Namespace(include=None, output=None)
    cmd_export(args)
    out = json.loads(capsys.readouterr().out)
    assert out[0]["path"] == "a.md"
    assert out[0]["pagerank"] == 0.5

    out_file = tmp_path / "export.json"
    args = argparse.Namespace(include=["triples"], output=str(out_file))
    cmd_export(args)
    data = json.loads(out_file.read_text())
    assert data[0]["triples"] == []
    assert "Exported 1 notes" in capsys.readouterr().out

    # --output into a directory that does not exist yet
    nested = tmp_path / "missing" / "dir" / "export.json"
    args = argparse.Namespace(include=None, output=str(nested))
    cmd_export(args)
    assert json.loads(nested.read_text())[0]["path"] == "a.md"
