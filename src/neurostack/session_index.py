#!/usr/bin/env python3
"""neurostack.session_index: FTS5 search over Claude Code session transcripts.

Ported from session-index (~/tools/session-index/session_index.py).
Still works as a standalone script for backward compatibility.
"""

import argparse
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "NEUROSTACK_SESSION_DB",
    os.environ.get(
        "SESSION_INDEX_DB",
        str(Path.home() / ".local" / "share" / "neurostack" / "sessions.db"),
    ),
))
SESSIONS_DIR = Path(os.environ.get(
    "NEUROSTACK_SESSION_DIR",
    os.environ.get(
        "SESSION_INDEX_DIR",
        os.path.expanduser("~/.claude/projects"),
    ),
))

def parse_since(value: str) -> str:
    """Parse a --since value like '2d', '3h', '1w', '30m' into an ISO cutoff timestamp."""
    m = re.fullmatch(r"(\d+)([smhdw])", value.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(
            f"Invalid --since format '{value}'. Use e.g. 2d, 3h, 1w, 30m, 90s"
        )
    n, unit = int(m.group(1)), m.group(2)
    delta = {"s": timedelta(seconds=n), "m": timedelta(minutes=n),
             "h": timedelta(hours=n), "d": timedelta(days=n),
             "w": timedelta(weeks=n)}[unit]
    cutoff = datetime.now(timezone.utc) - delta
    return cutoff.strftime("%Y-%m-%dT%H:%M:%S")


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project    TEXT,
    slug       TEXT,
    version    TEXT,
    cwd        TEXT,
    first_ts   TEXT,
    last_ts    TEXT,
    file_mtime REAL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    uuid       TEXT UNIQUE,
    role       TEXT NOT NULL,  -- user, assistant, system, tool_use, tool_result
    content    TEXT NOT NULL,
    timestamp  TEXT,
    tool_name  TEXT,
    file_paths TEXT,           -- comma-separated file paths mentioned
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role,
    tool_name,
    session_id UNINDEXED,
    content='messages',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, tool_name, session_id)
    VALUES (new.id, new.content, new.role, new.tool_name, new.session_id);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, tool_name, session_id)
    VALUES ('delete', old.id, old.content, old.role, old.tool_name, old.session_id);
END;
"""


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def extract_text_content(message_data: dict) -> str:
    """Extract readable text from a message's content field."""
    content = message_data.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "thinking":
                    parts.append(block.get("thinking", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = json.dumps(block.get("input", {}), ensure_ascii=False)
                    parts.append(f"[tool_use:{name}] {inp}")
                elif block.get("type") == "tool_result":
                    text = block.get("text", "") or block.get("content", "")
                    if isinstance(text, list):
                        text = " ".join(
                            b.get("text", "") for b in text if isinstance(b, dict)
                        )
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def extract_tool_names(message_data: dict) -> str:
    """Extract tool names from assistant messages."""
    content = message_data.get("content", [])
    if not isinstance(content, list):
        return ""
    names = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            names.append(block.get("name", ""))
    return ",".join(names) if names else ""


def extract_file_paths(text: str) -> str:
    """Extract file paths mentioned in text."""
    paths = set()
    for word in text.split():
        w = word.strip("\"'`,;:()")
        if "/" in w and (
            w.startswith("/") or w.startswith("~/") or w.startswith("./")
        ):
            paths.add(w)
    return ",".join(sorted(paths)[:20]) if paths else ""


def index_session(conn: sqlite3.Connection, jsonl_path: Path) -> int:
    """Index a single session JSONL file. Returns number of messages indexed."""
    session_id = jsonl_path.stem
    project = jsonl_path.parent.name
    file_mtime = jsonl_path.stat().st_mtime

    # Check if already indexed and up to date
    row = conn.execute(
        "SELECT file_mtime FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row and row["file_mtime"] >= file_mtime:
        return 0

    # Delete old data for this session (re-index)
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    slug = ""
    version = ""
    cwd = ""
    first_ts = None
    last_ts = None
    count = 0

    # Pre-scan for metadata and insert session row first (FK requirement)
    with open(jsonl_path, "r", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not slug and entry.get("slug"):
                slug = entry["slug"]
            if not version and entry.get("version"):
                version = entry["version"]
            if not cwd and entry.get("cwd"):
                cwd = entry["cwd"]
            ts = entry.get("timestamp", "")
            if not first_ts and ts:
                first_ts = ts
            if ts:
                last_ts = ts

    conn.execute(
        "INSERT INTO sessions (session_id, project, slug, version, cwd, first_ts, last_ts, file_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, project, slug, version, cwd, first_ts, last_ts, file_mtime),
    )

    with open(jsonl_path, "r", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type", "")
            ts = entry.get("timestamp", "")

            if entry_type == "user":
                msg = entry.get("message", {})
                text = extract_text_content(msg)
                if not text.strip():
                    continue
                uuid = entry.get("uuid", "")
                conn.execute(
                    "INSERT OR IGNORE INTO messages (session_id, uuid, role, content, timestamp, file_paths) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, uuid, "user", text, ts, extract_file_paths(text)),
                )
                count += 1

            elif entry_type == "assistant":
                msg = entry.get("message", {})
                text = extract_text_content(msg)
                if not text.strip():
                    continue
                uuid = entry.get("uuid", "")
                tools = extract_tool_names(msg)
                conn.execute(
                    "INSERT OR IGNORE INTO messages (session_id, uuid, role, content, timestamp, tool_name, file_paths) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, uuid, "assistant", text, ts, tools, extract_file_paths(text)),
                )
                count += 1

            elif entry_type == "system":
                msg = entry.get("message", {})
                text = extract_text_content(msg)
                if not text.strip():
                    continue
                uuid = entry.get("uuid", "")
                conn.execute(
                    "INSERT OR IGNORE INTO messages (session_id, uuid, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (session_id, uuid, "system", text, ts),
                )
                count += 1

    if count == 0:
        # Remove empty session row
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))

    return count


def cmd_index(args):
    """Index all session JSONL files."""
    conn = get_db()
    jsonl_files = sorted(SESSIONS_DIR.rglob("*.jsonl"))
    total_files = len(jsonl_files)
    total_msgs = 0
    indexed = 0

    for i, f in enumerate(jsonl_files, 1):
        count = index_session(conn, f)
        if count > 0:
            indexed += 1
            total_msgs += count
            if not args.quiet:
                print(f"  [{i}/{total_files}] {f.stem[:8]}... +{count} messages")
        if i % 50 == 0:
            conn.commit()

    conn.commit()
    conn.close()
    print(f"Indexed {indexed} sessions ({total_msgs} messages) from {total_files} files")


def cmd_search(args):
    """Search indexed sessions."""
    conn = get_db()
    query = " ".join(args.query)

    filters = ""
    params = [query]
    if args.role:
        filters += " AND m.role = ?"
        params.append(args.role)
    if args.since:
        filters += " AND m.timestamp >= ?"
        params.append(args.since)

    limit = args.limit or 20
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT m.id, m.session_id, m.role, m.content, m.timestamp, m.tool_name,
               s.slug, s.cwd,
               highlight(messages_fts, 0, '>>>', '<<<') AS highlighted
        FROM messages_fts f
        JOIN messages m ON m.id = f.rowid
        LEFT JOIN sessions s ON s.session_id = m.session_id
        WHERE messages_fts MATCH ?
        {filters}
        ORDER BY rank
        LIMIT ?
        """,
        params,
    ).fetchall()

    if not rows:
        print("No results found.")
        return

    for row in rows:
        ts = row["timestamp"] or "?"
        date = ts[:10] if len(ts) >= 10 else ts
        role = row["role"]
        session = row["session_id"][:8]
        slug = row["slug"] or ""
        tools = f" [{row['tool_name']}]" if row["tool_name"] else ""

        # Truncate content for display
        content = row["highlighted"] or row["content"]
        content = content.replace("\n", " ")
        max_len = args.width or 200
        if len(content) > max_len:
            content = content[:max_len] + "..."

        print(f"\033[36m{date}\033[0m \033[33m{session}\033[0m/{slug} \033[1m{role}\033[0m{tools}")
        print(f"  {content}")
        print()

    print(f"({len(rows)} results)")


def cmd_context(args):
    """Show full conversation context around a search result."""
    conn = get_db()
    query = " ".join(args.query)

    # Find the best matching message
    row = conn.execute(
        """
        SELECT m.session_id, m.timestamp
        FROM messages_fts f
        JOIN messages m ON m.id = f.rowid
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT 1
        """,
        (query,),
    ).fetchone()

    if not row:
        print("No results found.")
        return

    session_id = row["session_id"]
    window = args.window or 5

    # Get surrounding messages
    rows = conn.execute(
        """
        SELECT role, content, timestamp, tool_name
        FROM messages
        WHERE session_id = ?
        ORDER BY timestamp, id
        """,
        (session_id,),
    ).fetchall()

    # Find the target index
    target_ts = row["timestamp"]
    target_idx = 0
    for i, r in enumerate(rows):
        if r["timestamp"] == target_ts:
            target_idx = i
            break

    start = max(0, target_idx - window)
    end = min(len(rows), target_idx + window + 1)

    sess = conn.execute(
        "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    print(f"\033[1mSession:\033[0m {session_id} ({sess['slug'] or '?'})")
    print(f"\033[1mCwd:\033[0m {sess['cwd'] or '?'}")
    print(f"\033[1mTime:\033[0m {sess['first_ts'][:16] if sess['first_ts'] else '?'} → {sess['last_ts'][:16] if sess['last_ts'] else '?'}")
    print("─" * 80)

    for i in range(start, end):
        r = rows[i]
        marker = ">>>" if i == target_idx else "   "
        role = r["role"]
        ts = (r["timestamp"] or "")[:19]
        tools = f" [{r['tool_name']}]" if r["tool_name"] else ""

        content = r["content"].replace("\n", "\n     ")
        max_len = 500
        if len(content) > max_len:
            content = content[:max_len] + "..."

        print(f"{marker} \033[36m{ts}\033[0m \033[1m{role}\033[0m{tools}")
        print(f"     {content}")
        print()


def cmd_stats(args):
    """Show index statistics."""
    conn = get_db()
    sessions = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
    messages = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
    by_role = conn.execute(
        "SELECT role, COUNT(*) as c FROM messages GROUP BY role ORDER BY c DESC"
    ).fetchall()
    latest = conn.execute(
        "SELECT session_id, slug, last_ts FROM sessions ORDER BY last_ts DESC LIMIT 5"
    ).fetchall()

    db_size = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0

    print(f"Database: {DB_PATH} ({db_size:.1f} MB)")
    print(f"Sessions: {sessions}")
    print(f"Messages: {messages}")
    print()
    print("By role:")
    for r in by_role:
        print(f"  {r['role']:12s} {r['c']:6d}")
    print()
    print("Recent sessions:")
    for r in latest:
        date = r["last_ts"][:16] if r["last_ts"] else "?"
        print(f"  {date}  {r['session_id'][:8]}  {r['slug'] or ''}")


def cmd_sessions(args):
    """List indexed sessions."""
    conn = get_db()
    limit = args.limit or 20
    since_filter = ""
    params = []
    if args.since:
        since_filter = "WHERE s.last_ts >= ?"
        params.append(args.since)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT s.session_id, s.slug, s.cwd, s.first_ts, s.last_ts,
               COUNT(m.id) as msg_count
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.session_id
        {since_filter}
        GROUP BY s.session_id
        ORDER BY s.last_ts DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    for r in rows:
        date = r["first_ts"][:16] if r["first_ts"] else "?"
        slug = r["slug"] or ""
        print(f"\033[36m{date}\033[0m  {r['session_id'][:8]}  \033[33m{slug:30s}\033[0m  {r['msg_count']:4d} msgs")


def main():
    parser = argparse.ArgumentParser(
        prog="session-index",
        description="FTS5 search over Claude Code session transcripts",
    )
    sub = parser.add_subparsers(dest="command")

    # index
    p_idx = sub.add_parser("index", help="Index session JSONL files")
    p_idx.add_argument("-q", "--quiet", action="store_true")

    # search
    p_search = sub.add_parser("search", aliases=["s"], help="Search messages")
    p_search.add_argument("query", nargs="+", help="FTS5 search query")
    p_search.add_argument("-r", "--role", choices=["user", "assistant", "system"])
    p_search.add_argument("-l", "--limit", type=int, default=20)
    p_search.add_argument("-w", "--width", type=int, default=200)
    p_search.add_argument("--since", type=parse_since, metavar="AGE",
                          help="Only show results newer than AGE (e.g. 2d, 3h, 1w, 30m)")

    # context
    p_ctx = sub.add_parser("context", aliases=["ctx"], help="Show conversation context around a match")
    p_ctx.add_argument("query", nargs="+", help="FTS5 search query")
    p_ctx.add_argument("-n", "--window", type=int, default=5, help="Messages before/after")

    # stats
    sub.add_parser("stats", help="Show index statistics")

    # sessions
    p_sess = sub.add_parser("sessions", aliases=["ls"], help="List sessions")
    p_sess.add_argument("-l", "--limit", type=int, default=20)
    p_sess.add_argument("--since", type=parse_since, metavar="AGE",
                        help="Only show sessions newer than AGE (e.g. 2d, 3h, 1w, 30m)")

    args = parser.parse_args()

    if args.command in ("index",):
        cmd_index(args)
    elif args.command in ("search", "s"):
        cmd_search(args)
    elif args.command in ("context", "ctx"):
        cmd_context(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command in ("sessions", "ls"):
        cmd_sessions(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
