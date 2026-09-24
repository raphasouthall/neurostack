# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""The `neurostack ui` HTTP server: routing, errors, static files, auth (issue #243)."""

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from types import ModuleType, SimpleNamespace

import pytest

import neurostack
from neurostack.ui.server import make_server


@pytest.fixture
def calls(monkeypatch):
    """Swap in a fake dashboard module that records each call's arguments."""
    seen = []
    fake = ModuleType("neurostack.dashboard")

    def record(name):
        def fn(conn, *args, **kwargs):
            seen.append((name, args, kwargs))
            return {"route": name}
        return fn

    for name in ("overview", "automations", "graph", "communities", "memories"):
        setattr(fake, name, record(name))

    def missing(conn, key, **kwargs):
        raise KeyError(key)

    fake.job_runs = fake.note = missing
    monkeypatch.setitem(sys.modules, "neurostack.dashboard", fake)
    # `from .. import dashboard` reads the package attribute first when the
    # real module was imported earlier in the run.
    monkeypatch.setattr(neurostack, "dashboard", fake, raising=False)
    fake.seen = seen
    return fake


@pytest.fixture
def start(tmp_path):
    """Start a server on port 0 in a thread and return its base URL."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>hi</h1>")
    (static / "app.js").write_text("export {}")
    # A file beside the static dir that traversal would reach.
    (tmp_path / "pyproject.toml").write_text("secret")
    db = tmp_path / "neurostack.db"
    sqlite3.connect(db).execute("CREATE TABLE notes (path TEXT)").connection.close()
    servers = []

    def run(host="127.0.0.1", api_key="", db_path=db):
        httpd = make_server(SimpleNamespace(db_path=db_path, api_key=api_key),
                            host, 0, static_dir=static)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield run
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def get(url, method="GET", headers=None):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


@pytest.mark.parametrize("path, call", [
    ("/api/graph?limit=7&community=3", ("graph", (), {"limit": 7, "community": 3})),
    ("/api/memories?limit=5&type=bug&q=foo",
     ("memories", (), {"limit": 5, "entity_type": "bug", "q": "foo"})),
    ("/api/overview", ("overview", (), {})),
])
def test_api_passes_params_through(start, calls, path, call):
    status, headers, body = get(start() + path)

    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    assert json.loads(body) == {"route": call[0]}
    assert calls.seen == [call]


@pytest.mark.parametrize("path", [
    "/api/graph?limit=ten",
    "/api/graph?community=x",
    "/api/automations/decay/runs?limit=1.5",
    "/api/notes",
])
def test_bad_params_are_400(start, calls, path):
    status, _, body = get(start() + path)
    assert status == 400
    assert "error" in json.loads(body)
    assert calls.seen == []


@pytest.mark.parametrize("path", [
    "/api/automations/nope/runs",
    "/api/notes?path=missing.md",
    "/api/nothing",
])
def test_unknown_things_are_404(start, calls, path):
    status, headers, body = get(start() + path)
    assert status == 404
    assert headers["Content-Type"] == "application/json"
    assert "error" in json.loads(body)


def test_non_get_is_405(start, calls):
    status, headers, _ = get(start() + "/api/overview", method="POST")
    assert status == 405
    assert headers["Allow"] == "GET"


def test_unhandled_error_is_500(start, calls):
    def boom(conn):
        raise RuntimeError("boom")

    calls.overview = boom
    status, _, body = get(start() + "/api/overview")
    assert (status, json.loads(body)) == (500, {"error": "boom"})


def test_missing_db_is_503(start, calls, tmp_path):
    status, _, body = get(start(db_path=tmp_path / "absent.db") + "/api/overview")
    assert status == 503
    assert json.loads(body) == {"error": "no index yet, run neurostack index"}


def test_connection_is_read_only(start, calls):
    def write(conn):
        conn.execute("INSERT INTO notes VALUES ('x')")

    calls.overview = write
    status, _, body = get(start() + "/api/overview")
    assert status == 500
    assert "readonly" in json.loads(body)["error"]


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/%2e%2e/pyproject.toml", "/nope.js"])
def test_static_outside_or_missing_is_404(start, path):
    status, _, body = get(start() + path)
    assert status == 404
    assert b"secret" not in body


@pytest.mark.parametrize("path, ctype, body", [
    ("/", "text/html", b"<h1>hi</h1>"),
    ("/app.js", "text/javascript", b"export {}"),
])
def test_static_files_are_served(start, path, ctype, body):
    status, headers, got = get(start() + path)
    assert (status, headers["Content-Type"], got) == (200, ctype, body)


def test_non_loopback_host_needs_api_key(tmp_path):
    with pytest.raises(ValueError, match="api_key"):
        make_server(SimpleNamespace(db_path=tmp_path / "x.db", api_key=""), "0.0.0.0", 0)


def test_non_loopback_api_needs_bearer(start, calls):
    base = start(host="0.0.0.0", api_key="s3cret")

    assert get(base + "/api/overview")[0] == 401
    assert get(base + "/api/overview", headers={"Authorization": "Bearer wrong"})[0] == 401
    assert get(base + "/api/overview", headers={"Authorization": "s3cret"})[0] == 401
    assert get(base + "/api/overview", headers={"Authorization": "Bearer s3cret"})[0] == 200
    assert get(base + "/")[0] == 200
