"""Shared fixtures for NeuroStack tests."""

import json
import sqlite3
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


@pytest.fixture(autouse=True)
def clear_reinforcement_buffer():
    """Isolate the per-process reinforcement buffer between tests (issue #120).

    hybrid_search buffers co-occurrence pairs in a module-level set instead of
    writing them, so without this a search in one test leaves pairs that a drain
    in another would write to an unrelated database. The recorded database path
    is reset too, for the same reason.
    """
    from neurostack import cooccurrence

    def _reset():
        thread = cooccurrence._flush_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10.0)
        with cooccurrence._reinforcement_lock:
            cooccurrence._reinforcement_buffer.clear()
        cooccurrence._reinforcement_db_path = ""
        cooccurrence._flush_thread = None

    _reset()
    yield
    _reset()


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


# ---------------------------------------------------------------------------
# Fake MCP endpoint for the harness hook tests (issues #141 / #143)
# ---------------------------------------------------------------------------

class FakeMcpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        method = body.get("method")
        if method == "initialize":
            self._send({"jsonrpc": "2.0", "id": body.get("id"),
                        "result": {"protocolVersion": "2025-06-18", "capabilities": {}}},
                       sid="fake-session")
            return
        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        if method == "tools/call":
            params = body.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            self.server.calls.append((name, args))
            # A real server embeds every memory it stores, which outlasts the
            # interactive timeout; `delay_s` makes that testable (issue #153).
            if self.server.delay_s:
                time.sleep(self.server.delay_s)
            reply = self.server.replies.get(name)
            payload = reply(args) if callable(reply) else ({} if reply is None else reply)
            self._send({"jsonrpc": "2.0", "id": body.get("id"),
                        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}})
            return
        self._send({"jsonrpc": "2.0", "id": body.get("id"),
                    "error": {"code": -32601, "message": f"unknown method {method}"}})

    def _send(self, obj, sid=None):
        raw = f"event: message\ndata: {json.dumps(obj)}\n\n".encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        if sid:
            self.send_header("mcp-session-id", sid)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    """A fake MCP endpoint. `replies` maps tool name -> payload or callable."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeMcpHandler)
    httpd.calls = []
    httpd.replies = {}
    httpd.delay_s = 0.0
    httpd.url = f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Keep state files, config, and adapter writes inside the test.

    Not autouse: only the hook and checkpoint modules want a throwaway HOME,
    and they opt in module-wide.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv("NEUROSTACK_URL", raising=False)
    return home
