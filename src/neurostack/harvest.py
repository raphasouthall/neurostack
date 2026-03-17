# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Extract insights from AI coding session transcripts and save as memories.

Supports multiple providers (Claude Code, VS Code Chat, Codex CLI, etc.)
via a pluggable provider architecture. Each provider knows how to find
its session files and extract text from its transcript format.

Two-tier classification:
  1. Broad regex pre-filter selects candidate messages
  2. Local LLM classifies and summarizes candidates
Falls back to regex-only if LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

log = logging.getLogger("neurostack")


# ---------------------------------------------------------------------------
# Harvest state (deduplication across triggers)
# ---------------------------------------------------------------------------

def _harvest_state_path() -> Path:
    """Path to the harvest state file tracking already-processed sessions."""
    from .config import get_config
    return get_config().db_dir / "harvest_state.json"


def _load_harvest_state() -> dict[str, float]:
    """Load harvest state: mapping of session file path -> mtime at harvest."""
    path = _harvest_state_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_harvest_state(state: dict[str, float]) -> None:
    """Persist harvest state."""
    path = _harvest_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


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
    """A single extracted message from a session transcript."""
    role: str  # "user" or "assistant"
    text: str


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
        for entry in _parse_jsonl(path):
            role = entry.get("message", {}).get("role", entry.get("type", ""))
            if role not in ("assistant", "user"):
                continue
            text = _extract_text_claude(entry)
            if text:
                messages.append(Message(role=role, text=text))
        return messages


class VSCodeChatProvider:
    """VS Code built-in chat — ~/.config/Code/User/**/chatSessions/*.jsonl"""

    name = "vscode-chat"

    def find_sessions(self, n: int) -> list[SessionFile]:
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


# Provider registry — order doesn't matter, all are scanned
_PROVIDERS: list[SessionProvider] = [
    ClaudeCodeProvider(),
    VSCodeChatProvider(),
    CodexCLIProvider(),
    AiderProvider(),
    GeminiCLIProvider(),
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
    "observation": [re.compile(
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


def _is_duplicate(conn, content: str, entity_type: str) -> bool:
    """Check if a substantially similar memory already exists via FTS5."""
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

def _llm_classify(
    candidates: list[dict],
    llm_url: str,
    llm_model: str,
) -> list[dict]:
    """Use local LLM to classify and summarize candidate insights.

    Sends a batch prompt with candidates. Returns only those the LLM
    judges as genuinely worth remembering long-term.
    """
    import httpx

    if not candidates:
        return []

    # Process in batches of 10
    results = []
    for batch_start in range(0, len(candidates), 10):
        batch = candidates[batch_start:batch_start + 10]
        numbered = []
        for i, c in enumerate(batch):
            role = c.get("role", "assistant")
            text = c["text"][:800]
            numbered.append(f"[{i + 1}] ({role}) {text}")

        batch_text = "\n---\n".join(numbered)

        prompt = (
            "You are analyzing an AI coding session transcript. "
            "For each numbered message below, decide if it contains a "
            "genuinely useful insight worth remembering long-term. "
            "Insights include: architectural decisions, bug root causes, "
            "tool configurations, user corrections/preferences, "
            "discovered facts about infrastructure.\n\n"
            "Skip boilerplate, status updates, and routine tool output.\n\n"
            "For each message, respond with EXACTLY one line:\n"
            "[N] KEEP type=<bug|decision|convention|learning|observation> "
            "summary=<one sentence summary>\n"
            "OR:\n"
            "[N] SKIP\n\n"
            "Messages:\n" + batch_text + "\n\nAnalysis:"
        )

        try:
            from .config import _auth_headers, get_config
            resp = httpx.post(
                f"{llm_url}/v1/chat/completions",
                headers=_auth_headers(get_config().llm_api_key),
                json={
                    "model": llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "reasoning_effort": "none",
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            response = resp.json()["choices"][0]["message"]["content"]
            # Strip think tags if present
            response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL)
        except Exception as exc:
            log.warning("LLM classify failed: %s - falling back to regex", exc)
            # Fallback: keep all candidates with regex classification
            for c in batch:
                c["summary"] = _make_summary(c["text"])
                c["entity_type"] = c["prefilter_type"]
                results.append(c)
            continue

        for line in response.strip().splitlines():
            m = re.match(
                r"\[(\d+)\]\s+KEEP\s+type=(\w+)\s+summary=(.+)",
                line.strip(),
            )
            if not m:
                continue
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(batch):
                c = batch[idx].copy()
                etype = m.group(2).strip()
                valid = {"bug", "decision", "convention", "learning", "observation"}
                if etype in valid:
                    c["entity_type"] = etype
                else:
                    c["entity_type"] = c["prefilter_type"]
                c["summary"] = m.group(3).strip()
                results.append(c)

    return results


# ---------------------------------------------------------------------------
# Main harvest entry point
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
    from .memories import save_memory
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
        if prev_mtime is not None and prev_mtime == s.mtime:
            log.debug("Skipping already-harvested session: %s (%s)", s.path.name, s.provider)
            continue
        sessions.append(s)

    if not sessions:
        return {"sessions_scanned": 0, "counts": {}, "saved": [], "skipped": [],
                "dry_run": dry_run, "note": "all sessions already harvested"}

    saved, skipped = [], []
    counts: dict[str, int] = {}

    for session in sessions:
        messages = extract_messages(session)
        candidates = []

        for msg in messages:
            if not msg.text or len(msg.text) < _MIN_LEN:
                continue
            # Skip user messages that are system XML or very long pastes
            if msg.role == "user" and (len(msg.text) > 1000 or msg.text.startswith("<")):
                continue

            prefilter_type = _prefilter_classify(msg.text, msg.role)
            if not prefilter_type:
                continue

            candidates.append({
                "text": msg.text,
                "role": msg.role,
                "prefilter_type": prefilter_type,
                "provider": session.provider,
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
            etype = item.get("entity_type", item.get("prefilter_type", "observation"))

            if len(summary) < _MIN_LEN:
                continue

            tags = _extract_tags(item["text"])
            ttl = 168.0 if etype == "context" else None
            record = {"content": summary, "entity_type": etype, "tags": tags,
                      "ttl_hours": ttl, "provider": session.provider}

            if _is_duplicate(conn, summary, etype):
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
                        source_agent=f"harvest/{session.provider}", ttl_hours=ttl,
                        embed_url=url,
                    )
                    record["memory_id"] = mem.memory_id
                    record["status"] = "saved"
                    saved.append(record)
                except Exception as exc:
                    record["status"] = f"error: {exc}"
                    skipped.append(record)
            counts[etype] = counts.get(etype, 0) + 1

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
