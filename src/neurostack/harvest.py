# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Extract insights from AI coding session transcripts and save as memories.

Supports multiple providers (Claude Code, VS Code Chat, Codex CLI, etc.)
via a pluggable provider architecture. Each provider knows how to find
its session files and extract text from its transcript format.

Two-tier classification:
  1. Broad regex pre-filter selects candidate messages
  2. Local LLM classifies and summarizes candidates
Falls back to regex-only if LLM is unavailable. With an LLM, a user
correction after a tool call or a fix after a tool error may be saved with a
``when-*`` trigger tag (issue #135) so it surfaces when the same thing recurs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .redact import redact_secrets

log = logging.getLogger("neurostack")


# ---------------------------------------------------------------------------
# Harvest state (deduplication across triggers)
# ---------------------------------------------------------------------------

def _harvest_state_path() -> Path:
    """Path to the harvest state file tracking already-processed sessions."""
    from .config import get_config
    return get_config().db_dir / "harvest_state.json"


def _load_harvest_state() -> dict[str, float | str]:
    """Load harvest state: session path -> mtime, or ``mcp:`` key -> transcript hash."""
    path = _harvest_state_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_harvest_state(state: dict[str, float | str]) -> None:
    """Persist harvest state atomically (temp file + os.replace)."""
    import os
    import tempfile

    path = _harvest_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Session provider protocol and registry
# ---------------------------------------------------------------------------

@dataclass
class SessionFile:
    """A discovered session file with its provider metadata."""
    path: Path
    mtime: float
    provider: str


@dataclass
class Message:
    """A single extracted message from a session transcript.

    ``prev_*`` carry the tool context that preceded this message (issue #135):
    the last tool the assistant called, the path that call targeted, and the
    first line of the most recent failed tool result. The classifier uses them
    to attach a trigger to a user correction or an error-then-fix.
    """
    role: str  # "user" or "assistant"
    text: str
    prev_tool: str | None = None
    prev_path: str | None = None
    prev_error: str | None = None


# A failed tool result stays attached to this many following messages: the fix
# usually lands in the next assistant turn, sometimes one or two later.
_ERROR_CONTEXT_MESSAGES = 3
_PATH_KEYS = ("file_path", "filePath", "path", "notebook_path")
_HASHLINE_HEADER = re.compile(r"^\[([^\]#]+)#[0-9A-Fa-f]{4}\]", re.MULTILINE)


class _ToolContext:
    """Rolling tool state a provider stamps onto each message it emits."""

    def __init__(self) -> None:
        self.tool: str | None = None
        self.path: str | None = None
        self.error: str | None = None
        self._error_left = 0

    def call(self, name, args) -> None:
        if not isinstance(name, str) or not name:
            return
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args = {}
        if not isinstance(args, dict):
            args = {}
        path = next((args[k] for k in _PATH_KEYS if isinstance(args.get(k), str)), None)
        if path is None and isinstance(args.get("input"), str):
            # omp hashline edits name the file in a ``[path#TAG]`` header.
            m = _HASHLINE_HEADER.search(args["input"])
            path = m.group(1) if m else None
        # Claude Code exposes MCP tools as ``mcp__<server>__<tool>``; omp routes
        # them through ``write`` to ``xd://mcp__<server>_<tool>``. Record the
        # name the harness would report for the call, minus the MCP plumbing.
        if path and path.startswith("xd://"):
            name = path[len("xd://"):].removeprefix("mcp__")
        elif name.startswith("mcp__") and "__" in name[5:]:
            name = name.rsplit("__", 1)[1]
        self.tool, self.path = name, path

    def result(self, is_error, content) -> None:
        if not is_error:
            return
        if isinstance(content, list):
            content = "\n".join(
                p["text"] for p in content
                if isinstance(p, dict) and isinstance(p.get("text"), str)
            )
        if not isinstance(content, str):
            return
        first = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
        if first:
            self.error = first[:200]
            self._error_left = _ERROR_CONTEXT_MESSAGES

    def stamp(self, msg: Message) -> Message:
        msg.prev_tool, msg.prev_path = self.tool, self.path
        if self._error_left > 0:
            msg.prev_error = self.error
            self._error_left -= 1
        else:
            self.error = None
        return msg


class SessionProvider(Protocol):
    """Interface for AI coding assistant session providers."""

    name: str

    def find_sessions(self, n: int) -> list[SessionFile]:
        """Return up to N most recent session files, sorted by mtime desc."""
        ...

    def extract_messages(self, path: Path) -> list[Message]:
        """Extract user/assistant messages from a session transcript file."""
        ...


class ClaudeCodeProvider:
    """Claude Code — ~/.claude/projects/*/*.jsonl"""

    name = "claude-code"

    def find_sessions(self, n: int) -> list[SessionFile]:
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return []
        sessions = []
        for proj in claude_dir.iterdir():
            if not proj.is_dir():
                continue
            for f in proj.glob("*.jsonl"):
                try:
                    st = f.stat()
                    sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
                except OSError:
                    continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        messages = []
        ctx = _ToolContext()
        for entry in _parse_jsonl(path):
            role = entry.get("message", {}).get("role", entry.get("type", ""))
            if role not in ("assistant", "user"):
                continue
            text = _extract_text_claude(entry)
            if text:
                messages.append(ctx.stamp(Message(role=role, text=text)))
            # Observe this entry's tool blocks AFTER stamping: ``prev_*`` means
            # what came before the message, not what it did itself.
            content = entry.get("message", {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        ctx.call(block.get("name"), block.get("input"))
                    elif block.get("type") == "tool_result":
                        ctx.result(block.get("is_error"), block.get("content"))
        return messages


class VSCodeChatProvider:
    """VS Code built-in chat — ~/.config/Code/User/**/chatSessions/*.jsonl"""

    name = "vscode-chat"

    def find_sessions(self, n: int) -> list[SessionFile]:
        import sys
        if sys.platform == "win32":
            base = Path.home() / "AppData" / "Roaming" / "Code" / "User"
        else:
            base = Path.home() / ".config" / "Code" / "User"
        if not base.exists():
            return []
        sessions = []
        # Global and workspace chat sessions
        for pattern in [
            "globalStorage/emptyWindowChatSessions/*.jsonl",
            "workspaceStorage/*/chatSessions/*.jsonl",
            "workspaceStorage/*/chatEditingSessions/*.jsonl",
        ]:
            for f in base.glob(pattern):
                try:
                    st = f.stat()
                    if st.st_size < 100:  # skip empty shells
                        continue
                    sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
                except OSError:
                    continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        messages = []
        for entry in _parse_jsonl(path):
            v = entry.get("v", entry)
            for req in v.get("requests", []):
                # User message
                user_msg = req.get("message", {}).get("text", "")
                if user_msg:
                    messages.append(Message(role="user", text=user_msg))
                # Assistant response
                resp = req.get("response", {})
                for part in resp.get("value", []):
                    if isinstance(part, dict):
                        text = part.get("value", "")
                        if isinstance(text, str) and text:
                            messages.append(Message(role="assistant", text=text))
        return messages


class CodexCLIProvider:
    """OpenAI Codex CLI — ~/.codex/sessions/**/*.jsonl (rollout files).

    Codex stores rollouts as JSONL under $CODEX_HOME/sessions/ (default
    ~/.codex/sessions/) in date-partitioned subdirectories:
        sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl

    Each line is a RolloutLine: {"timestamp": "...", "type": "<tag>", "payload": {...}}
    Messages are tagged "response_item" with payload {"type": "message", "role": "...",
    "content": [{"type": "output_text"|"input_text", "text": "..."}]}.
    """

    name = "codex-cli"

    def _codex_home(self) -> Path:
        import os
        return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))

    def find_sessions(self, n: int) -> list[SessionFile]:
        sessions_dir = self._codex_home() / "sessions"
        if not sessions_dir.exists():
            return []
        sessions = []
        # Rollouts live in date subdirs: sessions/YYYY/MM/DD/rollout-*.jsonl
        for f in sessions_dir.rglob("rollout-*.jsonl"):
            try:
                st = f.stat()
                sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
            except OSError:
                continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        messages = []
        for line_obj in _parse_jsonl(path):
            # RolloutLine has {"timestamp", "type", "payload"} via serde flatten
            item_type = line_obj.get("type", "")
            payload = line_obj.get("payload", line_obj)

            if item_type == "response_item":
                # ResponseItem::Message {role, content: [ContentItem]}
                if isinstance(payload, dict):
                    msg_payload = payload.get("payload", payload)
                else:
                    msg_payload = payload
                if not isinstance(msg_payload, dict):
                    continue
                role = msg_payload.get("role", "")
                if role not in ("assistant", "user"):
                    continue
                content = msg_payload.get("content", [])
                parts = []
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text", "")
                            if isinstance(text, str) and text:
                                parts.append(text)
                if parts:
                    messages.append(Message(role=role, text=" ".join(parts)))
            elif item_type == "session_meta":
                # Skip metadata lines
                continue
        return messages


class AiderProvider:
    """Aider — .aider.chat.history.md files in home and project dirs."""

    name = "aider"

    def find_sessions(self, n: int) -> list[SessionFile]:
        sessions = []
        # Check home dir and common project locations
        search_dirs = [Path.home()]
        projects_dir = Path.home() / "projects"
        if projects_dir.exists():
            search_dirs.extend(
                d for d in projects_dir.iterdir() if d.is_dir()
            )
        for d in search_dirs:
            for name in (".aider.chat.history.md", ".aider.chat.history"):
                f = d / name
                if f.exists():
                    try:
                        st = f.stat()
                        sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
                    except OSError:
                        continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        messages = []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        # Aider uses markdown headers: #### user\n... #### assistant\n...
        current_role = None
        current_text: list[str] = []
        for line in content.splitlines():
            header = re.match(r"^#{1,4}\s+(user|assistant)\s*$", line, re.I)
            if header:
                if current_role and current_text:
                    messages.append(Message(role=current_role, text="\n".join(current_text)))
                current_role = header.group(1).lower()
                current_text = []
            elif current_role:
                current_text.append(line)
        if current_role and current_text:
            messages.append(Message(role=current_role, text="\n".join(current_text)))
        return messages


class GeminiCLIProvider:
    """Google Gemini CLI — ~/.gemini/tmp/<project_hash>/chats/session-*.json

    Gemini CLI stores sessions as single JSON files (not JSONL) containing a
    ConversationRecord with a messages array. Each message has:
      - type: "user" | "gemini" | "info" | "error" | "warning"
      - content: string | Part | Part[]  (Part = {text: string} or similar)
      - toolCalls: optional array of tool call records
      - thoughts: optional array of reasoning summaries
    """

    name = "gemini-cli"

    def find_sessions(self, n: int) -> list[SessionFile]:
        gemini_dir = Path.home() / ".gemini" / "tmp"
        if not gemini_dir.exists():
            return []
        sessions = []
        # Sessions live in project hash subdirs: tmp/<hash>/chats/session-*.json
        for f in gemini_dir.rglob("chats/session-*.json"):
            try:
                st = f.stat()
                if st.st_size < 100:  # skip empty/corrupt files
                    continue
                sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
            except OSError:
                continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, dict):
            return []
        messages = []
        for msg in data.get("messages", []):
            msg_type = msg.get("type", "")
            if msg_type == "user":
                role = "user"
            elif msg_type == "gemini":
                role = "assistant"
            else:
                continue  # skip info/error/warning
            text = _extract_gemini_content(msg.get("content"))
            if text:
                messages.append(Message(role=role, text=text))
        return messages


def _extract_gemini_content(content) -> str | None:
    """Extract text from Gemini CLI PartListUnion content.

    Content can be: a string, a Part dict ({text: "..."}), or a list of
    strings/Part dicts.
    """
    if isinstance(content, str):
        return content if content.strip() else None
    if isinstance(content, dict):
        t = content.get("text", "")
        return t if isinstance(t, str) and t.strip() else None
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item)
            elif isinstance(item, dict):
                t = item.get("text", "")
                # Skip thought parts
                if item.get("thought"):
                    continue
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return " ".join(parts) if parts else None
    return None


class OmpProvider:
    """Oh My Pi — ~/.omp/agent/sessions/*/*.jsonl

    One JSONL per session, under a per-project subdirectory. Message lines are
    {"type": "message", "message": {"role": ..., "content": [part, ...]}}.
    Roles also include "toolResult", whose text parts are raw tool output —
    excluded, or the pre-filter drowns in it.
    """

    name = "omp"

    def find_sessions(self, n: int) -> list[SessionFile]:
        sessions_dir = Path.home() / ".omp" / "agent" / "sessions"
        if not sessions_dir.exists():
            return []
        sessions = []
        for f in sessions_dir.glob("*/*.jsonl"):
            try:
                st = f.stat()
                sessions.append(SessionFile(path=f, mtime=st.st_mtime, provider=self.name))
            except OSError:
                continue
        sessions.sort(key=lambda s: s.mtime, reverse=True)
        return sessions[:n]

    def extract_messages(self, path: Path) -> list[Message]:
        messages = []
        ctx = _ToolContext()
        for entry in _parse_jsonl(path):
            if entry.get("type") != "message":
                continue
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content")
            if role == "toolResult":
                ctx.result(msg.get("isError"), content)
                continue
            if role not in ("assistant", "user"):
                continue
            calls = []
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # Only "text" parts are transcript; "thinking" is noise and
                # "toolCall" parts feed the tool context for LATER messages.
                parts = []
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    if p.get("type") == "text" and isinstance(p.get("text"), str):
                        parts.append(p["text"])
                    elif p.get("type") == "toolCall":
                        calls.append(p)
                text = "\n".join(parts)
            else:
                continue
            if text:
                messages.append(ctx.stamp(Message(role=role, text=text)))
            for p in calls:
                ctx.call(p.get("name"), p.get("arguments"))
        return messages


# Provider registry — order doesn't matter, all are scanned
_PROVIDERS: list[SessionProvider] = [
    ClaudeCodeProvider(),
    VSCodeChatProvider(),
    CodexCLIProvider(),
    AiderProvider(),
    GeminiCLIProvider(),
    OmpProvider(),
]

_PROVIDER_MAP: dict[str, SessionProvider] = {p.name: p for p in _PROVIDERS}


def get_provider_names() -> list[str]:
    """Return list of registered provider names."""
    return list(_PROVIDER_MAP.keys())


def find_recent_sessions(
    n: int = 1,
    provider: str | None = None,
) -> list[SessionFile]:
    """Return the N most recent session files across all (or one) provider(s)."""
    providers = [_PROVIDER_MAP[provider]] if provider else _PROVIDERS
    all_sessions: list[SessionFile] = []
    for p in providers:
        try:
            all_sessions.extend(p.find_sessions(n))
        except Exception as exc:
            log.debug("Provider %s failed: %s", p.name, exc)
    all_sessions.sort(key=lambda s: s.mtime, reverse=True)
    return all_sessions[:n]


def extract_messages(session: SessionFile) -> list[Message]:
    """Extract messages from a session file using its provider."""
    p = _PROVIDER_MAP.get(session.provider)
    if not p:
        return []
    return p.extract_messages(session.path)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, skipping malformed lines."""
    entries = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    except OSError as exc:
        log.debug("Could not read %s: %s", path, exc)
    return entries


def _extract_text_claude(entry: dict) -> str | None:
    """Extract displayable text from a Claude Code session entry."""
    content = entry.get("message", {}).get("content", entry.get("content"))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text", block.get("content", ""))
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts) if parts else None
    return None


# ---------------------------------------------------------------------------
# Pre-filter patterns and classification
# ---------------------------------------------------------------------------

# Broad pre-filter patterns - these select CANDIDATES for LLM review.
# False positives are fine (LLM filters them); false negatives are not.
_PREFILTER: dict[str, list[re.Pattern]] = {
    "bug": [re.compile(
        r"\b(root cause|fixed by|bug fix|traceback|stack trace|the fix was"
        r"|error was|the issue was|broke because|failed because"
        r"|workaround|regression|the problem was)\b", re.I,
    )],
    "decision": [re.compile(
        r"\b(decided to|switched from|chose .+ over|going with|opting for"
        r"|approach:|architecture:|design:|we.ll use|plan is to"
        r"|recommended|the flow is|pipeline:|strategy:)\b", re.I,
    )],
    "convention": [re.compile(
        r"\b(always use|never use|rule:|convention:|must always|must never"
        r"|important:|careful:|warning:|don.t forget"
        r"|make sure to|remember to)\b", re.I,
    )],
    "learning": [re.compile(
        r"\b(discovered that|turns out|TIL:|learned that|found that"
        r"|the reason is|key finding|it.s actually|didn.t know"
        r"|wasn.t aware|interesting)\b", re.I,
    )],
    # Credentials, endpoints, URLs and current-state facts go stale quickly —
    # default them to ephemeral 'context' (168h TTL). The LLM still overrides
    # per-item to 'observation' when a match is genuinely durable (issue #30).
    "context": [re.compile(
        r"\b(credential|api.?key|endpoint|connection.?string"
        r"|host(name)?:|port:|url:|stored at|located at"
        r"|config\.toml|\.env\b)\b", re.I,
    )],
}
# User correction patterns - high signal, scan user messages only
_USER_CORRECTION = re.compile(
    r"^(wait|no[,. !]|don.t|stop|wrong|instead|actually|not that"
    r"|I said|I meant|that.s not)", re.I,
)

_MIN_LEN = 40
_MAX_SUMMARY = 200


def _prefilter_classify(text: str, role: str) -> str | None:
    """Pre-filter classify text. Returns candidate entity type or None."""
    if len(text) < _MIN_LEN:
        return None
    # User corrections are high signal
    if role == "user" and _USER_CORRECTION.search(text):
        return "convention"
    for etype, patterns in _PREFILTER.items():
        for pat in patterns:
            if pat.search(text):
                return etype
    return None


def _make_summary(text: str) -> str:
    """Extract a one-line summary from text."""
    text = re.sub(r"\s+", " ", text.strip().replace("\n", " "))
    match = re.match(r"^(.{20,}?[.!?])\s", text)
    if match and len(match.group(1)) <= _MAX_SUMMARY:
        return match.group(1)
    return text[:_MAX_SUMMARY - 3] + "..." if len(text) > _MAX_SUMMARY else text


def _extract_tags(text: str) -> list[str]:
    """Extract tags from file paths mentioned in text."""
    tags = set()
    exts = {"py", "ts", "js", "rs", "go", "md", "toml", "yaml", "yml", "json"}
    for m in re.finditer(r"[\w/.-]+\.\w{1,10}", text):
        path = m.group()
        ext = path.rsplit(".", 1)[-1].lower()
        if ext in exts:
            tags.add(ext)
        parts = path.split("/")
        if len(parts) > 1:
            tags.add(parts[-2] if parts[-2] else parts[0])
    return sorted(tags)[:5]


# Cosine similarity at/above which two same-type memories are treated as
# duplicates during harvest (issue #36).
DEDUP_COSINE_THRESHOLD = 0.88


def _is_duplicate(
    conn, content: str, entity_type: str, embed_url: str | None = None
) -> bool:
    """True if a substantially similar memory already exists.

    Prefers semantic (cosine) similarity so paraphrases with different wording
    are caught — FTS5's strict all-terms match lets "three Harrods supply-chain
    paraphrases" through as distinct (issue #36). The FTS5 keyword match stays as
    a floor: it runs whenever the cosine check doesn't flag a duplicate — both
    when embeddings are unavailable (lite mode / embedder down) and when a
    keyword-overlapping pair falls below the cosine threshold — so dedup never
    silently switches off.
    """
    try:
        from .memories import find_similar_memories

        if find_similar_memories(
            conn, content, entity_type=entity_type,
            threshold=DEDUP_COSINE_THRESHOLD, limit=1, embed_url=embed_url,
        ):
            return True
    except Exception:
        pass
    return _fts_duplicate(conn, content, entity_type)


def _fts_duplicate(conn, content: str, entity_type: str) -> bool:
    """FTS5 keyword-overlap duplicate check — the pre-cosine floor."""
    words = re.findall(r"\b\w{4,}\b", content.lower())
    if not words:
        return False
    words = sorted(set(words), key=len, reverse=True)[:5]
    query = " ".join(f'"{w}"' for w in words)
    try:
        rows = conn.execute(
            "SELECT m.content FROM memories_fts "
            "JOIN memories m ON m.memory_id = memories_fts.rowid "
            "WHERE memories_fts MATCH ? AND m.entity_type = ? LIMIT 3",
            (query, entity_type),
        ).fetchall()
        return len(rows) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------

# Classifier batch size. 10 let the model stop early ("answered 1 of 10")
# even at a 16k context; 5 halves the answer it must sustain (issue #127).
CLASSIFY_BATCH_SIZE = 5

_VALID_TYPES = frozenset(
    {"bug", "decision", "convention", "learning", "observation", "context"}
)

_CLASSIFY_PROMPT_HEAD = (
    "You are analyzing an AI coding session transcript.\n\n"
    "There are {n} numbered messages below. Reply with ONLY a JSON array of "
    "EXACTLY {n} objects, one per message, in order, n from 1 to {n}. "
    "No preamble, no code fence.\n\n"
    "Each object is either:\n"
    '{{"n": N, "verdict": "KEEP", "type": "<bug|decision|convention|learning|'
    'observation|context>", "summary": "<one sentence>", '
    '"trigger": "<only when the trigger rule below applies>"}}\n'
    'or {{"n": N, "verdict": "SKIP"}}\n\n'
    "KEEP a message that records any of: an architectural or tooling "
    "decision, a bug's root cause or fix, a rule to follow, a discovered "
    "fact about a system, a user correction or preference, or a short-lived "
    "operational fact such as an endpoint, credential location or "
    "current-state note.\n"
    "SKIP a message that is only progress narration, a restatement of the "
    "task, a question back to the user, or raw command output. A message "
    "that says what the user asked for, or what the assistant is about to "
    "do, is narration - SKIP it.\n\n"
    "Type guide: bug=root cause/fix, decision=choice made, "
    "convention=rule to always follow, learning=discovered fact, "
    "observation=durable infrastructure fact, "
    "context=ephemeral/short-lived fact kept only short-term.\n\n"
    "Trigger rule. Some messages carry a line starting \"context:\" that names "
    "the tool the assistant had just called (and its path) and any tool error "
    "just before the message. If such a line is present AND the message is a "
    "user correction or a fix, the KEEP object MUST include \"trigger\":\n"
    '- user corrects what a tool call did -> "calling:<tool name from the '
    'context line>"\n'
    '- user corrects an edit or write to a file -> "editing:<path from the '
    'context line>"\n'
    '- assistant fixes the error from the context line -> "error:<short '
    'distinctive substring of that error>"\n'
    "No context line, or not a correction or fix: omit \"trigger\".\n\n"
    "Examples:\n"
    "(assistant) Cloning the repo now and reading the layout for you.\n"
    '-> {{"n": 1, "verdict": "SKIP"}}\n'
    "(user) Get context on the website and review its content.\n"
    '-> {{"n": 2, "verdict": "SKIP"}}\n'
    "(assistant) The 502s came from the ingress timeout at 30s; raised to 120s.\n"
    '-> {{"n": 3, "verdict": "KEEP", "type": "bug", "summary": "502s were the '
    'ingress 30s timeout; raised to 120s"}}\n'
    "(assistant) We will use merge commits, not squash, for this repo.\n"
    '-> {{"n": 4, "verdict": "KEEP", "type": "decision", "summary": "Repo uses '
    'merge commits, not squash"}}\n'
    "(user) No, never force-push to main; open a PR instead.\n"
    "  context: last tool call git_push on main\n"
    '-> {{"n": 5, "verdict": "KEEP", "type": "convention", "summary": "Never '
    'force-push to main; open a PR", "trigger": "calling:git_push"}}\n\n'
    "Messages:\n{messages}\n\nAnswer:"
)


def _parse_classify_reply(response: str, batch_len: int) -> dict[int, dict]:
    """Map 0-based candidate index -> verdict object from the model's reply.

    Tolerates a code fence or stray prose around the array; ignores objects
    with an out-of-range or missing ``n``. A bare object (what small models
    return for a one-candidate batch, including every one-candidate retry)
    counts as a one-element array.
    """
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL)
    start, end = response.find("["), response.rfind("]")
    if start < 0 or end <= start:
        start, end = response.find("{"), response.rfind("}")
        if start < 0 or end <= start:
            return {}
    try:
        items = json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        return {}
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return {}
    verdicts: dict[int, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        n = item.get("n")
        if not isinstance(n, int) or not (1 <= n <= batch_len):
            continue
        verdicts[n - 1] = item
    return verdicts


def _context_line(c: dict) -> str:
    """Render a candidate's preceding tool call and error for the classifier."""
    parts = []
    if c.get("prev_tool"):
        call = f"last tool call {c['prev_tool']}"
        if c.get("prev_path"):
            call += f" on {c['prev_path']}"
        parts.append(call)
    if c.get("prev_error"):
        parts.append(f'last tool error "{c["prev_error"]}"')
    return "; ".join(parts)


def _classify_batch(
    batch: list[dict], llm_url: str, llm_model: str
) -> dict[int, dict]:
    """One classifier call. Raises on transport/HTTP failure."""
    import httpx

    from .config import _auth_headers, get_config

    numbered = []
    for i, c in enumerate(batch):
        role = c.get("role", "assistant")
        line = f"[{i + 1}] ({role}) {c['text'][:800]}"
        ctx = _context_line(c)
        if ctx:
            line += "\n  context: " + ctx
        numbered.append(line)
    prompt = _CLASSIFY_PROMPT_HEAD.format(
        n=len(batch), messages="\n---\n".join(numbered),
    )
    resp = httpx.post(
        f"{llm_url}/v1/chat/completions",
        headers=_auth_headers(get_config().llm_api_key),
        json={
            "model": llm_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "reasoning_effort": "none",
            "temperature": 0.1,
            # One JSON object per candidate, each carrying a summary: 500
            # truncated a 10-message answer mid-line (issue #117).
            "max_tokens": 2000,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return _parse_classify_reply(
        resp.json()["choices"][0]["message"]["content"], len(batch),
    )


def _llm_classify(
    candidates: list[dict],
    llm_url: str,
    llm_model: str,
) -> list[dict]:
    """Use local LLM to classify and summarize candidate insights.

    Sends batches of CLASSIFY_BATCH_SIZE, JSON in and out, validated against
    the batch size; candidates the model left unanswered get ONE retry as a
    smaller batch (issue #127). Returns only those the LLM judges worth
    remembering long-term.
    """
    if not candidates:
        return []

    results = []
    for batch_start in range(0, len(candidates), CLASSIFY_BATCH_SIZE):
        batch = candidates[batch_start:batch_start + CLASSIFY_BATCH_SIZE]
        try:
            verdicts = _classify_batch(batch, llm_url, llm_model)
        except Exception as exc:
            log.warning("LLM classify failed: %s - falling back to regex", exc)
            # Fallback: keep only keyword-hit candidates (issue #125 widened
            # the batch to every qualified message; without a keyword type
            # there is nothing to classify them as, and saving them all would
            # turn one LLM outage into a hundred junk memories).
            for c in batch:
                if not c["prefilter_type"]:
                    continue
                c["summary"] = _make_summary(c["text"])
                c["entity_type"] = c["prefilter_type"]
                results.append(c)
            continue

        missing = [i for i in range(len(batch)) if i not in verdicts]
        if missing:
            # The model stops early on some batches whatever the context
            # size; one retry on just the unanswered candidates recovers most.
            try:
                retry = _classify_batch([batch[i] for i in missing], llm_url, llm_model)
            except Exception as exc:
                log.warning("LLM classify retry failed: %s", exc)
                retry = {}
            for j, v in retry.items():
                verdicts[missing[j]] = v

        for idx, item in sorted(verdicts.items()):
            if str(item.get("verdict", "")).upper() != "KEEP":
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            c = batch[idx].copy()
            etype = str(item.get("type", "")).strip()
            c["entity_type"] = (
                etype if etype in _VALID_TYPES
                else c["prefilter_type"] or "observation"
            )
            c["summary"] = summary
            trigger = item.get("trigger")
            if isinstance(trigger, str) and trigger.strip():
                c["trigger"] = trigger.strip()
            results.append(c)

        # A batch the model only partly answered is a silent capture loss: the
        # unanswered candidates are dropped, and an all-SKIP reply is otherwise
        # indistinguishable from a reply that never arrived (issue #117). Say so.
        dropped = len(batch) - len(verdicts)
        if dropped:
            log.warning(
                "LLM classify answered %d of %d candidates - %d dropped unclassified",
                len(verdicts), len(batch), dropped,
            )

    return results


# Cap on a when-error: value. Error lines run long; the match is a substring,
# so the head of the line is what matters.
_MAX_ERROR_TRIGGER = 40
_GLOB_CHARS = frozenset("*?[")


def _trigger_tag(raw) -> str | None:
    """Turn a classifier-emitted ``<event>:<value>`` into a ``when-*`` tag.

    Normalises what the model is likely to get slightly wrong: tool names and
    error text are lowercased (matching is case-insensitive anyway, so the tag
    reads consistently), error text is capped, and a literal file path becomes
    a glob over its directory so the memory fires for sibling files too.
    Anything that still fails :func:`triggers.parse_trigger` is dropped with
    one log line; the memory itself is unaffected.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    from .triggers import parse_trigger

    event, _, value = raw.strip().partition(":")
    event, value = event.strip().lower(), value.strip()
    if event == "calling":
        value = value.lower()
    elif event == "error":
        value = value.lower()[:_MAX_ERROR_TRIGGER]
    elif event == "editing" and value and not (_GLOB_CHARS & set(value)):
        head, sep, leaf = value.rpartition("/")
        if sep and "." in leaf:
            value = head + "/*"
    tag = f"when-{event}:{value}"
    if parse_trigger(tag) is None:
        log.info("harvest: dropping malformed trigger %r", raw)
        return None
    return tag


# ---------------------------------------------------------------------------
# Shared harvest core
# ---------------------------------------------------------------------------

def _harvest_messages(
    conn,
    messages: list[Message],
    provider: str,
    *,
    cfg,
    embed_url: str | None,
    dry_run: bool,
    use_llm: bool,
    saved: list[dict],
    skipped: list[dict],
    counts: dict[str, int],
) -> None:
    """Classify one transcript's messages and save the keepers.

    The seam shared by both entry points: ``harvest_sessions`` (session files on
    this machine's disk) and ``harvest_transcript`` (a transcript posted over
    MCP). Results accumulate into the caller's ``saved``/``skipped``/``counts``,
    so a multi-session caller needs no per-session merge step. Redaction lives
    here, ahead of the dedup check, so both callers inherit the issue #113
    contract by construction.
    """
    from .memories import save_memory

    candidates = []

    # The keyword prefilter gates only the regex paths. With an LLM available
    # every qualified message is a candidate: measured on a real 167-message
    # session, the keyword gate passed 0 of 145 length-qualified messages, so
    # whole sessions never reached the classifier (issue #125). The keyword
    # hit survives as a type hint the LLM path falls back on.
    for msg in messages:
        if not msg.text or len(msg.text) < _MIN_LEN:
            continue
        # Skip user messages that are system XML or very long pastes
        if msg.role == "user" and (len(msg.text) > 1000 or msg.text.startswith("<")):
            continue

        prefilter_type = _prefilter_classify(msg.text, msg.role)
        if not prefilter_type and not use_llm:
            continue

        candidates.append({
            "text": msg.text,
            "role": msg.role,
            "prefilter_type": prefilter_type,
            "provider": provider,
            "prev_tool": msg.prev_tool,
            "prev_path": msg.prev_path,
            "prev_error": msg.prev_error,
        })

    # Tier 2: LLM classification
    if use_llm and candidates:
        classified = _llm_classify(candidates, cfg.llm_url, cfg.llm_model)
    else:
        # Fallback: regex classification + naive summary
        classified = []
        for c in candidates:
            c["entity_type"] = c["prefilter_type"]
            c["summary"] = _make_summary(c["text"])
            classified.append(c)

    # Save classified insights
    for item in classified:
        summary = item.get("summary", _make_summary(item["text"]))
        # Transcripts carry live credentials; a summary must never store one
        # (issue #113). Redact BEFORE the dedup check so the stored form and
        # the deduped form are the same string.
        summary, redacted = redact_secrets(summary)
        etype = item.get("entity_type", item.get("prefilter_type", "observation"))

        if len(summary) < _MIN_LEN:
            continue

        tags = _extract_tags(item["text"])
        # A model-emitted trigger becomes a when-* tag so the memory surfaces
        # the next time the same tool call or error happens (issue #135).
        trigger = _trigger_tag(item.get("trigger"))
        if trigger:
            tags.append(trigger)
        # Harvest-created rows only: agent-written memories keep their
        # caller-chosen TTL. Auto-captured context goes stale in a week;
        # auto-captured observations get 30 days to be synthesized into a
        # learning (issue #36) before they expire as noise.
        ttl = {"context": 168.0, "observation": 720.0}.get(etype)
        record = {"content": summary, "entity_type": etype, "tags": tags,
                  "ttl_hours": ttl, "provider": provider}
        if trigger:
            record["trigger"] = trigger
        if redacted:
            record["redacted"] = redacted

        if _is_duplicate(conn, summary, etype, embed_url=embed_url):
            record["status"] = "skipped (duplicate)"
            skipped.append(record)
            continue

        if dry_run:
            record["status"] = "would save"
            saved.append(record)
        else:
            try:
                mem = save_memory(
                    conn, content=summary, tags=tags, entity_type=etype,
                    source_agent=f"harvest/{provider}", ttl_hours=ttl,
                    embed_url=embed_url,
                )
                record["memory_id"] = mem.memory_id
                record["status"] = "saved"
                saved.append(record)
            except Exception as exc:
                record["status"] = f"error: {exc}"
                skipped.append(record)
        counts[etype] = counts.get(etype, 0) + 1


# ---------------------------------------------------------------------------
# Main harvest entry points
# ---------------------------------------------------------------------------

def harvest_sessions(
    n_sessions: int = 1,
    dry_run: bool = False,
    embed_url: str | None = None,
    use_llm: bool = True,
    provider: str | None = None,
) -> dict:
    """Extract insights from recent sessions. Returns report dict.

    Two-tier approach:
      1. Broad regex pre-filter selects candidate messages
      2. Local LLM classifies and summarizes (falls back to regex-only)

    Args:
        n_sessions: Number of recent sessions to scan.
        dry_run: If True, show what would be saved without saving.
        embed_url: Override embedding URL.
        use_llm: Use LLM for classification (falls back to regex if False).
        provider: Restrict to a single provider name, or None for all.
    """
    from .config import get_config
    from .schema import DB_PATH, get_db

    cfg = get_config()
    url = embed_url or cfg.embed_url
    conn = get_db(DB_PATH)

    all_sessions = find_recent_sessions(n_sessions, provider=provider)
    if not all_sessions:
        return {"error": "No sessions found", "saved": [], "skipped": [], "counts": {}}

    # Filter out sessions already harvested at their current mtime
    harvest_state = _load_harvest_state()
    sessions = []
    for s in all_sessions:
        prev_mtime = harvest_state.get(str(s.path))
        # `mcp:` keys hold a transcript hash, never an mtime — compare numbers only.
        if isinstance(prev_mtime, (int, float)) and prev_mtime == s.mtime:
            log.debug("Skipping already-harvested session: %s (%s)", s.path.name, s.provider)
            continue
        sessions.append(s)

    if not sessions:
        return {"sessions_scanned": 0, "counts": {}, "saved": [], "skipped": [],
                "dry_run": dry_run, "note": "all sessions already harvested"}

    saved, skipped = [], []
    counts: dict[str, int] = {}

    for session in sessions:
        _harvest_messages(
            conn, extract_messages(session), session.provider,
            cfg=cfg, embed_url=url, dry_run=dry_run, use_llm=use_llm,
            saved=saved, skipped=skipped, counts=counts,
        )

    # Record harvested sessions (skip on dry run)
    if not dry_run:
        for s in sessions:
            harvest_state[str(s.path)] = s.mtime
        _save_harvest_state(harvest_state)

    return {
        "sessions_scanned": len(sessions),
        "providers": list({s.provider for s in sessions}),
        "counts": counts,
        "saved": saved,
        "skipped": skipped,
        "dry_run": dry_run,
    }


# Cap on a single posted transcript. Above this the client must split on newline
# boundaries and post each chunk separately: chunks are harvested independently
# and the cosine dedup absorbs whatever the split overlaps.
MAX_TRANSCRIPT_BYTES = 4 * 1024 * 1024


def harvest_transcript(
    transcript: str,
    session_id: str,
    source_agent: str,
    dry_run: bool = False,
    embed_url: str | None = None,
    use_llm: bool = True,
) -> dict:
    """Extract insights from a POSTED transcript. Returns report dict.

    The MCP-native counterpart to ``harvest_sessions`` (issue #115): the client
    sends its own session text, so the server needs no access to the client's
    filesystem. Classification, redaction and dedup are the same code path.

    Args:
        transcript: Raw session text in ``source_agent``'s native format.
        session_id: Client-side session id, used for the re-post guard.
        source_agent: Registered provider name — names the transcript FORMAT.
        dry_run: If True, show what would be saved without saving.
        embed_url: Override embedding URL.
        use_llm: Use LLM for classification (falls back to regex if False).
    """
    import hashlib
    import tempfile

    from .config import get_config
    from .schema import DB_PATH, get_db

    def _err(msg: str) -> dict:
        return {"error": msg, "saved": [], "skipped": [], "counts": {}}

    prov = _PROVIDER_MAP.get(source_agent)
    if prov is None:
        return _err(
            f"Unknown source_agent '{source_agent}' — must be one of: "
            f"{', '.join(get_provider_names())}"
        )
    if not transcript.strip():
        return _err("Empty transcript")

    raw = transcript.encode("utf-8")
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        return _err(
            f"Transcript is {len(raw)} bytes, over the {MAX_TRANSCRIPT_BYTES} "
            "byte cap. Split it on newline boundaries and post each chunk as a "
            "separate call — chunks are harvested independently and the dedup "
            "absorbs any overlap."
        )

    # Re-post guard: same session id + same bytes is a no-op, so a client can
    # retry a failed POST without duplicating work.
    digest = hashlib.sha256(raw).hexdigest()
    state_key = f"mcp:{source_agent}:{session_id}"
    harvest_state = _load_harvest_state()
    if harvest_state.get(state_key) == digest:
        return {"sessions_scanned": 0, "session_id": session_id,
                "provider": source_agent, "providers": [source_agent],
                "counts": {}, "saved": [], "skipped": [], "dry_run": dry_run,
                "note": "transcript already harvested"}

    cfg = get_config()
    url = embed_url or cfg.embed_url
    conn = get_db(DB_PATH)

    # The provider parsers read a path, so the posted text becomes a temp file
    # rather than every provider growing a second entry point.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(transcript)
        messages = prov.extract_messages(Path(tmp_path))
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    saved: list[dict] = []
    skipped: list[dict] = []
    counts: dict[str, int] = {}
    if messages:
        _harvest_messages(
            conn, messages, source_agent,
            cfg=cfg, embed_url=url, dry_run=dry_run, use_llm=use_llm,
            saved=saved, skipped=skipped, counts=counts,
        )

    # Record the digest only if the run actually yielded something. LLM
    # classification is not deterministic (issue #117), so a zero-yield run may
    # simply have been unlucky — leaving it unrecorded lets a client re-post and
    # pick up what the classifier dropped, instead of the guard making that loss
    # permanent.
    if not dry_run and (saved or skipped):
        harvest_state[state_key] = digest
        _save_harvest_state(harvest_state)

    return {
        "sessions_scanned": 1,
        "session_id": session_id,
        "provider": source_agent,
        "providers": [source_agent],
        "messages": len(messages),
        "counts": counts,
        "saved": saved,
        "skipped": skipped,
        "dry_run": dry_run,
    }
