"""Shared fixtures for NeuroStack tests."""

import json
import sqlite3
import textwrap

import pytest


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault with sample notes."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Note 1: research note with frontmatter and wiki-links
    (vault / "research").mkdir()
    (vault / "research" / "predictive-coding.md").write_text(textwrap.dedent("""\
        ---
        date: 2026-01-15
        tags: [neuroscience, prediction]
        type: permanent
        status: active
        actionable: true
        ---

        # Predictive Coding

        The brain generates predictions about incoming sensory data.
        When predictions fail, **prediction errors** propagate upward.

        ## Key Principles

        - Hierarchical prediction chains
        - Error-driven learning
        - Bayesian inference in neural circuits

        ## Related

        See [[memory-consolidation]] for how predictions are refined during sleep.
        Also related to [[excitability-windows]].
    """))

    # Note 2: linked note
    (vault / "research" / "memory-consolidation.md").write_text(textwrap.dedent("""\
        ---
        date: 2026-01-20
        tags: [neuroscience, memory]
        type: permanent
        status: active
        actionable: false
        ---

        # Memory Consolidation

        Memory consolidation occurs during sleep through hippocampal replay.

        ## Mechanisms

        - Hippocampal sharp-wave ripples
        - Cortical slow oscillations
        - Spindle-ripple coupling

        This process stabilises [[predictive-coding]] networks.
    """))

    # Note 3: a long note that will be chunked
    long_content = "Some content here.\n" * 200
    (vault / "research" / "long-note.md").write_text(textwrap.dedent(f"""\
        ---
        date: 2026-02-01
        tags: [test]
        type: permanent
        status: reference
        ---

        # Long Note

        {long_content}

        ## Section Two

        More content in section two.

        ## Section Three

        Final section content.
    """))

    # Index file
    (vault / "research" / "index.md").write_text(textwrap.dedent("""\
        # Research Index

        - [[predictive-coding]] — Predictive coding theory
        - [[memory-consolidation]] — Memory consolidation mechanisms
        - [[long-note]] — A long test note
    """))

    return vault


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database with the NeuroStack schema."""
    from neurostack.schema import SCHEMA_SQL, SCHEMA_VERSION

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO schema_version VALUES (?)", (SCHEMA_VERSION,)
    )
    conn.commit()
    return conn


@pytest.fixture
def populated_db(in_memory_db, tmp_vault):
    """In-memory DB populated with sample notes and chunks."""
    conn = in_memory_db
    now = "2026-01-15T00:00:00+00:00"

    from neurostack.chunker import parse_note

    for md_file in sorted(tmp_vault.rglob("*.md")):
        if md_file.name == "index.md":
            continue
        parsed = parse_note(md_file, tmp_vault)
        fm_json = json.dumps(parsed.frontmatter, default=str)
        conn.execute(
            "INSERT OR REPLACE INTO notes "
            "(path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (parsed.path, parsed.title, fm_json, parsed.content_hash, now),
        )
        for chunk in parsed.chunks:
            conn.execute(
                "INSERT INTO chunks "
                "(note_path, heading_path, content, content_hash, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, chunk.heading_path, chunk.content, "test",
                 chunk.position),
            )

    conn.commit()
    return conn
