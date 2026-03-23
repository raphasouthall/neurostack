# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Server-side vault query for NeuroStack Cloud.

Downloads a user's indexed DB from GCS, caches it on the Cloud Run
instance, and runs search queries against it.

The DB already contains pre-computed embeddings, summaries, triples,
and FTS5 indexes from cloud indexing. Uses direct SQL queries against
the cached DB — avoids ``get_db()`` which triggers WAL mode and
schema migrations inappropriate for a read-only query path.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path

import httpx

log = logging.getLogger("neurostack.cloud.query")

_CACHE_DIR = Path(tempfile.gettempdir()) / "neurostack-db-cache"


def _safe_fts_query(query: str) -> str:
    """Escape FTS5 special chars and OR-join tokens for recall."""
    tokens = [
        '"' + w.replace('"', "") + '"'
        for w in query.split()
        if w and not w.startswith("-")
    ]
    return " OR ".join(tokens) if tokens else ""


class CloudQueryEngine:
    """Runs search queries against a user's cloud-indexed DB.

    Downloads the DB from GCS on first query, caches locally for
    subsequent queries during this instance's lifetime.
    """

    def __init__(self, storage) -> None:
        self._storage = storage
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_db_path(self, user_id: str) -> Path:
        user_dir = _CACHE_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "neurostack.db"

    def _ensure_db(self, user_id: str) -> Path:
        """Download user's DB from GCS if not cached locally."""
        db_path = self._get_db_path(user_id)
        if db_path.exists():
            return db_path

        log.info("Downloading DB for user %s from GCS", user_id)
        try:
            url = self._storage.generate_download_url(user_id)
        except Exception as exc:
            raise FileNotFoundError(
                "No indexed database found for user. Push your vault first."
            ) from exc

        timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
        tmp_path = db_path.with_suffix(".tmp")
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=131072):
                            f.write(chunk)
            tmp_path.rename(db_path)
        except httpx.HTTPStatusError:
            tmp_path.unlink(missing_ok=True)
            raise FileNotFoundError(
                "No indexed database found for user. Push your vault first."
            )
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        log.info(
            "Cached DB for user %s (%d bytes)", user_id, db_path.stat().st_size
        )
        return db_path

    def _connect(self, db_path: Path) -> sqlite3.Connection:
        """Open a read-only SQLite connection (no WAL, no migrations)."""
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def invalidate_cache(self, user_id: str) -> None:
        """Remove a user's cached DB (e.g. after a new push)."""
        user_dir = _CACHE_DIR / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)
            log.info("Invalidated DB cache for user %s", user_id)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 10,
        mode: str = "hybrid",
        depth: str = "auto",
        workspace: str | None = None,
    ) -> dict:
        """Run a tiered search against the user's cloud-indexed DB.

        Depth levels mirror NeuroStack's tiered_search:
        - "triples": SPO facts only (~15 tokens each)
        - "summaries": Note summaries (~75 tokens each)
        - "full": Full chunk snippets + summaries
        - "auto": Start with triples, escalate if coverage is low
        """
        db_path = self._ensure_db(user_id)
        conn = self._connect(db_path)
        try:
            return self._tiered_search(
                conn, query, top_k=top_k, depth=depth, workspace=workspace
            )
        finally:
            conn.close()

    def _tiered_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        *,
        top_k: int = 10,
        depth: str = "auto",
        workspace: str | None = None,
    ) -> dict:
        result = {
            "triples": [], "summaries": [], "chunks": [],
            "depth_used": depth,
        }

        if depth == "triples":
            result["triples"] = self._search_triples(
                conn, query, top_k=top_k * 2, workspace=workspace
            )
            return result

        if depth == "summaries":
            chunks = self._fts_search_chunks(
                conn, query, limit=top_k, workspace=workspace
            )
            seen = set()
            for c in chunks:
                np_ = c["note_path"]
                if np_ not in seen:
                    seen.add(np_)
                    summary = self._get_note_summary(conn, np_)
                    if summary:
                        result["summaries"].append(summary)
            return result

        if depth == "full":
            result["chunks"] = self._fts_search_chunks(
                conn, query, limit=top_k, workspace=workspace
            )
            return result

        # Auto: start with triples, escalate if needed
        triples = self._search_triples(
            conn, query, top_k=top_k * 3, workspace=workspace
        )
        result["triples"] = triples

        triple_notes = {t["note"] for t in triples}
        top_score = max((t["score"] for t in triples), default=0.0)

        if len(triple_notes) >= 2 and top_score > 0.4:
            # Good triple coverage — add summaries for top notes
            for np_ in list(triple_notes)[:top_k]:
                summary = self._get_note_summary(conn, np_)
                if summary:
                    result["summaries"].append(summary)
            result["depth_used"] = "auto:triples+summaries"
            return result

        # Low coverage — fall back to full chunks
        result["chunks"] = self._fts_search_chunks(
            conn, query, limit=top_k, workspace=workspace
        )
        result["depth_used"] = "auto:full"
        return result

    # ------------------------------------------------------------------
    # FTS5 chunk search
    # ------------------------------------------------------------------

    def _fts_search_chunks(
        self,
        conn: sqlite3.Connection,
        query: str,
        *,
        limit: int = 10,
        workspace: str | None = None,
    ) -> list[dict]:
        safe_q = _safe_fts_query(query)
        if not safe_q:
            return []

        if workspace:
            workspace = workspace.strip("/")
            rows = conn.execute(
                """SELECT c.chunk_id, c.note_path, c.heading_path, c.content,
                          rank
                   FROM chunks_fts
                   JOIN chunks c ON c.chunk_id = chunks_fts.rowid
                   WHERE chunks_fts MATCH ?
                     AND c.note_path LIKE ? || '%'
                   ORDER BY rank LIMIT ?""",
                (safe_q, workspace + "/", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.chunk_id, c.note_path, c.heading_path, c.content,
                          rank
                   FROM chunks_fts
                   JOIN chunks c ON c.chunk_id = chunks_fts.rowid
                   WHERE chunks_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (safe_q, limit),
            ).fetchall()

        results = []
        for r in rows:
            np_ = r["note_path"]
            summary = self._get_note_summary(conn, np_)
            title = self._get_note_title(conn, np_)
            results.append({
                "note": np_,
                "title": title,
                "section": r["heading_path"] or "",
                "snippet": (r["content"] or "")[:500],
                "summary": summary["summary"] if summary else "",
                "score": round(abs(r["rank"]), 4),
            })
        return results

    # ------------------------------------------------------------------
    # Triple search
    # ------------------------------------------------------------------

    def _search_triples(
        self,
        conn: sqlite3.Connection,
        query: str,
        *,
        top_k: int = 20,
        workspace: str | None = None,
    ) -> list[dict]:
        safe_q = _safe_fts_query(query)
        if not safe_q:
            return []

        if workspace:
            workspace = workspace.strip("/")
            rows = conn.execute(
                """SELECT t.triple_id, t.note_path, t.subject,
                          t.predicate, t.object, rank
                   FROM triples_fts
                   JOIN triples t ON t.triple_id = triples_fts.rowid
                   WHERE triples_fts MATCH ?
                     AND t.note_path LIKE ? || '%'
                   ORDER BY rank LIMIT ?""",
                (safe_q, workspace + "/", top_k),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.triple_id, t.note_path, t.subject,
                          t.predicate, t.object, rank
                   FROM triples_fts
                   JOIN triples t ON t.triple_id = triples_fts.rowid
                   WHERE triples_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (safe_q, top_k),
            ).fetchall()

        title_cache: dict[str, str] = {}
        results = []
        for r in rows:
            np_ = r["note_path"]
            if np_ not in title_cache:
                title_cache[np_] = self._get_note_title(conn, np_)
            results.append({
                "note": np_,
                "title": title_cache[np_],
                "subject": r["subject"],
                "predicate": r["predicate"],
                "object": r["object"],
                "score": round(abs(r["rank"]), 4),
            })
        return results

    def search_triples(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 10,
        workspace: str | None = None,
    ) -> list[dict]:
        """Public API: search triples in the user's cloud DB."""
        db_path = self._ensure_db(user_id)
        conn = self._connect(db_path)
        try:
            return self._search_triples(
                conn, query, top_k=top_k, workspace=workspace
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _get_note_summary(
        self, conn: sqlite3.Connection, note_path: str
    ) -> dict | None:
        row = conn.execute(
            """SELECT s.summary_text, n.title, n.path
               FROM summaries s
               JOIN notes n ON n.path = s.note_path
               WHERE s.note_path = ?""",
            (note_path,),
        ).fetchone()
        if row:
            return {
                "note": row["path"],
                "title": row["title"],
                "summary": row["summary_text"],
            }
        return None

    def _get_note_title(
        self, conn: sqlite3.Connection, note_path: str
    ) -> str:
        row = conn.execute(
            "SELECT title FROM notes WHERE path = ?", (note_path,)
        ).fetchone()
        return row["title"] if row else note_path

    # ------------------------------------------------------------------
    # Stats / health
    # ------------------------------------------------------------------

    def get_db_stats(self, user_id: str) -> dict:
        """Return note/chunk/embedding counts and last sync time."""
        db_path = self._ensure_db(user_id)
        conn = self._connect(db_path)
        try:
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            try:
                embedding_count = conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
                ).fetchone()[0]
            except Exception:
                embedding_count = chunk_count
            import datetime

            mtime = db_path.stat().st_mtime
            last_sync = datetime.datetime.fromtimestamp(
                mtime, tz=datetime.timezone.utc
            ).isoformat()
            return {
                "note_count": note_count,
                "chunk_count": chunk_count,
                "embedding_count": embedding_count,
                "last_sync": last_sync,
            }
        finally:
            conn.close()

    def get_health_stats(self, user_id: str) -> dict:
        """Return embedding/summary coverage and triple count."""
        db_path = self._ensure_db(user_id)
        conn = self._connect(db_path)
        try:
            note_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            try:
                summary_count = conn.execute(
                    "SELECT COUNT(*) FROM summaries"
                ).fetchone()[0]
            except Exception:
                summary_count = 0
            summary_pct = round(
                (summary_count / note_count * 100) if note_count > 0 else 0.0, 1
            )
            try:
                emb_count = conn.execute(
                    "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
                ).fetchone()[0]
            except Exception:
                emb_count = 0
            emb_pct = round(
                (emb_count / chunk_count * 100) if chunk_count > 0 else 0.0, 1
            )
            try:
                triple_count = conn.execute(
                    "SELECT COUNT(*) FROM triples"
                ).fetchone()[0]
            except Exception:
                triple_count = 0
            return {
                "embedding_coverage_pct": emb_pct,
                "summary_coverage_pct": summary_pct,
                "triple_count": triple_count,
            }
        finally:
            conn.close()

    def get_summary(
        self,
        user_id: str,
        note_path: str,
    ) -> dict | None:
        """Get the pre-computed summary for a specific note."""
        db_path = self._ensure_db(user_id)
        conn = self._connect(db_path)
        try:
            return self._get_note_summary(conn, note_path)
        finally:
            conn.close()
