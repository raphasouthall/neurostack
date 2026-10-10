# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Integration tests for the MCP server layer (issue #5).

Exercises the registered MCP tools end-to-end against a fixture vault:
registry registration, the MCPServer adapter, and the tool functions
themselves (vault_search, vault_stats, vault_prediction_errors), asserting
response structure and JSON serialisability.

The tools are regular Python functions behind the protocol-agnostic
registry, so we call them through ``registry.call`` (the same entry point
every adapter uses) rather than over a stdio transport. Search runs in
keyword mode so no embedder is needed.
"""

import asyncio
import json

import pytest

from neurostack import config as nsconfig


@pytest.fixture
def mcp_vault(tmp_path, tmp_vault, monkeypatch):
    """Point config at the fixture vault + a fresh on-disk DB, and index it."""
    db_dir = tmp_path / "db"
    monkeypatch.setenv("NEUROSTACK_VAULT_ROOT", str(tmp_vault))
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(db_dir))
    # Unroutable embedder: keyword-mode tests must fail loudly, not fall back
    # to a live Ollama leaked in from the developer's config.toml
    monkeypatch.setenv("NEUROSTACK_EMBED_URL", "http://127.0.0.1:1")
    nsconfig._config = None

    from neurostack.chunker import parse_note
    from neurostack.schema import get_db

    conn = get_db(db_dir / "neurostack.db")
    now = "2026-01-15T00:00:00+00:00"
    for md_file in sorted(tmp_vault.rglob("*.md")):
        parsed = parse_note(md_file, tmp_vault)
        conn.execute(
            "INSERT OR REPLACE INTO notes "
            "(path, title, frontmatter, content_hash, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (parsed.path, parsed.title, json.dumps(parsed.frontmatter, default=str),
             parsed.content_hash, now),
        )
        for chunk in parsed.chunks:
            conn.execute(
                "INSERT INTO chunks "
                "(note_path, heading_path, content, content_hash, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, chunk.heading_path, chunk.content, "test",
                 chunk.position),
            )
    conn.commit()
    conn.close()
    yield tmp_vault
    nsconfig._config = None


def _registry():
    from neurostack.tools import ensure_registered
    return ensure_registered()


def test_registry_registers_expected_tools(mcp_vault):
    names = {t.name for t in _registry().list_tools()}
    assert {"vault_search", "vault_stats", "vault_prediction_errors"} <= names


def test_mcp_server_exposes_registry_tools(mcp_vault):
    from neurostack.server import mcp
    from neurostack.tools.mcp_adapter import create_mcp_server

    assert mcp is not None  # module-level server import builds cleanly
    server = create_mcp_server()
    tool_names = {t.name for t in asyncio.run(server.list_tools())}
    registry_names = {t.name for t in _registry().list_tools()}
    assert tool_names  # empty == empty must not pass
    assert tool_names == registry_names


def test_tool_reply_reaches_the_client_once(mcp_vault):
    # Issue #310: a `-> dict` tool also came back as structuredContent, so the
    # client showed the same reply twice.
    from mcp import Client

    from neurostack.tools.mcp_adapter import create_mcp_server

    async def call():
        async with Client(create_mcp_server()) as client:
            return await client.call_tool("vault_stats", {})

    reply = asyncio.run(call())
    assert reply.structured_content is None
    assert len(reply.content) == 1
    assert json.loads(reply.content[0].text)["notes"] == 4


def test_read_replies_are_markdown_except_for_the_hook_client(mcp_vault):
    # Issue #318: a model reads vault_search and vault_memories, so they go out
    # as Markdown; the hook client parses them as JSON and keeps getting JSON.
    from mcp import Client
    from mcp.types import Implementation

    from neurostack.client import CLIENT_NAME
    from neurostack.tools.mcp_adapter import create_mcp_server

    _registry().call("vault_remember", content="Predictive coding uses priors.",
                     tags=["coding", "session:7"], entity_type="decision")
    calls = [
        ("vault_search", {"query": "prediction", "mode": "keyword", "depth": "full"}),
        ("vault_memories", {}),
    ]

    async def replies(client_name):
        info = Implementation(name=client_name, version="1")
        async with Client(create_mcp_server(), client_info=info) as client:
            return [(await client.call_tool(n, a)).content[0].text for n, a in calls]

    search_md, memories_md = asyncio.run(replies("claude-code"))
    search_json, memories_json = asyncio.run(replies(CLIENT_NAME))

    assert "### " in search_md and "predictive-coding" in search_md
    assert len(search_md) < len(search_json)
    assert json.loads(search_json)["results"]
    assert memories_md.startswith("#")
    assert "tags: coding" in memories_md and "session:7" not in memories_md
    assert len(memories_md) < len(memories_json)
    assert json.loads(memories_json)["memories"][0]["tags"] == ["coding", "session:7"]



def test_vault_search_keyword(mcp_vault):
    result = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth="full",
    )
    assert isinstance(result, dict)
    assert "results" in result
    json.dumps(result)  # response must be serialisable over the wire
    paths = [r["path"] for r in result["results"]]
    assert any("predictive-coding" in p for p in paths)
    for r in result["results"]:
        assert {"path", "title", "score"} <= set(r), r


def test_an_invented_depth_is_rejected(mcp_vault):
    # Agents guessed "shallow", "quick", "standard" in real transcripts, and a
    # silent fallback looked like a working search with the wrong footprint.
    with pytest.raises(Exception) as err:
        _registry().call("vault_search", query="prediction", depth="shallow")
    message = str(err.value)
    assert "depth must be one of" in message
    assert "triples" in message and "auto" in message


@pytest.mark.parametrize("depth", ["triples", "summaries", "full", "auto"])
def test_every_documented_depth_is_accepted(mcp_vault, depth):
    result = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth=depth,
    )
    # Tiered depths answer with the tier they served; only "full" returns a
    # flat result list. An agent has to read both shapes.
    key = "results" if depth == "full" else "depth_used"
    assert key in result, result
    json.dumps(result)


def test_vault_search_reference_only(mcp_vault):
    # Issue #62: reference mode returns lean {path, score, snippet} + a fetch hint.
    result = _registry().call(
        "vault_search", query="prediction", mode="keyword", reference_only=True,
    )
    assert result["reference_only"] is True
    assert "vault_read_file" in result["hint"]
    assert result["results"], "reference search should surface at least one path"
    for r in result["results"]:
        assert set(r) == {"path", "score", "snippet"}, r
    json.dumps(result)


def test_vault_search_max_tokens_truncates(mcp_vault):
    # A generous budget keeps every hit; a 1-token budget keeps exactly one.
    full = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth="full",
    )
    assert len(full["results"]) >= 2, "need >1 hit to prove truncation"

    capped = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth="full",
        max_tokens=1,
    )
    assert len(capped["results"]) == 1  # at least one always kept
    assert capped["truncated"] is True
    json.dumps(capped)


def test_vault_search_max_tokens_applies_to_tiered_depth(mcp_vault):
    # The budget must not silently no-op just because depth defaults to "auto".
    capped = _registry().call(
        "vault_search", query="prediction", mode="keyword", depth="auto",
        max_tokens=1,
    )
    # auto falls back to chunk search in the fixture (no triples/summaries), so
    # the content list is capped to one entry and truncation is flagged.
    assert capped.get("truncated") is True
    total = sum(len(capped.get(k, [])) for k in ("triples", "summaries", "chunks"))
    assert total == 1
    json.dumps(capped)


def _oversized_tiered(monkeypatch):
    """Stub a tiered result shaped like a live reply, 2,100-2,700 tokens uncapped."""
    from neurostack.tools import search_tools

    triples = [
        {"note": f"n{i}.md", "title": "T", "s": "s" * 40, "p": "p", "o": "o" * 40,
         "score": 0.6}
        for i in range(15)
    ]
    summaries = [
        {"note": f"n{i}.md", "title": "T", "summary": "x" * 700, "score": 0.9}
        for i in range(5)
    ]
    memories = [{"memory_id": i, "content": "m" * 1500} for i in range(3)]

    def tiered(*_a, depth, **_k):
        return {"triples": list(triples) if depth == "auto" else [],
                "summaries": list(summaries), "chunks": [], "depth_used": depth}

    monkeypatch.setattr("neurostack.search.tiered_search", tiered)
    monkeypatch.setattr(
        search_tools, "_search_memories_for_results", lambda *a, **k: list(memories)
    )
    return summaries, memories


@pytest.mark.parametrize("depth", ["auto", "summaries"])
def test_vault_search_tiered_default_budget(mcp_vault, monkeypatch, depth):
    # Issue #310: auto and summaries replies ran past 10 kB with no max_tokens.
    from neurostack.budget import estimate_tokens
    from neurostack.tools.search_tools import DEFAULT_TIERED_MAX_TOKENS

    summaries, memories = _oversized_tiered(monkeypatch)
    result = _registry().call("vault_search", query="q", depth=depth)

    assert estimate_tokens(result) <= DEFAULT_TIERED_MAX_TOKENS
    assert result["truncated"] is True
    # Memories go first, so the ranked notes survive whole.
    assert result["summaries"] == summaries
    assert len(result["memories"]) < len(memories)


def test_vault_search_explicit_max_tokens_beats_default(mcp_vault, monkeypatch):
    summaries, memories = _oversized_tiered(monkeypatch)
    result = _registry().call(
        "vault_search", query="q", depth="auto", max_tokens=100_000,
    )
    assert "truncated" not in result
    assert result["summaries"] == summaries
    assert result["memories"] == memories


_PROJECT_NOTE = """---
date: 2026-09-11
tags: [work]
type: project
---
# AVD migration
Replace Citrix with AVD.
## Licensing
Licensing is still open.
## Current status
Licensing bought on 2026-10-01.
### Prod pool
HOST01 is live.
## Open
Nothing left here.
"""


def _stub_hits(monkeypatch, notes, memories=()):
    """Every search path answers with chunks from `notes`, best first."""
    from types import SimpleNamespace

    from neurostack.tools import search_tools

    hits = [
        SimpleNamespace(note_path=n, title="T", heading_path="S", score=0.5,
                        snippet="Licensing is still open.", summary="")
        for n in notes
    ]
    chunks = [{"note": h.note_path, "title": "T", "section": "S",
               "snippet": h.snippet, "score": 0.5} for h in hits]
    monkeypatch.setattr(
        "neurostack.search.tiered_search",
        lambda *a, depth, **k: {"triples": [], "summaries": [], "chunks": list(chunks),
                                "depth_used": depth},
    )
    monkeypatch.setattr("neurostack.search.hybrid_search", lambda *a, **k: list(hits))
    monkeypatch.setattr(
        search_tools, "_search_memories_for_results", lambda *a, **k: list(memories)
    )


@pytest.mark.parametrize("kwargs", [
    {"depth": "auto"}, {"depth": "full"}, {"reference_only": True},
])
def test_sibling_hit_brings_the_project_status(mcp_vault, monkeypatch, kwargs):
    # Issue #322: the agent answered from a sibling runbook and never saw the
    # project note say licensing was done.
    folder = mcp_vault / "work" / "projects" / "avd"
    folder.mkdir(parents=True)
    (folder / "avd.md").write_text(_PROJECT_NOTE)
    (folder / "runbook.md").write_text("# Runbook\nLicensing is still open.\n")
    _stub_hits(monkeypatch, ["work/projects/avd/runbook.md"])

    [project] = _registry().call("vault_search", query="q", **kwargs)["projects"]

    assert project["path"] == "work/projects/avd/avd.md"
    assert project["title"] == "AVD migration"
    assert "2026-10-01" in project["status"] and "HOST01" in project["status"]
    assert "still open" not in project["status"]
    assert "Nothing left" not in project["status"]
    assert project["updated"][:4].isdigit()


def test_without_a_status_heading_the_newest_dated_and_open_sections_stand_in(
    mcp_vault, monkeypatch,
):
    # Most live project notes have no status heading; their news sits in dated
    # build sections and an Open list (#322).
    folder = mcp_vault / "projects" / "avd"
    folder.mkdir(parents=True)
    (folder / "avd.md").write_text(
        "# AVD\nIntro text.\n"
        "## Non-prod build (2026-09-10)\nOld build.\n"
        "## Prod pilot build (2026-09-30)\nPilot live.\n"
        "```bash\n# not a heading\nrun-it\n```\nAfter the fence.\n"
        "## Open\nRetire NetScaler.\n"
        "## Related\nLinks.\n"
    )
    _stub_hits(monkeypatch, ["projects/avd/avd.md"])

    [project] = _registry().call("vault_search", query="q")["projects"]

    status = project["status"]
    assert "Pilot live." in status and "After the fence." in status
    assert "Retire NetScaler." in status
    assert "Old build." not in status and "Intro text." not in status
    assert "Links." not in status


def test_no_projects_block_without_a_project_folder_hit(mcp_vault, monkeypatch):
    # A note directly under projects/ belongs to no project folder.
    (mcp_vault / "home" / "projects").mkdir(parents=True)
    (mcp_vault / "home" / "projects" / "loose.md").write_text("# Loose\n")
    _stub_hits(monkeypatch, ["research/predictive-coding.md", "home/projects/loose.md"])

    assert "projects" not in _registry().call("vault_search", query="q")


def test_at_most_two_projects_best_hit_first(mcp_vault, monkeypatch):
    for slug in ("a", "b", "c"):
        folder = mcp_vault / "projects" / slug
        folder.mkdir(parents=True)
        # No status heading, so the status is the note's opening text.
        (folder / "index.md").write_text(f"# {slug}\nProject {slug} opening.\n")
        (folder / "x.md").write_text("# x\n")
    _stub_hits(monkeypatch, ["projects/b/x.md", "projects/b/index.md",
                             "projects/a/x.md", "projects/c/x.md"])

    projects = _registry().call("vault_search", query="q")["projects"]

    assert [p["path"] for p in projects] == ["projects/b/index.md", "projects/a/index.md"]
    assert "Project b opening." in projects[0]["status"]


def _projects(vault, *slugs_and_titles):
    for slug, title in slugs_and_titles:
        folder = vault / "work" / "acme" / "projects" / slug
        folder.mkdir(parents=True)
        (folder / f"{slug}.md").write_text(f"# {title}\nAbout {slug}.\n")
        (folder / "x.md").write_text("# x\n")


def test_project_the_query_names_beats_an_earlier_unrelated_hit(mcp_vault, monkeypatch):
    # Issue #324: hit order put projects sharing one common word, or none, ahead
    # of the project the query named.
    _projects(mcp_vault, ("billing", "Billing"), ("cloud-tagging", "Cloud tagging"),
              ("cloud-backup", "Cloud backup"), ("remote-desktop", "Remote desktop rollout"))
    _stub_hits(monkeypatch, [f"work/acme/projects/{s}/x.md"
                             for s in ("billing", "cloud-tagging", "remote-desktop")])

    projects = _registry().call(
        "vault_search", query="remote desktop cloud session hosts",
    )["projects"]

    assert [p["title"] for p in projects] == ["Remote desktop rollout", "Cloud tagging"]


def test_project_the_query_names_joins_without_a_hit(mcp_vault, monkeypatch):
    _projects(mcp_vault, ("billing", "Billing"), ("remote-desktop", "Remote desktop rollout"))
    _stub_hits(monkeypatch, ["work/acme/projects/billing/x.md"])

    projects = _registry().call("vault_search", query="remote desktop hosts")["projects"]

    assert [p["title"] for p in projects] == ["Remote desktop rollout", "Billing"]


def test_project_status_outlives_memories_under_the_default_budget(mcp_vault, monkeypatch):
    from neurostack.budget import estimate_tokens
    from neurostack.tools.search_tools import DEFAULT_TIERED_MAX_TOKENS

    folder = mcp_vault / "work" / "projects" / "avd"
    folder.mkdir(parents=True)
    (folder / "avd.md").write_text(_PROJECT_NOTE)
    memories = [{"memory_id": i, "content": "m" * 1500} for i in range(6)]
    _stub_hits(monkeypatch, ["work/projects/avd/avd.md"], memories)

    result = _registry().call("vault_search", query="q")

    assert result["truncated"] is True
    assert len(result["memories"]) < len(memories)
    assert result["projects"][0]["path"] == "work/projects/avd/avd.md"
    assert estimate_tokens(result) <= DEFAULT_TIERED_MAX_TOKENS



def test_vault_diff_and_checkpoint(mcp_vault):
    # Issue #11: no baseline → all added; checkpoint → next diff is clean.
    reg = _registry()
    d0 = reg.call("vault_diff")
    assert d0["mode"] == "baseline"
    assert d0["has_baseline"] is False
    assert d0["added_count"] == 4  # fixture vault: 3 notes + index.md

    ck = reg.call("vault_checkpoint")
    assert ck["notes"] == 4

    d1 = reg.call("vault_diff")
    assert d1["has_baseline"] is True
    assert d1["added_count"] == d1["modified_count"] == d1["deleted_count"] == 0
    json.dumps(d1)


def test_vault_graph_analysis_structure(mcp_vault):
    # Issue #12: gaps + bridges + stats, JSON-serialisable over the wire.
    result = _registry().call("vault_graph_analysis", top_k=5)
    assert set(result) == {"stats", "gaps", "bridges"}
    assert {"notes", "edges", "components", "isolated"} <= set(result["stats"])
    assert isinstance(result["gaps"], list)
    assert isinstance(result["bridges"], list)
    json.dumps(result)


def test_vault_stats_structure(mcp_vault):
    result = _registry().call("vault_stats")
    for key in ("notes", "chunks", "embedded", "summaries", "graph_edges",
                "triples", "excitability", "memories"):
        assert key in result, key
    assert result["notes"] == 4  # fixture vault: 3 notes + index.md
    assert result["chunks"] > 0
    json.dumps(result)


def test_vault_prediction_errors_structure(mcp_vault):
    # Seed one note flagged twice (threshold: PREDICTION_ERROR_MIN_OCCURRENCES=2)
    # and one flagged once, which must stay below the reporting threshold.
    from neurostack.config import get_config
    from neurostack.schema import get_db

    conn = get_db(get_config().db_path)
    conn.executemany(
        "INSERT INTO prediction_errors "
        "(note_path, query, cosine_distance, error_type) VALUES (?, ?, ?, ?)",
        [
            ("research/long-note.md", "unrelated query", 0.8, "low_overlap"),
            ("research/long-note.md", "another query", 0.7, "low_overlap"),
            ("research/memory-consolidation.md", "one-off", 0.9, "low_overlap"),
        ],
    )
    conn.commit()
    conn.close()

    result = _registry().call("vault_prediction_errors")

    assert set(result) == {
        "total_flagged_notes", "total_flagged_memories", "showing", "errors"
    }
    assert result["total_flagged_notes"] == 1
    assert result["showing"] == 1
    err = result["errors"][0]
    assert err["note_path"] == "research/long-note.md"
    assert err["error_type"] == "low_overlap"
    assert err["occurrences"] == 2
    json.dumps(result)
