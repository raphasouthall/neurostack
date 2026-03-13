"""Tests for neurostack.graph — wiki-link graph, PageRank, neighborhood."""

from neurostack.graph import compute_pagerank, get_neighborhood, resolve_wiki_link


class TestResolveWikiLink:
    def test_exact_match(self):
        paths = ["research/predictive-coding.md", "research/memory.md"]
        result = resolve_wiki_link("research/predictive-coding.md", paths)
        assert result == "research/predictive-coding.md"

    def test_stem_match(self):
        paths = ["research/predictive-coding.md", "research/memory.md"]
        assert resolve_wiki_link("predictive-coding", paths) == "research/predictive-coding.md"

    def test_case_insensitive(self):
        paths = ["research/Predictive-Coding.md"]
        assert resolve_wiki_link("predictive-coding", paths) == "research/Predictive-Coding.md"

    def test_no_match(self):
        paths = ["research/other.md"]
        assert resolve_wiki_link("nonexistent", paths) is None

    def test_with_md_suffix(self):
        paths = ["research/note.md"]
        assert resolve_wiki_link("research/note", paths) == "research/note.md"


class TestComputePageRank:
    def test_simple_graph(self, in_memory_db):
        conn = in_memory_db
        # Insert notes
        for path in ["a.md", "b.md", "c.md"]:
            conn.execute(
                "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
                (path, path, "h", "2026-01-01"),
            )
        # a -> b -> c -> a (cycle)
        conn.execute("INSERT INTO graph_edges VALUES ('a.md', 'b.md', 'b')")
        conn.execute("INSERT INTO graph_edges VALUES ('b.md', 'c.md', 'c')")
        conn.execute("INSERT INTO graph_edges VALUES ('c.md', 'a.md', 'a')")
        conn.commit()

        compute_pagerank(conn)

        rows = conn.execute("SELECT * FROM graph_stats ORDER BY note_path").fetchall()
        assert len(rows) == 3
        # In a cycle, all nodes should have equal PageRank
        prs = [r["pagerank"] for r in rows]
        assert abs(prs[0] - prs[1]) < 0.001
        assert abs(prs[1] - prs[2]) < 0.001

    def test_hub_node(self, in_memory_db):
        conn = in_memory_db
        for path in ["hub.md", "a.md", "b.md", "c.md"]:
            conn.execute(
                "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
                (path, path, "h", "2026-01-01"),
            )
        # a, b, c all link to hub
        conn.execute("INSERT INTO graph_edges VALUES ('a.md', 'hub.md', 'hub')")
        conn.execute("INSERT INTO graph_edges VALUES ('b.md', 'hub.md', 'hub')")
        conn.execute("INSERT INTO graph_edges VALUES ('c.md', 'hub.md', 'hub')")
        conn.commit()

        compute_pagerank(conn)

        hub = conn.execute(
            "SELECT pagerank FROM graph_stats WHERE note_path = 'hub.md'"
        ).fetchone()
        others = conn.execute(
            "SELECT pagerank FROM graph_stats WHERE note_path != 'hub.md'"
        ).fetchall()
        assert hub["pagerank"] > max(r["pagerank"] for r in others)

    def test_empty_graph(self, in_memory_db):
        compute_pagerank(in_memory_db)
        rows = in_memory_db.execute("SELECT * FROM graph_stats").fetchall()
        assert len(rows) == 0


class TestGetNeighborhood:
    def test_with_neighbors(self, in_memory_db):
        conn = in_memory_db
        for path in ["a.md", "b.md", "c.md"]:
            conn.execute(
                "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
                (path, path.replace(".md", ""), "h", "2026-01-01"),
            )
        conn.execute("INSERT INTO graph_edges VALUES ('a.md', 'b.md', 'b')")
        conn.execute("INSERT INTO graph_edges VALUES ('a.md', 'c.md', 'c')")
        compute_pagerank(conn)
        conn.commit()

        result = get_neighborhood("a.md", depth=1, conn=conn)
        assert result is not None
        assert result.center.path == "a.md"
        assert len(result.neighbors) == 2

    def test_fuzzy_match(self, in_memory_db):
        conn = in_memory_db
        conn.execute(
            "INSERT INTO notes (path, title, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            ("research/predictive-coding.md", "Predictive Coding", "h", "2026-01-01"),
        )
        conn.commit()

        result = get_neighborhood("predictive-coding", conn=conn)
        assert result is not None
        assert result.center.path == "research/predictive-coding.md"

    def test_not_found(self, in_memory_db):
        result = get_neighborhood("nonexistent.md", conn=in_memory_db)
        assert result is None
