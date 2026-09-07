# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack hook <event>` — the harness-neutral client hook (issue #141).

One JSON object on stdin, the text to inject on stdout, exit 0 (allow) or
exit 2 (block, stdout is the reason). Every harness adapter is a thin mapping
onto these five events, so retrieval, once-per-session suppression, and
outcome reporting live here instead of once per harness.

Fail open, always: an unreachable server, a malformed payload, or an
unexpected exception prints one line to stderr and exits 0.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..client import ClientConfig, McpClient, load_client_config

EVENTS = ("session-start", "prompt", "tool-call", "tool-result", "session-end")

# After a trigger fires, watch this many later tool calls: a byte-identical
# re-issue means the memory was ignored, silence means it was followed (#136).
OUTCOME_WINDOW = 5
# 20 fired on "retry the mcp" and "do it", which carry no retrievable topic.
MIN_PROMPT_LEN = 40
PROMPT_TOKEN_BUDGET = 1500
# vault_harvest_transcript takes the transcript inline; keep each POST inside
# the server's request limits.
MAX_TRANSCRIPT_BYTES = 4 * 1024 * 1024
_HASHLINE_HEADER = re.compile(r"^\[([^\]#]+)#[0-9A-Fa-f]{4}\]", re.MULTILINE)
_XD_PREFIX = "xd://"


@dataclass
class Verdict:
    """What the harness should do with this event."""

    text: str = ""
    block: bool = False


@dataclass
class SessionState:
    """Once-per-session bookkeeping, persisted between hook processes."""

    session: str
    path: Path
    fired: set[int] = field(default_factory=set)
    checked: set[str] = field(default_factory=set)
    pending: dict[int, dict] = field(default_factory=dict)
    prompts: set[str] = field(default_factory=set)
    calls: int = 0

    def save(self) -> None:
        data = {
            "fired": sorted(self.fired),
            "checked": sorted(self.checked),
            "pending": {str(k): v for k, v in self.pending.items()},
            "prompts": sorted(self.prompts),
            "calls": self.calls,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            print(f"neurostack hook: state not saved: {exc}", file=sys.stderr)


def sessions_dir() -> Path:
    """Per-session state directory (`~/.cache/neurostack/sessions`)."""
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "neurostack" / "sessions"


def _state_path(session: str) -> Path:
    """State file for a session id, sanitized into a single safe filename."""
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", session)[:120] or "default"
    return sessions_dir() / f"{slug}.json"


def load_state(session: str, fresh: bool = False) -> SessionState:
    """Read the session's state, or start a new one."""
    path = _state_path(session)
    state = SessionState(session=session, path=path)
    if fresh:
        return state
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if not isinstance(raw, dict):
        return state
    state.fired = {int(i) for i in raw.get("fired", []) if isinstance(i, int)}
    state.checked = {str(k) for k in raw.get("checked", []) if isinstance(k, str)}
    state.prompts = {str(k) for k in raw.get("prompts", []) if isinstance(k, str)}
    pending = raw.get("pending")
    if isinstance(pending, dict):
        for key, value in pending.items():
            if isinstance(value, dict) and str(key).lstrip("-").isdigit():
                state.pending[int(key)] = value
    if isinstance(raw.get("calls"), int):
        state.calls = raw["calls"]
    return state


# ---------------------------------------------------------------------------
# Payload reading — harnesses name the same fields differently
# ---------------------------------------------------------------------------

def _first_str(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _session_id(payload: dict) -> str:
    return _first_str(payload, "session", "session_id") or "default"


def _tool_input(payload: dict):
    for key in ("input", "tool_input"):
        if key in payload:
            return payload[key]
    return None


def _xd_device(value: str) -> str | None:
    """Bare tool name behind an xd:// device path, or None.

    `xd://mcp__neurostack_vault_write_file` -> `vault_write_file`: omp turns an
    MCP tool call into a `write` to a device path, and the trigger tag records
    the plain tool name.
    """
    if not value.startswith(_XD_PREFIX):
        return None
    device = value[len(_XD_PREFIX):]
    if not device.startswith("mcp__"):
        return device or None
    rest = device[len("mcp__"):]
    sep = rest.find("_")
    return rest[sep + 1:] if sep > 0 else rest or None


def _tool_names(tool: str, tool_input) -> list[str]:
    """Every name a `when-calling:` tag could plausibly be written as."""
    names: list[str] = []
    device = _xd_device(tool)
    if device:
        names.append(device)
    elif tool:
        names.append(tool)
        if isinstance(tool_input, dict) and isinstance(tool_input.get("path"), str):
            nested = _xd_device(tool_input["path"])
            if nested:
                names.append(nested)
    return list(dict.fromkeys(names))


def _edited_paths(payload: dict, tool: str, tool_input) -> list[str]:
    """Files this call is about to touch.

    The harness may pass `paths` outright; otherwise derive them the way the
    write and edit tools carry them (`path`/`file_path`, or hashline section
    headers in an edit body) so an adapter stays a pure event mapping.
    """
    paths: list[str] = []
    given = payload.get("paths")
    if isinstance(given, list):
        paths += [p for p in given if isinstance(p, str) and p]
    if isinstance(tool_input, dict):
        for key in ("path", "file_path", "notebook_path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
        body = tool_input.get("input")
        if tool == "edit" and isinstance(body, str):
            paths += _HASHLINE_HEADER.findall(body)
    return [p for p in dict.fromkeys(paths) if not p.startswith(_XD_PREFIX)]


def _error_text(payload: dict) -> str:
    """Error text of a failed tool call, or "" when the call succeeded."""
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict) and error:
        return json.dumps(error)
    # Claude Code passes the whole response and no error flag; only treat it as
    # a failure when it says so, or a when-error lookup runs on every call.
    response = payload.get("tool_response")
    if isinstance(response, dict):
        for key in ("error", "isError", "is_error"):
            value = response.get(key)
            if value:
                return value if isinstance(value, str) else json.dumps(response)
    if isinstance(response, str) and response.strip().lower().startswith("error"):
        return response.strip()
    return ""


def _error_key(text: str) -> str:
    return text.strip()[:120].lower()


def _call_key(tool: str, tool_input) -> str:
    try:
        body = json.dumps(tool_input, sort_keys=True, default=str)
    except (TypeError, ValueError):
        body = ""
    return f"{tool}\x00{body}"


# ---------------------------------------------------------------------------
# Triggers and outcomes (issues #131 / #136)
# ---------------------------------------------------------------------------

def _valid_hit(hit) -> bool:
    return (
        isinstance(hit, dict)
        and isinstance(hit.get("memory_id"), int)
        and isinstance(hit.get("content"), str)
        and isinstance(hit.get("trigger"), str)
    )


def _fetch_triggers(
    client: McpClient,
    state: SessionState,
    event: str,
    value: str,
    workspace: str | None,
) -> list[dict]:
    """Trigger hits that have not fired yet in this session.

    Each (event, value) pair is looked up once per session and each memory
    fires once, so the server sees no repeat traffic and a re-issued call
    always proceeds.
    """
    if not value:
        return []
    key = f"{event}\x00{value}"
    if key in state.checked:
        return []
    state.checked.add(key)
    args: dict = {"event": event, "value": value, "session_hint": state.session}
    if workspace:
        args["workspace"] = workspace
    payload = client.call_json("vault_triggers", args)
    hits = payload.get("hits") if isinstance(payload, dict) else None
    fresh = [
        h for h in hits or []
        if _valid_hit(h) and h["memory_id"] not in state.fired
    ]
    for hit in fresh:
        state.fired.add(hit["memory_id"])
    return fresh


def _report_outcome(
    client: McpClient,
    state: SessionState,
    memory_id: int,
    followed: bool,
    note: str,
) -> None:
    state.pending.pop(memory_id, None)
    client.call(
        "vault_trigger_outcome",
        {"memory_id": memory_id, "followed": followed, "note": note},
    )


def _observe_call(client: McpClient, state: SessionState, tool: str, tool_input) -> None:
    """Settle pending outcomes and advance the window on every tool call."""
    if not state.pending:
        return
    key = _call_key(tool, tool_input)
    for memory_id, pending in list(state.pending.items()):
        if pending.get("kind") in ("calling", "editing") and pending.get("key") == key:
            _report_outcome(client, state, memory_id, False, f"re-issued {tool} unchanged")
            continue
        pending["remaining"] = int(pending.get("remaining", OUTCOME_WINDOW)) - 1
        if pending["remaining"] <= 0:
            _report_outcome(
                client, state, memory_id, True, "window elapsed without a repeat"
            )


def _observe_error(client: McpClient, state: SessionState, text: str) -> None:
    """A when-error memory was ignored when the same error comes back."""
    if not state.pending:
        return
    key = _error_key(text)
    for memory_id, pending in list(state.pending.items()):
        if pending.get("kind") == "error" and pending.get("key") == key:
            _report_outcome(client, state, memory_id, False, "same error recurred")


def _format_hits(hits: list[dict], header: str) -> str:
    lines = [f"- [memory {h['memory_id']}, {h['trigger']}] {h['content']}" for h in hits]
    return header + "\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def _workspace(cfg: ClientConfig, payload: dict) -> str | None:
    return cfg.workspace_for(_first_str(payload, "workspace", "cwd") or None)


def _event_session_start(client: McpClient, payload: dict, state: SessionState,
                         cfg: ClientConfig) -> Verdict:
    args: dict = {}
    workspace = _workspace(cfg, payload)
    if workspace:
        args["workspace"] = workspace
    text = client.call("session_brief", args)
    if not text:
        return Verdict()
    # The tool answers {"brief": "<markdown>"}; unwrap it, and take a plain
    # text reply as the brief itself.
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        brief = parsed.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            return Verdict()
        text = brief
    return Verdict(
        "NeuroStack session brief (auto-injected at session start; recent vault "
        "changes, commits, memories):\n\n" + text.strip()
    )


def _event_prompt(client: McpClient, payload: dict, state: SessionState,
                  cfg: ClientConfig) -> Verdict:
    prompt = _first_str(payload, "prompt").strip()
    # Slash commands, bash passthroughs, and one-liners carry no topic.
    if len(prompt) < MIN_PROMPT_LEN or prompt.startswith(("/", "!", "#")):
        return Verdict()
    digest = hashlib.sha256(prompt[:200].encode("utf-8")).hexdigest()[:16]
    if digest in state.prompts:
        return Verdict()
    # Mark before fetching so a failed call never retries per model turn.
    state.prompts.add(digest)
    args: dict = {"task": prompt[:500], "token_budget": PROMPT_TOKEN_BUDGET}
    workspace = _workspace(cfg, payload)
    if workspace:
        args["workspace"] = workspace
    context = _cwd_context(payload)
    if context:
        args["context"] = context
    text = client.call("vault_context", args)
    if not text:
        return Verdict()
    return Verdict(
        "NeuroStack context (auto-RAG for this prompt; graph-ranked notes, "
        "memories, triples — background, verify anything operational):\n" + text.strip()
    )


def _cwd_context(payload: dict) -> str | None:
    """Project hint from the working directory: its basename, unless $HOME.

    Feeds vault_context's soft attention boost (#94) — re-ranking, not filtering.
    """
    cwd = _first_str(payload, "cwd", "workspace").rstrip("/")
    if not cwd or not cwd.startswith("/") or cwd == str(Path.home()).rstrip("/"):
        return None
    base = os.path.basename(cwd)
    return base if len(base) > 2 else None


def _event_tool_call(client: McpClient, payload: dict, state: SessionState,
                     cfg: ClientConfig) -> Verdict:
    tool = _first_str(payload, "tool", "tool_name")
    tool_input = _tool_input(payload)
    state.calls += 1
    _observe_call(client, state, tool, tool_input)
    workspace = _workspace(cfg, payload)
    hits: list[dict] = []
    for name in _tool_names(tool, tool_input):
        hits += _fetch_triggers(client, state, "calling", name, workspace)
    for path in _edited_paths(payload, tool, tool_input):
        hits += _fetch_triggers(client, state, "editing", path, workspace)
    if not hits:
        return Verdict()
    key = _call_key(tool, tool_input)
    for hit in hits:
        state.pending[hit["memory_id"]] = {
            "kind": "editing" if hit["trigger"].startswith("when-editing:") else "calling",
            "key": key,
            "remaining": OUTCOME_WINDOW,
        }
    return Verdict(
        _format_hits(
            hits,
            "NeuroStack trigger memories apply to this call (fires once per session; "
            "re-issue the call with them in mind):",
        ),
        block=True,
    )


def _event_tool_result(client: McpClient, payload: dict, state: SessionState,
                       cfg: ClientConfig) -> Verdict:
    text = _error_text(payload)
    if not text:
        return Verdict()
    _observe_error(client, state, text)
    hits = _fetch_triggers(client, state, "error", text[:500], _workspace(cfg, payload))
    if not hits:
        return Verdict()
    key = _error_key(text)
    for hit in hits:
        state.pending[hit["memory_id"]] = {
            "kind": "error", "key": key, "remaining": OUTCOME_WINDOW,
        }
    return Verdict(
        _format_hits(
            hits,
            "NeuroStack trigger memories for this error (fires once per session):",
        )
    )


def _transcript_roots() -> dict[str, Path]:
    home = Path.home()
    return {
        "claude-code": home / ".claude" / "projects",
        "omp": home / ".omp" / "agent" / "sessions",
    }


def _resolve_transcript(payload: dict, session: str, source: str) -> Path | None:
    """The transcript file for this session.

    Claude Code hands over `transcript_path`; omp only knows its session id,
    so the file is looked up under the harness's session root.
    """
    given = _first_str(payload, "transcript_path", "transcript")
    if given:
        path = Path(os.path.expanduser(given))
        return path if path.is_file() else None
    roots = _transcript_roots()
    candidates = [roots[source]] if source in roots else list(roots.values())
    found: list[Path] = []
    for root in candidates:
        if root.is_dir():
            found += [p for p in root.glob(f"**/*{session}*.jsonl") if p.is_file()]
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)


def _chunks(text: str) -> list[str]:
    """Split on newline boundaries so every chunk holds whole JSONL records."""
    if len(text.encode("utf-8", "replace")) <= MAX_TRANSCRIPT_BYTES:
        return [text]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        n = len(line.encode("utf-8", "replace"))
        if size + n > MAX_TRANSCRIPT_BYTES and buf:
            out.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += n
    if buf:
        out.append("".join(buf))
    return out


def _event_session_end(client: McpClient, payload: dict, state: SessionState,
                       cfg: ClientConfig) -> Verdict:
    source = _first_str(payload, "format", "source_agent") or "claude-code"
    path = _resolve_transcript(payload, state.session, source)
    if path is None:
        print("neurostack hook session-end: no transcript found", file=sys.stderr)
        return Verdict()
    try:
        text = path.read_text(errors="replace")
    except OSError as exc:
        print(f"neurostack hook session-end: {path} unreadable: {exc}", file=sys.stderr)
        return Verdict()
    parts = _chunks(text)
    lines: list[str] = []
    for i, part in enumerate(parts):
        session_id = path.stem if len(parts) == 1 else f"{path.stem}#{i}"
        report = client.call_json(
            "vault_harvest_transcript",
            {"transcript": part, "session_id": session_id, "source_agent": source},
            timeout_s=cfg.harvest_timeout_s,
        )
        if report is None:
            lines.append(f"{path.name} chunk {i + 1}/{len(parts)}: no reply")
            continue
        lines.append(
            f"{path.name} [{source}] chunk {i + 1}/{len(parts)}: "
            f"messages={report.get('messages')} saved={len(report.get('saved') or [])} "
            f"skipped={len(report.get('skipped') or [])}"
        )
    try:
        state.path.unlink()
    except OSError:
        pass
    return Verdict("\n".join(lines))


_HANDLERS = {
    "session-start": _event_session_start,
    "prompt": _event_prompt,
    "tool-call": _event_tool_call,
    "tool-result": _event_tool_result,
    "session-end": _event_session_end,
}


def run_event(event: str, payload: dict, cfg: ClientConfig | None = None,
              client: McpClient | None = None) -> Verdict:
    """Run one hook event. Used by the CLI and by the tests."""
    cfg = cfg or load_client_config()
    client = client or McpClient(cfg)
    session = _session_id(payload)
    state = load_state(session, fresh=(event == "session-start"))
    try:
        verdict = _HANDLERS[event](client, payload, state, cfg)
    finally:
        if event != "session-end":
            state.save()
        client.close()
    if client.errors:
        print(f"neurostack hook {event}: {client.errors[0]}", file=sys.stderr)
    return verdict


def cmd_hook(args) -> None:
    """Read one event from stdin, print the verdict, exit 0 or 2.

    Fail open: anything unexpected becomes one stderr line and exit 0.
    """
    event = args.event
    try:
        raw = sys.stdin.read()
    except OSError as exc:
        print(f"neurostack hook {event}: stdin unreadable: {exc}", file=sys.stderr)
        return
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        print(f"neurostack hook {event}: stdin was not JSON", file=sys.stderr)
        return
    if not isinstance(payload, dict):
        print(f"neurostack hook {event}: stdin was not a JSON object", file=sys.stderr)
        return

    try:
        verdict = run_event(event, payload)
    except Exception as exc:  # a hook never takes the agent down with it
        print(f"neurostack hook {event}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return

    if verdict.block:
        # Claude Code reads stderr as the block reason on exit 2; every other
        # harness reads stdout. Both get the same text.
        stream = sys.stderr if getattr(args, "harness", None) == "claude" else sys.stdout
        print(verdict.text, file=stream)
        sys.exit(2)
    if verdict.text:
        print(verdict.text)
