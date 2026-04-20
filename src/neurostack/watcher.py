# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Watchdog-based file watcher with debounce for vault indexing.

Supports optional cloud sync via ``--cloud`` flag or ``cloud.auto_push``
config toggle.  When enabled, vault changes are pushed to NeuroStack Cloud
after an idle period (no file changes for ``CLOUD_IDLE_SECONDS``).  The push
runs in a background thread so it never blocks local indexing.
"""

import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread, Timer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .chunker import parse_note
from .cooccurrence import persist_cooccurrence, upsert_cooccurrence_for_note
from .embedder import HAS_NUMPY, build_chunk_context, embedding_to_blob, get_embeddings_batch
from .graph import build_graph, compute_pagerank
from .schema import DB_PATH, get_db
from .summarizer import summarize_note
from .triples import extract_triples, triple_to_text
from .vecindex import (
    delete_chunk_vecs,
    delete_triple_vecs,
    has_vec_index,
    upsert_chunk_vec,
    upsert_triple_vec,
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
from .config import get_config

log = logging.getLogger("neurostack.indexer")

DEBOUNCE_SECONDS = 2.0
CLOUD_IDLE_SECONDS = 60.0  # Push to cloud after 60s of no file changes
CLOUD_RETRY_DELAYS = (5, 15, 45)  # Exponential backoff for push failures


def _vault_root():
    """Resolve vault root lazily to support test config overrides."""
    return get_config().vault_root


class CloudPusher:
    """Background cloud push with idle detection and retry.

    Tracks file changes and triggers a cloud push after the vault has been
    idle for ``CLOUD_IDLE_SECONDS``.  The push runs in a daemon thread so
    it never blocks local indexing.  Retries with exponential backoff on
    transient failures; the 15-min systemd timer acts as ultimate fallback.
    """

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root
        self._idle_timer: Timer | None = None
        self._lock = Lock()
        self._push_in_progress = False

    def notify_change(self) -> None:
        """Called by DebouncedHandler on every file event.  Resets idle timer."""
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
            self._idle_timer = Timer(CLOUD_IDLE_SECONDS, self._trigger_push)
            self._idle_timer.daemon = True
            self._idle_timer.start()

    def _trigger_push(self) -> None:
        """Fire a cloud push in a background thread."""
        with self._lock:
            if self._push_in_progress:
                log.debug("Cloud push already in progress, skipping")
                return
            self._push_in_progress = True

        thread = Thread(target=self._do_push, daemon=True)
        thread.start()

    def _do_push(self) -> None:
        """Execute cloud push with retry.  Runs in a daemon thread."""
        try:
            from .cloud.config import load_cloud_config
            from .cloud.sync import ConsentError, SyncError, VaultSyncEngine
            from .config import get_config

            cfg = get_config()
            cloud_cfg = load_cloud_config()
            if not cloud_cfg.cloud_api_url or not cloud_cfg.cloud_api_key:
                log.debug("Cloud not configured, skipping push")
                return

            engine = VaultSyncEngine(
                cloud_api_url=cloud_cfg.cloud_api_url,
                cloud_api_key=cloud_cfg.cloud_api_key,
                vault_root=self._vault_root,
                db_dir=Path(cfg.db_path).parent if hasattr(cfg, "db_path") else self._vault_root,
            )

            for attempt, delay in enumerate(CLOUD_RETRY_DELAYS):
                try:
                    result = engine.push(
                        progress_callback=lambda msg: log.info("Cloud: %s", msg),
                    )
                    status = result.get("status", "unknown")
                    if status == "no_changes":
                        log.debug("Cloud push: no changes")
                    else:
                        uploaded = result.get("upload_stats", {}).get("files_uploaded", 0)
                        log.info("Cloud push complete: %d files synced", uploaded)
                    return
                except ConsentError:
                    log.debug("Cloud consent not given, skipping push")
                    return
                except (SyncError, Exception) as exc:
                    log.warning(
                        "Cloud push attempt %d/%d failed: %s",
                        attempt + 1, len(CLOUD_RETRY_DELAYS), exc,
                    )
                    if attempt < len(CLOUD_RETRY_DELAYS) - 1:
                        time.sleep(delay)

            log.error(
                "Cloud push failed after %d attempts (timer will retry)",
                len(CLOUD_RETRY_DELAYS),
            )

        except Exception as exc:
            log.error("Cloud push error: %s", exc)
        finally:
            with self._lock:
                self._push_in_progress = False


class DebouncedHandler(FileSystemEventHandler):
    """Debounces file changes and triggers indexing."""

    def __init__(
        self,
        vault_root: Path,
        embed_url: str,
        summarize_url: str,
        exclude_dirs: list[str] | None = None,
        cloud_pusher: CloudPusher | None = None,
    ):
        self.vault_root = vault_root
        self.embed_url = embed_url
        self.summarize_url = summarize_url
        self._timers: dict[str, Timer] = {}
        self._timers_lock = Lock()
        self._exclude_dirs = set(
            exclude_dirs or [],
        )
        self._cloud_pusher = cloud_pusher
        # Reuse a single DB connection across events (WAL mode is safe for
        # concurrent reads).  The connection is created lazily on first use.
        self._conn = None

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

        # Notify cloud pusher (resets idle timer)
        if self._cloud_pusher is not None:
            self._cloud_pusher.notify_change()

        # Debounce local indexing
        with self._timers_lock:
            if path in self._timers:
                self._timers[path].cancel()

            self._timers[path] = Timer(
                DEBOUNCE_SECONDS,
                self._process_file,
                args=[path, event.event_type],
            )
            self._timers[path].start()

    def _get_conn(self):
        """Return a reused DB connection, creating it on first call."""
        if self._conn is None:
            self._conn = get_db()
        return self._conn

    def _process_file(self, path_str: str, event_type: str):
        path = Path(path_str)
        with self._timers_lock:
            self._timers.pop(path_str, None)

        conn = self._get_conn()

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
    embed_url = embed_url or get_config().embed_url
    summarize_url = summarize_url or get_config().llm_url
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

    # Upsert note_metadata: frontmatter-owned fields sync on every
    # re-index; status and date_added are preserved (status is managed
    # by the excitability decay system, date_added is immutable).
    fm = parsed.frontmatter or {}
    conn.execute(
        "INSERT INTO note_metadata"
        " (note_path, status, tags, note_type, date_added)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(note_path) DO UPDATE SET"
        "  tags = excluded.tags,"
        "  note_type = excluded.note_type",
        (
            parsed.path,
            fm.get("status", "active"),
            json.dumps(fm.get("tags", [])),
            fm.get("type", "permanent"),
            fm.get("date", now[:10]),
        ),
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

    # Delete old chunks (and their vec index entries)
    _has_vec = has_vec_index(conn)
    if _has_vec:
        delete_chunk_vecs(conn, parsed.path)
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
            # Populate sqlite-vec index
            if _has_vec and emb_blob:
                chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                upsert_chunk_vec(conn, chunk_id, emb_blob)

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
    # Delete old triples (and their vec index entries)
    _has_vec = has_vec_index(conn)
    if _has_vec:
        delete_triple_vecs(conn, note_path)
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
        # Populate sqlite-vec index
        if _has_vec and emb_blob:
            triple_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            upsert_triple_vec(conn, triple_id, emb_blob)

    log.info(f"  Extracted {len(triples)} triples from {note_path}")

    # Update co-occurrence for entities in this note
    upsert_cooccurrence_for_note(conn, note_path)


def _prepare_note(
    path: Path,
    vault_root: Path,
    embed_url: str,
    summarize_url: str,
    skip_summary: bool,
    skip_triples: bool,
    existing_hashes: dict[str, str],
) -> dict | None:
    """Prepare a note for indexing (network/CPU-bound, no DB writes).

    Thread-safe: does parsing, summarization, embedding, and triple extraction
    without touching the database. Returns a dict of results to be written by
    the main thread, or None if the note hasn't changed.
    """
    parsed = parse_note(path, vault_root)

    # Skip unchanged notes
    if parsed.path in existing_hashes and existing_hashes[parsed.path] == parsed.content_hash:
        return None

    now = datetime.now(timezone.utc).isoformat()
    frontmatter_json = json.dumps(parsed.frontmatter, default=str)
    full_content = "\n\n".join(c.content for c in parsed.chunks)

    # Generate summary (LLM call)
    summary = None
    if not skip_summary and full_content:
        try:
            summary = summarize_note(parsed.title, full_content, base_url=summarize_url)
        except Exception as e:
            log.warning(f"Summary failed for {parsed.path}: {e}")

    # Generate chunk embeddings
    chunk_embeddings = [None] * len(parsed.chunks)
    if parsed.chunks and HAS_NUMPY:
        texts = [
            build_chunk_context(parsed.title, frontmatter_json, summary, c.content)
            for c in parsed.chunks
        ]
        try:
            chunk_embeddings = get_embeddings_batch(texts, base_url=embed_url)
        except Exception as e:
            log.warning(f"Embedding failed for {parsed.path}: {e}")
            chunk_embeddings = [None] * len(texts)

    # Extract triples (LLM call)
    triples = []
    triple_embeddings = []
    if not skip_triples and full_content:
        try:
            triples = extract_triples(parsed.title, full_content, base_url=summarize_url)
            if triples and HAS_NUMPY:
                triple_texts = [triple_to_text(t) for t in triples]
                try:
                    triple_embeddings = get_embeddings_batch(triple_texts, base_url=embed_url)
                except Exception as e:
                    log.warning(f"Triple embedding failed for {parsed.path}: {e}")
                    triple_embeddings = [None] * len(triples)
            else:
                triple_embeddings = [None] * len(triples)
        except Exception as e:
            log.warning(f"Triple extraction failed for {parsed.path}: {e}")

    return {
        "parsed": parsed,
        "now": now,
        "frontmatter_json": frontmatter_json,
        "summary": summary,
        "chunk_embeddings": chunk_embeddings,
        "triples": triples,
        "triple_embeddings": triple_embeddings,
    }


def _write_note_results(conn, result: dict, _has_vec: bool) -> None:
    """Write prepared note results to the database (main thread only)."""
    parsed = result["parsed"]
    now = result["now"]
    frontmatter_json = result["frontmatter_json"]
    summary = result["summary"]
    chunk_embeddings = result["chunk_embeddings"]
    triples = result["triples"]
    triple_embeddings = result["triple_embeddings"]

    # Update note
    conn.execute(
        """INSERT OR REPLACE INTO notes (path, title, frontmatter, content_hash, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (parsed.path, parsed.title, frontmatter_json, parsed.content_hash, now),
    )

    # Upsert note_metadata
    fm = parsed.frontmatter or {}
    conn.execute(
        "INSERT INTO note_metadata"
        " (note_path, status, tags, note_type, date_added)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(note_path) DO UPDATE SET"
        "  tags = excluded.tags,"
        "  note_type = excluded.note_type",
        (
            parsed.path,
            fm.get("status", "active"),
            json.dumps(fm.get("tags", [])),
            fm.get("type", "permanent"),
            fm.get("date", now[:10]),
        ),
    )

    # Write summary
    if summary:
        conn.execute(
            "INSERT OR REPLACE INTO summaries"
            " (note_path, summary_text, content_hash, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (parsed.path, summary, parsed.content_hash, now),
        )

    # Delete old chunks
    if _has_vec:
        delete_chunk_vecs(conn, parsed.path)
    conn.execute("DELETE FROM chunks WHERE note_path = ?", (parsed.path,))

    # Insert new chunks
    for i, chunk in enumerate(parsed.chunks):
        emb = chunk_embeddings[i] if i < len(chunk_embeddings) else None
        emb_blob = embedding_to_blob(emb) if emb is not None else None
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
        if _has_vec and emb_blob:
            chunk_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            upsert_chunk_vec(conn, chunk_id, emb_blob)

    # Delete old triples and insert new ones
    if triples:
        if _has_vec:
            delete_triple_vecs(conn, parsed.path)
        conn.execute("DELETE FROM triples WHERE note_path = ?", (parsed.path,))

        triple_texts = [triple_to_text(t) for t in triples]
        for i, t in enumerate(triples):
            emb = triple_embeddings[i] if i < len(triple_embeddings) else None
            emb_blob = embedding_to_blob(emb) if emb is not None else None
            conn.execute(
                "INSERT INTO triples"
                " (note_path, subject, predicate, object,"
                " triple_text, embedding,"
                " content_hash, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    parsed.path, t["s"], t["p"], t["o"],
                    triple_texts[i], emb_blob, parsed.content_hash, now,
                ),
            )
            if _has_vec and emb_blob:
                triple_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                upsert_triple_vec(conn, triple_id, emb_blob)

        upsert_cooccurrence_for_note(conn, parsed.path)

    conn.commit()


def full_index(
    vault_root: Path | None = None,
    embed_url: str = None,
    summarize_url: str = None,
    skip_summary: bool = False,
    skip_triples: bool = False,
    exclude_dirs: list[str] | None = None,
    workers: int = 2,
):
    """Full re-index of the entire vault.

    Uses ThreadPoolExecutor to parallelize LLM-bound work (summaries, triples,
    embeddings) across multiple notes. SQLite writes remain single-threaded.
    Set workers=1 for sequential processing (original behavior).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    vault_root = vault_root or _vault_root()
    embed_url = embed_url or get_config().embed_url
    summarize_url = summarize_url or get_config().llm_url

    # Pre-flight: check Ollama before starting a long indexing run
    if not skip_summary or not skip_triples:
        from .preflight import check_ollama, preflight_report
        result = check_ollama(
            embed_url=embed_url,
            embed_model=get_config().embed_model,
            llm_url=summarize_url,
            llm_model=get_config().llm_model,
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
    log.info(f"Indexing {total} notes ({workers} workers)...")

    # Pre-fetch content hashes for skip-unchanged check
    existing_hashes = {}
    for row in conn.execute("SELECT path, content_hash FROM notes").fetchall():
        existing_hashes[row["path"]] = row["content_hash"]

    _has_vec = has_vec_index(conn)
    done = 0

    if workers <= 1:
        # Sequential fallback
        for path in md_files:
            try:
                result = _prepare_note(
                    path, vault_root, embed_url, summarize_url,
                    skip_summary, skip_triples, existing_hashes,
                )
                if result:
                    _write_note_results(conn, result, _has_vec)
            except Exception as e:
                log.error(f"Error indexing {path}: {e}")
            done += 1
            if done % 50 == 0 or done == total:
                log.info(f"  Progress: {done}/{total}")
    else:
        # Parallel: prepare in threads, write sequentially
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_path = {
                executor.submit(
                    _prepare_note,
                    path, vault_root, embed_url, summarize_url,
                    skip_summary, skip_triples, existing_hashes,
                ): path
                for path in md_files
            }
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    result = future.result()
                    if result:
                        _write_note_results(conn, result, _has_vec)
                except Exception as e:
                    log.error(f"Error indexing {path}: {e}")
                done += 1
                if done % 50 == 0 or done == total:
                    log.info(f"  Progress: {done}/{total}")

    # Build graph
    log.info("Building wiki-link graph...")
    build_graph(conn, vault_root)
    compute_pagerank(conn)

    # Populate co-occurrence weights from all triples
    log.info("Populating co-occurrence weights...")
    n_pairs = persist_cooccurrence(conn)
    log.info(f"Co-occurrence: {n_pairs} entity pairs.")

    # Rebuild sqlite-vec index from all embeddings
    if has_vec_index(conn):
        from .vecindex import populate_vec_chunks, populate_vec_triples
        log.info("Rebuilding vector search index...")
        n_chunks = populate_vec_chunks(conn)
        n_triples = populate_vec_triples(conn)
        log.info(f"Vector index: {n_chunks} chunks, {n_triples} triples.")

    log.info("Index complete.")


def backfill_summaries(
    vault_root: Path | None = None,
    summarize_url: str = None,
):
    """Generate summaries for all notes that don't have one yet."""
    vault_root = vault_root or _vault_root()
    summarize_url = summarize_url or get_config().llm_url
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
    vault_root: Path | None = None,
    summarize_url: str = None,
):
    """Regenerate summaries where content has changed since last summary."""
    vault_root = vault_root or _vault_root()
    summarize_url = summarize_url or get_config().llm_url
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
    vault_root: Path | None = None,
    embed_url: str = None,
    summarize_url: str = None,
):
    """Generate triples for all notes that don't have any yet."""
    vault_root = vault_root or _vault_root()
    embed_url = embed_url or get_config().embed_url
    summarize_url = summarize_url or get_config().llm_url
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
    embed_url = embed_url or get_config().embed_url
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

    # Rebuild sqlite-vec index after full re-embed
    main_conn = get_db(DB_PATH)
    if has_vec_index(main_conn):
        from .vecindex import populate_vec_chunks
        print("Rebuilding vector search index...")
        n = populate_vec_chunks(main_conn)
        print(f"Vector index: {n} chunks indexed.")
    main_conn.close()

    print(f"Done. {updated}/{total} chunks re-embedded with context.")


def run_watcher(
    vault_root: Path | None = None,
    embed_url: str = None,
    summarize_url: str = None,
    exclude_dirs: list[str] | None = None,
    cloud: bool = False,
):
    """Run the watchdog file watcher.

    Args:
        cloud: Enable automatic cloud push after idle period.  Can also
            be enabled via ``cloud.auto_push = true`` in config.toml.
    """
    vault_root = vault_root or _vault_root()
    embed_url = embed_url or get_config().embed_url
    summarize_url = summarize_url or get_config().llm_url

    # Check config toggle if flag not passed
    if not cloud:
        try:
            from .cloud.config import load_cloud_config
            cfg = load_cloud_config()
            cloud = bool(getattr(cfg, "auto_push", False))
        except Exception:
            pass

    cloud_pusher = None
    if cloud:
        cloud_pusher = CloudPusher(vault_root)
        log.info(
            "Watching %s for changes (cloud sync enabled, %ds idle push)...",
            vault_root, int(CLOUD_IDLE_SECONDS),
        )
    else:
        log.info(f"Watching {vault_root} for changes...")

    handler = DebouncedHandler(
        vault_root, embed_url, summarize_url,
        exclude_dirs=exclude_dirs,
        cloud_pusher=cloud_pusher,
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
