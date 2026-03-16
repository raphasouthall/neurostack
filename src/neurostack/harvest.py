# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Extract insights from Claude Code session transcripts and save as memories.

Two-tier approach:
  1. Broad regex pre-filter selects candidate messages
  2. Local LLM (Ollama) classifies and summarizes candidates
Falls back to regex-only if Ollama is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("neurostack")

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


def _llm_classify(
    candidates: list[dict],
    llm_url: str,
    llm_model: str,
) -> list[dict]:
    """Use local Ollama to classify and summarize candidate insights.

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


def harvest_sessions(
    n_sessions: int = 1,
    dry_run: bool = False,
    embed_url: str | None = None,
    use_llm: bool = True,
) -> dict:
    """Extract insights from recent sessions. Returns report dict.

    Two-tier approach:
      1. Broad regex pre-filter selects candidate messages
      2. Local LLM classifies and summarizes (falls back to regex-only)
    """
    from .config import get_config
    from .memories import save_memory
    from .schema import DB_PATH, get_db

    cfg = get_config()
    url = embed_url or cfg.embed_url
    conn = get_db(DB_PATH)

    sessions = find_recent_sessions(n_sessions)
    if not sessions:
        return {"error": "No Claude Code sessions found", "saved": [], "skipped": [], "counts": {}}

    saved, skipped = [], []
    counts: dict[str, int] = {}

    for session_file in sessions:
        entries = _parse_jsonl(session_file)
        candidates = []

        for entry in entries:
            role = entry.get("message", {}).get("role", entry.get("type", ""))
            if role not in ("assistant", "user"):
                continue
            text = _extract_text(entry)
            if not text or len(text) < _MIN_LEN:
                continue
            # Skip user messages that are system XML or very long pastes
            if role == "user" and (len(text) > 1000 or text.startswith("<")):
                continue

            prefilter_type = _prefilter_classify(text, role)
            if not prefilter_type:
                continue

            candidates.append({
                "text": text,
                "role": role,
                "prefilter_type": prefilter_type,
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
            record = {"content": summary, "entity_type": etype, "tags": tags, "ttl_hours": ttl}

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
                        source_agent="harvest", ttl_hours=ttl, embed_url=url,
                    )
                    record["memory_id"] = mem.memory_id
                    record["status"] = "saved"
                    saved.append(record)
                except Exception as exc:
                    record["status"] = f"error: {exc}"
                    skipped.append(record)
            counts[etype] = counts.get(etype, 0) + 1

    return {
        "sessions_scanned": len(sessions),
        "counts": counts,
        "saved": saved,
        "skipped": skipped,
        "dry_run": dry_run,
    }
