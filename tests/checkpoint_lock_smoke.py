#!/usr/bin/env python3
"""Deterministic, temp-only subprocess smoke for checkpoint locking."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MESSAGES = [
    {"role": "user", "content": f"question {i}"}
    if i % 2 == 0
    else {"role": "assistant", "content": [{"type": "tool_use", "name": "read"}]}
    for i in range(10)
]
MODEL_SOURCE = '''\
import pathlib
import sys
import time

root, count = map(pathlib.Path, sys.argv[1:])
prompt = sys.stdin.read()
session = prompt.split("--session ", 1)[1].split()[0]
marker = root / f"model-started-{session}"
release = root / f"release-{session}"
previous = count.read_text() if count.exists() else ""
count.write_text(previous + session + "\\n")
marker.touch()
while not release.exists():
    time.sleep(0.01)
print('[{"content":"fact one"},{"content":"fact two"}]')
'''


def wait_for(path: Path) -> None:
    for _ in range(500):
        if path.exists():
            return
        threading.Event().wait(0.01)
    raise AssertionError(f"marker not written: {path}")


class Mcp(BaseHTTPRequestHandler):
    calls = []
    fail_at = None

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        method = body.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}}
        elif method == "notifications/initialized":
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        else:
            args = (body.get("params") or {}).get("arguments") or {}
            self.calls.append(args.get("content"))
            result = None if self.fail_at == len(self.calls) else {
                "memory_id": len(self.calls)
            }
        response = {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
        }
        raw = f"event: message\ndata: {json.dumps(response)}\n\n".encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("mcp-session-id", "smoke")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        pass


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Mcp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    children = []
    root = None
    try:
        with tempfile.TemporaryDirectory(prefix="neurostack-163-") as raw:
            root = Path(raw)
            home = root / "home"
            cache = root / "cache"
            home.mkdir()
            model = root / "model.py"
            model.write_text(MODEL_SOURCE)
            count = root / "model-count"
            config = home / ".config/neurostack/client.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                f'checkpoint_command = "{sys.executable} {model} {root} {count}"\n'
                f'url = "http://127.0.0.1:{server.server_address[1]}/mcp"\n'
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(cache),
            }

            def window(session):
                path = cache / f"neurostack/sessions/{session}.window.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"since_index": 0, "messages": MESSAGES}))

            def command(session):
                return [sys.executable, "-m", "neurostack", "hook", "checkpoint",
                        "--run", "--harness", "omp", "--session", session]

            window("same")
            first = subprocess.Popen(command("same"), env=env, stdout=subprocess.PIPE,
                                     text=True, start_new_session=True)
            children.append(first)
            wait_for(root / "model-started-same")
            busy = subprocess.run(command("same"), env=env, capture_output=True,
                                  text=True, timeout=2)
            assert "already running" in busy.stdout
            window("other")
            (root / "release-other").touch()
            other = subprocess.run(command("other"), env=env, capture_output=True,
                                   text=True, timeout=10)
            assert "saved 2" in other.stdout and first.poll() is None
            (root / "release-same").touch()
            first.communicate(timeout=10)

            window("killed")
            killed = subprocess.Popen(command("killed"), env=env, stdout=subprocess.PIPE,
                                      text=True, start_new_session=True)
            children.append(killed)
            wait_for(root / "model-started-killed")
            os.killpg(killed.pid, signal.SIGTERM)
            killed.wait(timeout=5)
            (root / "release-killed").touch()
            recovered = subprocess.run(command("killed"), env=env, capture_output=True,
                                       text=True, timeout=10)
            assert "saved 2" in recovered.stdout

            before = len(Mcp.calls)
            window("partial")
            (root / "release-partial").touch()
            Mcp.fail_at = before + 2
            partial = subprocess.run(command("partial"), env=env, capture_output=True,
                                     text=True, timeout=10)
            assert "saved 1 of 2" in partial.stdout
            Mcp.fail_at = None
            retried = subprocess.run(command("partial"), env=env, capture_output=True,
                                     text=True, timeout=10)
            assert "skipped 1 acknowledged" in retried.stdout
            invocations = count.read_text().splitlines()
            assert invocations.count("partial") == 1
            assert len(invocations) == 5
            assert Mcp.calls[before:].count("fact one") == 1
            assert Mcp.calls[before:].count("fact two") == 2
            print("PASS busy, independence, kill recovery, partial retry")
    finally:
        if root is not None:
            for path in root.glob("release-*"):
                path.touch()
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=5)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
