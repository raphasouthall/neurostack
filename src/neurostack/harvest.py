# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Extract insights from Claude Code session transcripts and save as memories."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("neurostack")

_PATTERNS: dict[str, list[re.Pattern]] = {
    "bug": [re.compile(r"\b(root cause|fixed by|bug fix|traceback|stack trace|the fix was|error was)\b", re.I)],
    "decision": [re.compile(r"\b(decided to|switched from .+ to|chose .+ over|going with .+ because|opting for .+ instead)\b", re.I)],
    "convention": [re.compile(r"(always use|never use|rule:|convention:|must always|must never)\b", re.I)],
    "learning": [re.compile(r"\b(discovered that|turns out that|TIL:|learned that|found that .+ because|the reason is)\b", re.I)],
}
_MIN_LEN = 40
_MAX_SUMMARY = 200


def find_recent_sessions(n: int = 1) -> list[Path]:
    """Return the N most recent Claude Code session JSONL files.

    Claude Code stores transcripts as .jsonl files directly in project dirs
    (e.g. ~/.claude/projects/-home-raphasouthall/<uuid>.jsonl) and also in
    subagent subdirectories. We return the top-level session files only.
    """
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        return []
    sessions = []
    for proj in claude_dir.iterdir():
        if not proj.is_dir():
            continue
        for f in proj.glob("*.jsonl"):
            try:
                sessions.append((f.stat().st_mtime, f))
            except OSError:
                continue
    sessions.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in sessions[:n]]


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


def _extract_text(entry: dict) -> str | None:
    """Extract displayable text from a session entry."""
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


def _classify(text: str) -> str | None:
    """Classify text into an entity type. Returns None if no signal."""
    if len(text) < _MIN_LEN:
        return None
    for etype, patterns in _PATTERNS.items():
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


def harvest_sessions(
    n_sessions: int = 1,
    dry_run: bool = False,
    embed_url: str | None = None,
) -> dict:
    """Extract insights from recent sessions. Returns report dict."""
    from .config import get_config
    from .memories import save_memory
    from .schema import DB_PATH, get_db

    url = embed_url or get_config().embed_url
    conn = get_db(DB_PATH)

    sessions = find_recent_sessions(n_sessions)
    if not sessions:
        return {"error": "No Claude Code sessions found", "saved": [], "skipped": [], "counts": {}}

    saved, skipped = [], []
    counts: dict[str, int] = {}

    for session_file in sessions:
        for entry in _parse_jsonl(session_file):
                role = entry.get("message", {}).get("role", entry.get("type", ""))
                if role not in ("assistant", "tool_result"):
                    continue
                text = _extract_text(entry)
                if not text:
                    continue
                etype = _classify(text)
                if not etype:
                    continue
                summary = _make_summary(text)
                if len(summary) < _MIN_LEN:
                    continue

                tags = _extract_tags(text)
                ttl = 168.0 if etype == "context" else None
                item = {"content": summary, "entity_type": etype, "tags": tags, "ttl_hours": ttl}

                if _is_duplicate(conn, summary, etype):
                    item["status"] = "skipped (duplicate)"
                    skipped.append(item)
                    continue

                if dry_run:
                    item["status"] = "would save"
                    saved.append(item)
                else:
                    try:
                        mem = save_memory(
                            conn, content=summary, tags=tags, entity_type=etype,
                            source_agent="harvest", ttl_hours=ttl, embed_url=url,
                        )
                        item["memory_id"] = mem.memory_id
                        item["status"] = "saved"
                        saved.append(item)
                    except Exception as exc:
                        item["status"] = f"error: {exc}"
                        skipped.append(item)
                        continue
                counts[etype] = counts.get(etype, 0) + 1

    return {
        "sessions_scanned": len(sessions),
        "counts": counts,
        "saved": saved,
        "skipped": skipped,
        "dry_run": dry_run,
    }
