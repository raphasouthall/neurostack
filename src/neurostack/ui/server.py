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

from . import auth, search, tuning

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
# mimetypes reads the OS registry, which maps .js to text/plain on some Windows
# installs and has no entry for .mjs on older Pythons.
_TYPES = {".js": "text/javascript", ".mjs": "text/javascript"}
COOKIE = "ns_session"
_MAX_BODY = 4096
# A Best result mark carries the list shown, up to 50 note paths.
_MAX_WRITE_BODY = 65536
_WRITES = ("/api/feedback", "/api/feedback/undo", "/api/tune", "/api/tune/apply",
           "/api/tune/revert")
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


def _flag(params: dict, name: str) -> bool:
    return params.get(name, "").lower() in ("1", "true", "yes", "on")


def _search(conn, cfg, path: str, params: dict):
    """The Search page's two endpoints; a bad option is a 400, not a 500."""
    q = params.get("q", "").strip()
    text = {k: params[k].strip() or None for k in ("workspace", "context", "type")
            if k in params}
    if path == "/api/search/memories":
        return search.memories(cfg, q or None, entity_type=text.get("type"),
                               workspace=text.get("workspace"), **_ints(params, "limit"))
    if not q:
        raise _Error(400, "q is required")
    try:
        found = search.notes(
            cfg, q, mode=params.get("mode", "hybrid"), depth=params.get("depth", "full"),
            workspace=text.get("workspace"), context=text.get("context"),
            rerank=_flag(params, "rerank"), reference_only=_flag(params, "reference_only"),
            **_ints(params, "top_k", "max_tokens"))
    except ValueError as exc:
        raise _Error(400, str(exc)) from None
    # The notes already marked Best result for this query, so the page shows them (#291).
    found["marked"] = {r["chosen_path"]: r["feedback_id"] for r in conn.execute(
        "SELECT chosen_path, feedback_id FROM search_feedback"
        " WHERE query = ? AND source = 'explicit'", (q,))}
    return found


def _write(conn, cfg, path: str, body: dict):
    """One write request. A malformed body is a 400; a refused tuning step a 409."""
    from .. import feedback

    def field(name, kind):
        value = body.get(name)
        if not isinstance(value, kind) or (kind is str and not value.strip()):
            raise _Error(400, f"{name} is required")
        return value

    if path == "/api/feedback":
        shown = body.get("shown_paths") or []
        if not isinstance(shown, list) or not all(isinstance(p, str) for p in shown):
            raise _Error(400, "shown_paths must be a list of note paths")
        fid = feedback.mark_best(conn, field("query", str), field("chosen_path", str), shown)
        return {"feedback_id": fid}
    if path == "/api/feedback/undo":
        return {"removed": feedback.unmark_best(conn, field("feedback_id", int))}
    if path == "/api/tune":
        return {"run_id": tuning.start(cfg)}
    if path == "/api/tune/apply":
        try:
            tuning.apply(conn, field("run_id", int))
        except KeyError:
            raise _Error(404, f"unknown run: {body['run_id']}") from None
        return {"applied": body["run_id"]}
    return {"reverted": tuning.revert(conn)}


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
    if path == "/api/tune":
        return tuning.status(conn, cfg)
    if path == "/api/workspaces":
        return search.workspaces(conn)
    if path in ("/api/search/notes", "/api/search/memories"):
        return _search(conn, cfg, path, params)
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
        if path not in ("/api/login", "/api/logout") and path not in _WRITES:
            return self._not_allowed()
        try:
            if path == "/api/logout":
                self._json(200, {"user": None}, [("Set-Cookie", _cookie("", 0))])
                return
            if path in _WRITES:
                self._json(200, self._write(path))
                return
            name = self._login()
            token = auth.make_session(self.server.cfg, name)
            self._json(200, {"user": name}, [("Set-Cookie", _cookie(token, auth.SESSION_TTL))])
        except _Error as exc:
            self._json(exc.status, {"error": str(exc)})
        except Exception as exc:
            log.exception("ui request failed: %s", self.path)
            self._json(500, {"error": str(exc)})

    def _body(self, limit: int = _MAX_BODY) -> dict:
        try:
            size = int(self.headers.get("Content-Length", 0))
            if size < 0:
                raise ValueError
        except ValueError:
            raise _Error(400, "bad Content-Length") from None
        if size > limit:
            raise _Error(413, "body too large")
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            raise _Error(400, "body must be JSON") from None
        if not isinstance(body, dict):
            raise _Error(400, "body must be a JSON object")
        return body

    def _login(self) -> str:
        body = self._body()
        name, password = body.get("username"), body.get("password")
        if not isinstance(name, str) or not isinstance(password, str):
            raise _Error(400, "body must be JSON {username, password}")
        if not auth.verify(self.server.cfg, name, password):
            time.sleep(_FAIL_DELAY)
            raise _Error(401, "wrong username or password")
        return name

    def _write(self, path: str):
        """The dashboard's only writes (#291): search labels and weight tuning."""
        self._signed_in()
        db = Path(self.server.cfg.db_path)
        if not db.exists():
            raise _Error(503, "no index yet, run neurostack index")
        body = self._body(_MAX_WRITE_BODY)
        conn = tuning._connect(db)
        try:
            return _write(conn, self.server.cfg, path, body)
        except tuning.TuningError as exc:
            raise _Error(409, str(exc)) from None
        finally:
            conn.close()

    def _signed_in(self):
        srv = self.server
        user = None if srv.loopback else self._user()
        if not srv.loopback and not user:
            raise _Error(401, "sign in first")
        return user

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
        user = self._signed_in()
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
    if Path(cfg.db_path).exists():
        tuning.prepare(cfg.db_path)
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
