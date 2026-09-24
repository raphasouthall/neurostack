# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""HTTP server behind `neurostack ui` (issue #243).

Answers the dashboard's JSON API from `dashboard.py` over a read-only SQLite
connection and serves the static frontend. It is stdlib only, so it runs on the
base install without the FastAPI extra that `neurostack api` needs. On a
non-loopback host the API needs a session cookie from `POST /api/login`.
"""

import json
import logging
import mimetypes
import socket
import sqlite3
import time
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import auth

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
# mimetypes reads the OS registry, which maps .js to text/plain on some Windows
# installs and has no entry for .mjs on older Pythons.
_TYPES = {".js": "text/javascript", ".mjs": "text/javascript"}
COOKIE = "ns_session"
_MAX_BODY = 4096
# Seconds a failed login waits before answering, to slow password guessing.
_FAIL_DELAY = 1.0


def _cookie(token: str, max_age: int) -> str:
    return f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}"


class _Error(Exception):
    """An HTTP error, answered as `{"error": msg}`."""

    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status


def _ints(params: dict, *names: str) -> dict:
    """Parse the integer params the request sent; absent ones keep the data layer's default."""
    out = {}
    for name in names:
        if name in params:
            try:
                out[name] = int(params[name])
            except ValueError:
                raise _Error(400, f"{name} must be an integer") from None
    return out


def _route(conn, cfg, path: str, params: dict):
    from .. import dashboard

    if path == "/api/overview":
        return dashboard.overview(conn)
    if path == "/api/automations":
        return dashboard.automations(conn, cfg)
    if path == "/api/graph":
        return dashboard.graph(conn, **_ints(params, "limit", "community"))
    if path == "/api/communities":
        return dashboard.communities(conn)
    if path == "/api/memories":
        kw = _ints(params, "limit")
        if "type" in params:
            kw["entity_type"] = params["type"]
        if "q" in params:
            kw["q"] = params["q"]
        return dashboard.memories(conn, **kw)
    if path == "/api/notes":
        if "path" not in params:
            raise _Error(400, "path is required")
        try:
            return dashboard.note(conn, params["path"])
        except KeyError:
            raise _Error(404, f"unknown note: {params['path']}") from None
    parts = path.split("/")
    if len(parts) == 5 and parts[2] == "automations" and parts[4] == "runs":
        job = unquote(parts[3])
        try:
            return dashboard.job_runs(conn, job, **_ints(params, "limit"))
        except KeyError:
            raise _Error(404, f"unknown job: {job}") from None
    raise _Error(404, f"unknown endpoint: {path}")


class _Handler(BaseHTTPRequestHandler):
    server_version = "NeuroStackUI"

    def do_GET(self):
        url = urlsplit(self.path)
        try:
            if url.path == "/api" or url.path.startswith("/api/"):
                self._json(200, self._api(url))
            else:
                self._static(url.path)
        except _Error as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception as exc:
            log.exception("ui request failed: %s", self.path)
            self._json(500, {"error": str(exc)})

    def _not_allowed(self):
        self._json(405, {"error": "method not allowed"}, [("Allow", "GET")])

    do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _not_allowed

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/login", "/api/logout"):
            return self._not_allowed()
        try:
            if path == "/api/logout":
                self._json(200, {"user": None}, [("Set-Cookie", _cookie("", 0))])
                return
            name = self._login()
            token = auth.make_session(self.server.cfg, name)
            self._json(200, {"user": name}, [("Set-Cookie", _cookie(token, auth.SESSION_TTL))])
        except _Error as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception as exc:
            log.exception("ui request failed: %s", self.path)
            self._json(500, {"error": str(exc)})

    def _login(self) -> str:
        try:
            size = int(self.headers.get("Content-Length", 0))
            if size < 0:
                raise ValueError
        except ValueError:
            raise _Error(400, "bad Content-Length") from None
        if size > _MAX_BODY:
            raise _Error(413, "body too large")
        try:
            body = json.loads(self.rfile.read(size))
            name, password = body["username"], body["password"]
            if not isinstance(name, str) or not isinstance(password, str):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise _Error(400, "body must be JSON {username, password}") from None
        if not auth.verify(self.server.cfg, name, password):
            time.sleep(_FAIL_DELAY)
            raise _Error(401, "wrong username or password")
        return name

    def _user(self):
        """The user the request's session cookie signs in, or None."""
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = jar.get(COOKIE)
        return auth.check_session(self.server.cfg, morsel.value) if morsel else None

    def _api(self, url):
        srv = self.server
        user = None if srv.loopback else self._user()
        if not srv.loopback and not user:
            raise _Error(401, "sign in first")
        if url.path == "/api/me":
            return {"user": user}
        db = Path(srv.cfg.db_path)
        if not db.exists():
            raise _Error(503, "no index yet, run neurostack index")
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        # A file URI, because a bare Windows path is not a valid SQLite URI.
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return _route(conn, srv.cfg, url.path, params)
        finally:
            conn.close()

    def _static(self, path: str):
        root = self.server.static_dir
        target = (root / (unquote(path).lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise _Error(404, "not found")
        ctype = (_TYPES.get(target.suffix) or mimetypes.guess_type(target.name)[0]
                 or "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def _json(self, status: int, data, headers=()):
        body = json.dumps(data).encode()
        self._send(status, body, "application/json", [("Cache-Control", "no-store"), *headers])

    def _send(self, status: int, body: bytes, ctype: str, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        log.debug(format, *args)


class _V6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def make_server(cfg, host: str, port: int, static_dir=None) -> ThreadingHTTPServer:
    """Bind the dashboard server without starting it.

    Raises ValueError when a non-loopback host has no user to sign in as.
    """
    loopback = host in LOOPBACK
    if not loopback and not auth.list_users(cfg):
        raise ValueError(
            f"neurostack ui on {host} needs a login; create one with "
            "`neurostack ui user add NAME`. Only loopback hosts run without one"
        )
    httpd = (_V6Server if ":" in host else ThreadingHTTPServer)((host, port), _Handler)
    httpd.cfg = cfg
    httpd.loopback = loopback
    httpd.static_dir = Path(static_dir or STATIC_DIR).resolve()
    return httpd


def serve(cfg, host: str, port: int, open_browser: bool = False) -> None:
    """Serve the dashboard until Ctrl-C."""
    httpd = make_server(cfg, host, port)
    shown = f"[{host}]" if ":" in host else host
    url = f"http://{shown}:{httpd.server_address[1]}"
    print(f"NeuroStack UI on {url}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
