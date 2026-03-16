# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Watchdog-based file watcher with debounce for vault indexing."""

import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Timer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .chunker import parse_note
from .embedder import HAS_NUMPY, build_chunk_context, embedding_to_blob, get_embeddings_batch
from .graph import build_graph, compute_pagerank
from .schema import DB_PATH, get_db
from .summarizer import summarize_note
from .triples import extract_triples, triple_to_text

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
from .config import get_config

log = logging.getLogger("neurostack.indexer")

_cfg = get_config()
VAULT_ROOT = _cfg.vault_root
DEBOUNCE_SECONDS = 2.0


class DebouncedHandler(FileSystemEventHandler):
    """Debounces file changes and triggers indexing."""

    def __init__(
        self,
        vault_root: Path,
        embed_url: str,
        summarize_url: str,
        exclude_dirs: list[str] | None = None,
    ):
        self.vault_root = vault_root
        self.embed_url = embed_url
        self.summarize_url = summarize_url
        self._timers: dict[str, Timer] = {}
        self._exclude_dirs = set(
            exclude_dirs or [],
        )

    def _should_process(self, path: str) -> bool:
        p = Path(path)
        if not p.suffix == ".md":
            return False
        skip = {".git", ".obsidian", ".trash"}
        skip.update(self._exclude_dirs)
        if skip.intersection(p.parts):
            return False
        return True

    def on_any_event(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if not self._should_process(path):
            return

        # Debounce
        if path in self._timers:
            self._timers[path].cancel()

        self._timers[path] = Timer(
            DEBOUNCE_SECONDS,
            self._process_file,
            args=[path, event.event_type],
        )
        self._timers[path].start()

    def _process_file(self, path_str: str, event_type: str):
        path = Path(path_str)
        del self._timers[path_str]

        conn = get_db(DB_PATH)

        if event_type == "deleted" or not path.exists():
            rel_path = str(path.relative_to(self.vault_root))
            log.info(f"Removing: {rel_path}")
            conn.execute("DELETE FROM notes WHERE path = ?", (rel_path,))
            conn.commit()
            return

        try:
            index_single_note(path, self.vault_root, conn, self.embed_url, self.summarize_url)
            log.info(f"Indexed: {path.relative_to(self.vault_root)}")
        except Exception as e:
            log.error(f"Error indexing {path}: {e}")


def index_single_note(
    path: Path,
    vault_root: Path,
    conn,
    embed_url: str = None,
    summarize_url: str = None,
    skip_summary: bool = False,
    skip_triples: bool = False,
):
    """Index a single note: parse, embed, summarize, extract triples."""
    embed_url = embed_url or _cfg.embed_url
    summarize_url = summarize_url or _cfg.llm_url
    parsed = parse_note(path, vault_root)

    # Check if content changed
    existing = conn.execute(
        "SELECT content_hash FROM notes WHERE path = ?", (parsed.path,)
    ).fetchone()

    if existing and existing["content_hash"] == parsed.content_hash:
        return  # No change

    now = datetime.now(timezone.utc).isoformat()

    frontmatter_json = json.dumps(parsed.frontmatter, default=str)

    # Update note
    conn.execute(
        """INSERT OR REPLACE INTO notes (path, title, frontmatter, content_hash, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (parsed.path, parsed.title, frontmatter_json, parsed.content_hash, now),
    )

    # Generate summary first so it can be used as embedding context
    summary = None
    if not skip_summary:
        full_content = "\n\n".join(c.content for c in parsed.chunks)
        try:
            summary = summarize_note(parsed.title, full_content, base_url=summarize_url)
            conn.execute(
                "INSERT OR REPLACE INTO summaries"
                " (note_path, summary_text,"
                " content_hash, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (parsed.path, summary,
                 parsed.content_hash, now),
            )
        except Exception as e:
            log.warning(f"Summary failed for {parsed.path}: {e}")
    else:
        # Use existing summary for embedding context even when skipping regeneration
        existing_sum = conn.execute(
            "SELECT summary_text FROM summaries WHERE note_path = ?", (parsed.path,)
        ).fetchone()
        if existing_sum:
            summary = existing_sum["summary_text"]

    # Delete old chunks
    conn.execute("DELETE FROM chunks WHERE note_path = ?", (parsed.path,))

    # Insert new chunks with contextual embeddings
    if parsed.chunks:
        texts = [
            build_chunk_context(parsed.title, frontmatter_json, summary, c.content)
            for c in parsed.chunks
        ]
        if HAS_NUMPY:
            try:
                embeddings = get_embeddings_batch(texts, base_url=embed_url)
            except Exception as e:
                log.warning(f"Embedding failed for {parsed.path}: {e}")
                embeddings = [None] * len(texts)
        else:
            embeddings = [None] * len(texts)

        for i, chunk in enumerate(parsed.chunks):
            emb_blob = embedding_to_blob(embeddings[i]) if embeddings[i] is not None else None
            conn.execute(
                "INSERT INTO chunks"
                " (note_path, heading_path, content,"
                " content_hash, position, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    parsed.path,
                    chunk.heading_path,
                    chunk.content,
                    hashlib.sha256(chunk.content.encode()).hexdigest()[:16],
                    chunk.position,
                    emb_blob,
                ),
            )

    # Extract triples
    if not skip_triples:
        full_content = "\n\n".join(c.content for c in parsed.chunks)
        try:
            _index_triples_for_note(
                parsed.path, parsed.title, full_content,
                parsed.content_hash, now, conn, embed_url, summarize_url,
            )
        except Exception as e:
            log.warning(f"Triple extraction failed for {parsed.path}: {e}")

    conn.commit()


def _index_triples_for_note(
    note_path: str,
    title: str,
    content: str,
    content_hash: str,
    now: str,
    conn,
    embed_url: str,
    summarize_url: str,
):
    """Extract and store triples for a single note."""
    # Delete old triples for this note
    conn.execute("DELETE FROM triples WHERE note_path = ?", (note_path,))

    triples = extract_triples(title, content, base_url=summarize_url)
    if not triples:
        return

    # Build triple texts for batch embedding
    triple_texts = [triple_to_text(t) for t in triples]

    if HAS_NUMPY:
        try:
            embeddings = get_embeddings_batch(triple_texts, base_url=embed_url)
        except Exception as e:
            log.warning(f"Triple embedding failed for {note_path}: {e}")
            embeddings = [None] * len(triples)
    else:
        embeddings = [None] * len(triples)

    for i, t in enumerate(triples):
        emb_blob = embedding_to_blob(embeddings[i]) if embeddings[i] is not None else None
        conn.execute(
            "INSERT INTO triples"
            " (note_path, subject, predicate, object,"
            " triple_text, embedding,"
            " content_hash, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                note_path, t["s"], t["p"], t["o"],
                triple_texts[i], emb_blob, content_hash, now,
            ),
        )

    log.info(f"  Extracted {len(triples)} triples from {note_path}")


def full_index(
    vault_root: Path = VAULT_ROOT,
    embed_url: str = None,
    summarize_url: str = None,
    skip_summary: bool = False,
    skip_triples: bool = False,
    exclude_dirs: list[str] | None = None,
):
    """Full re-index of the entire vault."""
    embed_url = embed_url or _cfg.embed_url
    summarize_url = summarize_url or _cfg.llm_url

    # Pre-flight: check Ollama before starting a long indexing run
    if not skip_summary or not skip_triples:
        from .preflight import check_ollama, preflight_report
        result = check_ollama(
            embed_url=embed_url,
            embed_model=_cfg.embed_model,
            llm_url=summarize_url,
            llm_model=_cfg.llm_model,
        )
        report = preflight_report(result)
        if report:
            print(report)
            if not result.embed_ok:
                print(
                    "  Continuing with FTS5-only indexing "
                    "(no embeddings)."
                )
            if not result.llm_ok:
                skip_summary = True
                skip_triples = True

    conn = get_db(DB_PATH)
    md_files = sorted(vault_root.rglob("*.md"))
    # Filter out .git, .obsidian, .trash, and any extra exclude dirs
    skip_parts = {".git", ".obsidian", ".trash"}
    skip_parts.update(exclude_dirs or [])
    md_files = [
        f for f in md_files
        if not skip_parts.intersection(f.parts)
    ]

    total = len(md_files)
    log.info(f"Indexing {total} notes...")

    for i, path in enumerate(md_files):
        try:
            index_single_note(
                path, vault_root, conn, embed_url, summarize_url,
                skip_summary, skip_triples,
            )
            if (i + 1) % 50 == 0 or i + 1 == total:
                log.info(f"  Progress: {i + 1}/{total}")
        except Exception as e:
            log.error(f"Error indexing {path}: {e}")

    # Build graph
    log.info("Building wiki-link graph...")
    build_graph(conn, vault_root)
    compute_pagerank(conn)
    log.info("Index complete.")


def backfill_summaries(
    vault_root: Path = VAULT_ROOT,
    summarize_url: str = None,
):
    """Generate summaries for all notes that don't have one yet."""
    summarize_url = summarize_url or _cfg.llm_url
    conn = get_db(DB_PATH)
    # Find notes without summaries
    rows = conn.execute(
        """SELECT n.path, n.title FROM notes n
           LEFT JOIN summaries s ON n.path = s.note_path
           WHERE s.note_path IS NULL"""
    ).fetchall()

    total = len(rows)
    if total == 0:
        log.info("All notes already have summaries.")
        return

    log.info(f"Backfilling summaries for {total} notes...")
    success = 0
    for i, row in enumerate(rows):
        note_path = row["path"]
        title = row["title"]
        # Read chunks content for this note
        chunks = conn.execute(
            "SELECT content FROM chunks WHERE note_path = ? ORDER BY position",
            (note_path,),
        ).fetchall()
        if not chunks:
            continue

        full_content = "\n\n".join(c["content"] for c in chunks)
        try:
            summary = summarize_note(title, full_content, base_url=summarize_url)
            if summary:
                now = datetime.now(timezone.utc).isoformat()
                # Get content hash from notes table
                content_hash = conn.execute(
                    "SELECT content_hash FROM notes WHERE path = ?", (note_path,)
                ).fetchone()["content_hash"]
                conn.execute(
                    "INSERT OR REPLACE INTO summaries"
                    " (note_path, summary_text,"
                    " content_hash, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (note_path, summary, content_hash, now),
                )
                success += 1
        except Exception as e:
            log.warning(f"Summary failed for {note_path}: {e}")

        if (i + 1) % 10 == 0 or i + 1 == total:
            conn.commit()
            log.info(f"  Progress: {i + 1}/{total} ({success} successful)")

    conn.commit()
    log.info(f"Backfill complete: {success}/{total} summaries generated.")


def backfill_stale_summaries(
    vault_root: Path = VAULT_ROOT,
    summarize_url: str = None,
):
    """Regenerate summaries where content has changed since last summary."""
    summarize_url = summarize_url or _cfg.llm_url
    conn = get_db(DB_PATH)
    rows = conn.execute(
        """SELECT n.path, n.title, n.content_hash FROM notes n
           JOIN summaries s ON n.path = s.note_path
           WHERE s.content_hash != n.content_hash"""
    ).fetchall()

    total = len(rows)
    if total == 0:
        log.info("No stale summaries to refresh.")
        return

    log.info(f"Refreshing {total} stale summaries...")
    success = 0
    for i, row in enumerate(rows):
        note_path = row["path"]
        title = row["title"]
        content_hash = row["content_hash"]
        chunks = conn.execute(
            "SELECT content FROM chunks WHERE note_path = ? ORDER BY position",
            (note_path,),
        ).fetchall()
        if not chunks:
            continue

        full_content = "\n\n".join(c["content"] for c in chunks)
        try:
            summary = summarize_note(title, full_content, base_url=summarize_url)
            if summary:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO summaries"
                    " (note_path, summary_text,"
                    " content_hash, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (note_path, summary, content_hash, now),
                )
                success += 1
        except Exception as e:
            log.warning(
                f"Summary refresh failed for {note_path}: {e}"
            )

        if (i + 1) % 10 == 0 or i + 1 == total:
            conn.commit()
            log.info(f"  Progress: {i + 1}/{total} ({success} successful)")

    conn.commit()
    log.info(f"Stale refresh complete: {success}/{total} summaries regenerated.")


def backfill_triples(
    vault_root: Path = VAULT_ROOT,
    embed_url: str = None,
    summarize_url: str = None,
):
    """Generate triples for all notes that don't have any yet."""
    embed_url = embed_url or _cfg.embed_url
    summarize_url = summarize_url or _cfg.llm_url
    conn = get_db(DB_PATH)
    # Find notes without triples
    rows = conn.execute(
        """SELECT n.path, n.title, n.content_hash FROM notes n
           LEFT JOIN (SELECT DISTINCT note_path FROM triples) t ON n.path = t.note_path
           WHERE t.note_path IS NULL"""
    ).fetchall()

    total = len(rows)
    if total == 0:
        log.info("All notes already have triples.")
        return

    log.info(f"Backfilling triples for {total} notes...")
    success = 0
    total_triples = 0
    for i, row in enumerate(rows):
        note_path = row["path"]
        title = row["title"]
        content_hash = row["content_hash"]
        chunks = conn.execute(
            "SELECT content FROM chunks WHERE note_path = ? ORDER BY position",
            (note_path,),
        ).fetchall()
        if not chunks:
            continue

        full_content = "\n\n".join(c["content"] for c in chunks)
        try:
            now = datetime.now(timezone.utc).isoformat()
            _index_triples_for_note(
                note_path, title, full_content,
                content_hash, now, conn, embed_url, summarize_url,
            )
            count = conn.execute(
                "SELECT COUNT(*) as c FROM triples WHERE note_path = ?", (note_path,)
            ).fetchone()["c"]
            if count > 0:
                success += 1
                total_triples += count
        except Exception as e:
            log.warning(f"Triple extraction failed for {note_path}: {e}")

        if (i + 1) % 10 == 0 or i + 1 == total:
            conn.commit()
            log.info(f"  Progress: {i + 1}/{total} ({success} notes, {total_triples} triples)")

    conn.commit()
    log.info(f"Backfill complete: {total_triples} triples from {success}/{total} notes.")


def reembed_all_chunks(
    embed_url: str = None,
    batch_size: int = 50,
):
    embed_url = embed_url or _cfg.embed_url
    """Re-embed all chunks using contextual embeddings (title + tags + summary + chunk).

    Uses existing summaries and note metadata from the DB — no LLM calls needed.
    Only the embedding BLOBs are updated; chunk content is unchanged.
    """
    import sqlite3 as _sqlite3
    # Use autocommit mode so individual batch commits don't conflict with
    # other long-running write transactions (e.g. backfill triples).
    raw = _sqlite3.connect(str(DB_PATH), timeout=60.0, isolation_level=None)
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA busy_timeout=60000")
    raw.row_factory = _sqlite3.Row
    conn = raw

    rows = conn.execute(
        """SELECT c.chunk_id, c.content, c.note_path, c.position,
                  n.title, n.frontmatter,
                  s.summary_text
           FROM chunks c
           JOIN notes n ON c.note_path = n.path
           LEFT JOIN summaries s ON c.note_path = s.note_path
           ORDER BY c.note_path, c.position"""
    ).fetchall()

    total = len(rows)
    if total == 0:
        print("No chunks found.")
        return

    print(f"Re-embedding {total} chunks with contextual text...")

    updated = 0
    errors = 0
    for batch_start in range(0, total, batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        texts = [
            build_chunk_context(r["title"], r["frontmatter"], r["summary_text"], r["content"])
            for r in batch
        ]
        try:
            embeddings = get_embeddings_batch(texts, base_url=embed_url, batch_size=batch_size)
        except Exception as e:
            log.warning(f"Batch embedding failed at offset {batch_start}: {e}")
            errors += len(batch)
            continue

        conn.execute("BEGIN")
        for row, vec in zip(batch, embeddings):
            conn.execute(
                "UPDATE chunks SET embedding = ? WHERE chunk_id = ?",
                (embedding_to_blob(vec), row["chunk_id"]),
            )
            updated += 1
        conn.execute("COMMIT")

        done = min(batch_start + batch_size, total)
        print(f"  {done}/{total} chunks re-embedded ({updated} updated, {errors} errors)")

    print(f"Done. {updated}/{total} chunks re-embedded with context.")


def run_watcher(
    vault_root: Path = VAULT_ROOT,
    embed_url: str = None,
    summarize_url: str = None,
    exclude_dirs: list[str] | None = None,
):
    """Run the watchdog file watcher."""
    embed_url = embed_url or _cfg.embed_url
    summarize_url = summarize_url or _cfg.llm_url
    log.info(f"Watching {vault_root} for changes...")

    handler = DebouncedHandler(
        vault_root, embed_url, summarize_url,
        exclude_dirs=exclude_dirs,
    )
    observer = Observer()
    observer.schedule(handler, str(vault_root), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    run_watcher()
