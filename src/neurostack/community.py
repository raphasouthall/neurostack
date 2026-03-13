# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Generate LLM summaries and embeddings for Leiden communities.

For each unsummarized community:
1. Collect member note_paths (stored in community_members.entity)
2. Gather note titles + summaries for those notes
3. Sample top entities from those notes' triples
4. Generate a title + summary via Ollama (configured LLM)
5. Embed the summary via configured embedding model
6. Store back to the communities table
"""

import json
import logging
import random
from datetime import datetime, timezone

import httpx

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .embedder import get_embedding
from .schema import DB_PATH, get_db

log = logging.getLogger("neurostack")

from .config import get_config

_cfg = get_config()
SUMMARIZE_URL = _cfg.llm_url
EMBED_URL = _cfg.embed_url
SUMMARIZE_MODEL = _cfg.llm_model

COMMUNITY_PROMPT = (
    "You are summarizing a cluster of thematically"
    " related notes from a personal knowledge vault.\n"
    "\nMember notes and their summaries:\n"
    "{note_summaries}\n"
    "\nTop entities/concepts mentioned across these notes:\n"
    "{entities}\n"
    "\nSample facts from these notes:\n"
    "{triples}\n"
    "\nTasks:\n"
    '1. Give this community a short, descriptive title'
    ' (3-7 words, e.g. "Distributed Systems & Consensus")\n'
    "2. Write a 3-5 sentence summary of the shared themes,"
    " relationships, and knowledge in this cluster\n"
    "3. Note any particularly central concepts or"
    " recurring ideas\n"
    "\nReturn ONLY valid JSON:\n"
    '{{"title": "...", "summary": "..."}}'
)


def _collect_community_context(conn, community_id: int) -> dict:
    """Gather note summaries and top entities for a note-based community.

    community_members.entity stores note_paths for this community type.
    """
    note_paths = [
        r["entity"]
        for r in conn.execute(
            "SELECT entity FROM community_members WHERE community_id = ?",
            (community_id,),
        ).fetchall()
    ]

    if not note_paths:
        return {"entities": [], "triples": [], "note_summaries": []}

    # Collect note titles + summaries
    note_summaries = []
    for np_ in note_paths[:12]:
        row = conn.execute(
            """SELECT n.title, s.summary_text
               FROM notes n LEFT JOIN summaries s ON s.note_path = n.path
               WHERE n.path = ?""",
            (np_,),
        ).fetchone()
        if row:
            title = row["title"] or np_
            summary = row["summary_text"] or ""
            note_summaries.append(f"{title}: {summary}" if summary else title)

    # Collect top entities from these notes' triples
    placeholders = ",".join("?" * len(note_paths))
    triple_rows = conn.execute(
        f"""SELECT subject, predicate, object FROM triples
            WHERE note_path IN ({placeholders})
            LIMIT 80""",
        note_paths,
    ).fetchall()

    sample = random.sample(list(triple_rows), min(30, len(triple_rows)))
    triples_text = [f"{r['subject']} {r['predicate']} {r['object']}" for r in sample]

    # Top entities by frequency
    from collections import Counter
    entity_freq: Counter = Counter()
    for r in triple_rows:
        entity_freq[r["subject"]] += 1
        entity_freq[r["object"]] += 1
    top_entities = [e for e, _ in entity_freq.most_common(30)]

    return {
        "entities": top_entities,
        "triples": triples_text,
        "note_summaries": note_summaries,
    }


def _generate_community_summary(
    community_id: int,
    context: dict,
    base_url: str = SUMMARIZE_URL,
    model: str = SUMMARIZE_MODEL,
) -> tuple[str, str]:
    """Call Ollama to generate title + summary. Returns (title, summary)."""
    entities_str = ", ".join(context["entities"][:30])
    if not entities_str:
        return "Unknown Community", ""

    triples_str = "\n".join(f"- {t}" for t in context["triples"][:25])
    notes_str = "\n".join(f"- {s[:200]}" for s in context["note_summaries"][:5])

    prompt = COMMUNITY_PROMPT.format(
        entities=entities_str,
        triples=triples_str or "(none)",
        note_summaries=notes_str or "(none)",
    )

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["title", "summary"],
    }

    resp = httpx.post(
        f"{base_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.3, "num_predict": 512},
            "think": False,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()

    try:
        parsed = json.loads(raw)
        return parsed.get("title", "Unnamed Community"), parsed.get("summary", "")
    except json.JSONDecodeError:
        log.warning(f"JSON parse error for community {community_id}")
        return "Unnamed Community", raw[:500]


def summarize_all_communities(
    conn=None,
    db_path=None,
    summarize_url: str = SUMMARIZE_URL,
    embed_url: str = EMBED_URL,
    level: int | None = None,
):
    """Generate summaries + embeddings for all unsummarized communities."""
    if not HAS_NUMPY:
        raise ImportError(
            "Community summarization requires numpy. "
            "Install with: pip install neurostack[full]"
        )
    if conn is None:
        conn = get_db(db_path or DB_PATH)

    query = "SELECT community_id, level, entity_count FROM communities WHERE summary IS NULL"
    params: list = []
    if level is not None:
        query += " AND level = ?"
        params.append(level)
    query += " ORDER BY level, community_id"

    communities = conn.execute(query, params).fetchall()
    if not communities:
        log.info("All communities already have summaries.")
        return

    log.info(f"Summarizing {len(communities)} communities...")
    now = datetime.now(timezone.utc).isoformat()

    for i, row in enumerate(communities):
        cid = row["community_id"]
        log.info(
            f"  [{i + 1}/{len(communities)}] community {cid} "
            f"(level={row['level']}, {row['entity_count']} notes)"
        )

        ctx = _collect_community_context(conn, cid)
        if not ctx["note_summaries"]:
            continue

        title, summary = _generate_community_summary(cid, ctx, base_url=summarize_url)

        embedding_blob = None
        if summary:
            try:
                vec = get_embedding(title + ": " + summary, base_url=embed_url)
                embedding_blob = np.array(vec, dtype=np.float32).tobytes()
            except Exception as e:
                log.warning(f"Embedding failed for community {cid}: {e}")

        conn.execute(
            """UPDATE communities
               SET title = ?, summary = ?, summary_embedding = ?, updated_at = ?
               WHERE community_id = ?""",
            (title, summary, embedding_blob, now, cid),
        )
        conn.commit()

    log.info("Community summarization complete.")
