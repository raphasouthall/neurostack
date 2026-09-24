# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""The `neurostack ui` HTTP server: routing, errors, static files, login (issues #243, #251)."""

import base64
import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from types import ModuleType, SimpleNamespace

import pytest

import neurostack
from neurostack.ui import auth, server
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
def start(tmp_path, monkeypatch):
    """Start a server on port 0 in a thread and return its base URL."""
    monkeypatch.setattr(server, "_FAIL_DELAY", 0)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>hi</h1>")
    (static / "app.js").write_text("export {}")
    # A file beside the static dir that traversal would reach.
    (tmp_path / "pyproject.toml").write_text("secret")
    db = tmp_path / "neurostack.db"
    sqlite3.connect(db).execute("CREATE TABLE notes (path TEXT)").connection.close()
    servers = []

    def run(host="127.0.0.1", db_path=db):
        httpd = make_server(SimpleNamespace(db_path=db_path, db_dir=tmp_path),
                            host, 0, static_dir=static)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield run
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def get(url, method="GET", headers=None, data=None):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
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


def login(base, username="ada", password="correct horse"):
    body = json.dumps({"username": username, "password": password}).encode()
    return get(base + "/api/login", "POST", {"Content-Type": "application/json"}, body)


def session(headers):
    return {"Cookie": f"ns_session={SimpleCookie(headers['Set-Cookie'])['ns_session'].value}"}


@pytest.fixture
def cfg(tmp_path):
    cfg = SimpleNamespace(db_dir=tmp_path)
    auth.add_user(cfg, "ada", "correct horse")
    return cfg


def test_non_loopback_host_needs_a_user(tmp_path):
    with pytest.raises(ValueError, match="neurostack ui user add"):
        make_server(SimpleNamespace(db_path=tmp_path / "x.db", db_dir=tmp_path), "0.0.0.0", 0)


@pytest.mark.parametrize("username, password", [("ada", "wrong pass"), ("bob", "correct horse")])
def test_bad_login_is_401(start, cfg, username, password):
    status, headers, body = login(start(host="0.0.0.0"), username, password)
    assert (status, json.loads(body)) == (401, {"error": "wrong username or password"})
    assert "Set-Cookie" not in headers


def test_oversized_login_is_413(start, cfg):
    base = start(host="0.0.0.0")
    assert get(base + "/api/login", "POST", data=b"x" * 5000)[0] == 413


def test_login_cookie_opens_the_api(start, calls, cfg):
    base = start(host="0.0.0.0")
    status, headers, body = login(base)
    cookie = SimpleCookie(headers["Set-Cookie"])["ns_session"]

    assert (status, json.loads(body)) == (200, {"user": "ada"})
    assert cookie["httponly"] and cookie["samesite"] == "Strict"
    assert get(base + "/api/overview")[0] == 401
    assert get(base + "/api/me")[0] == 401
    assert get(base + "/api/overview", headers=session(headers))[0] == 200
    assert json.loads(get(base + "/api/me", headers=session(headers))[2]) == {"user": "ada"}
    assert get(base + "/")[0] == 200


def test_expired_or_tampered_token_is_401(start, calls, cfg):
    base = start(host="0.0.0.0")
    token = auth.make_session(cfg, "ada", now=1000)
    assert auth.check_session(cfg, token, now=1000 + auth.SESSION_TTL - 1) == "ada"
    assert auth.check_session(cfg, token, now=1000 + auth.SESSION_TTL) is None

    fresh = auth.make_session(cfg, "ada")
    raw = base64.urlsafe_b64decode(fresh + "=" * (-len(fresh) % 4)).decode()
    name, expiry, mac = raw.split("|")
    # A later expiry under the old signature.
    forged = base64.urlsafe_b64encode(f"{name}|{int(expiry) + 1}|{mac}".encode()).decode()
    for bad in (token, forged, "garbage"):
        assert get(base + "/api/overview", headers={"Cookie": f"ns_session={bad}"})[0] == 401
    assert get(base + "/api/overview", headers={"Cookie": f"ns_session={fresh}"})[0] == 200


@pytest.mark.parametrize("change", [
    lambda cfg: auth.remove_user(cfg, "ada"),
    lambda cfg: auth.add_user(cfg, "ada", "new password"),
])
def test_changing_the_user_ends_old_sessions(start, calls, cfg, change):
    base = start(host="0.0.0.0")
    cookie = session(login(base)[1])
    assert get(base + "/api/overview", headers=cookie)[0] == 200
    change(cfg)
    assert get(base + "/api/overview", headers=cookie)[0] == 401


def test_logout_clears_the_cookie(start, cfg):
    status, headers, _ = get(start(host="0.0.0.0") + "/api/logout", "POST")
    cookie = SimpleCookie(headers["Set-Cookie"])["ns_session"]
    assert (status, cookie.value, cookie["max-age"]) == (200, "", "0")


def test_loopback_needs_no_login(start, calls):
    base = start()
    assert json.loads(get(base + "/api/me")[2]) == {"user": None}
    assert get(base + "/api/overview")[0] == 200


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_login_files_are_private(cfg):
    auth.make_session(cfg, "ada")
    for name in ("ui-users.json", "ui-secret"):
        assert (cfg.db_dir / name).stat().st_mode & 0o777 == 0o600
