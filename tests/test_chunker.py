"""Tests for neurostack.chunker — frontmatter, heading-based chunking, wiki-links."""


from neurostack.chunker import (
    MAX_CHUNK_CHARS,
    chunk_by_headings,
    extract_wiki_links,
    parse_frontmatter,
    parse_note,
)


class TestParseFrontmatter:
    def test_valid_yaml(self):
        text = "---\ndate: 2026-01-01\ntags: [a, b]\ntype: permanent\n---\n\n# Hello"
        fm, body = parse_frontmatter(text)
        # YAML safe_load parses dates as datetime.date objects
        from datetime import date
        assert fm["date"] == date(2026, 1, 1)
        assert fm["tags"] == ["a", "b"]
        assert "# Hello" in body

    def test_no_frontmatter(self):
        text = "# Just a heading\n\nSome body text."
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_invalid_yaml(self):
        text = "---\n: invalid: yaml: {{{\n---\n\nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {}

    def test_empty_frontmatter(self):
        text = "---\n\n---\n\nBody"
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert "Body" in body


class TestChunkByHeadings:
    def test_single_section(self):
        content = "## Heading\n\nSome content here."
        chunks = chunk_by_headings(content)
        assert len(chunks) == 1
        assert "Heading" in chunks[0].heading_path
        assert "Some content here." in chunks[0].content

    def test_multiple_sections(self):
        content = "## First\n\nContent 1.\n\n## Second\n\nContent 2."
        chunks = chunk_by_headings(content)
        assert len(chunks) == 2
        assert chunks[0].position == 0
        assert chunks[1].position == 1

    def test_nested_headings(self):
        content = "## Parent\n\nParent text.\n\n### Child\n\nChild text."
        chunks = chunk_by_headings(content)
        assert len(chunks) == 2
        assert "## Parent" in chunks[0].heading_path
        assert "### Child" in chunks[1].heading_path

    def test_intro_content_before_headings(self):
        content = "Some intro text.\n\n## First Section\n\nSection content."
        chunks = chunk_by_headings(content)
        assert len(chunks) == 2
        assert chunks[0].heading_path == "(intro)"

    def test_oversized_chunk_split(self):
        big = "x" * (MAX_CHUNK_CHARS + 500)
        content = f"## Big Section\n\n{big}"
        chunks = chunk_by_headings(content)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk.content) <= MAX_CHUNK_CHARS

    def test_empty_content(self):
        chunks = chunk_by_headings("")
        assert chunks == []

    def test_heading_levels(self):
        content = "# H1\n\nA\n\n## H2\n\nB\n\n### H3\n\nC\n\n#### H4\n\nD"
        chunks = chunk_by_headings(content)
        assert len(chunks) == 4


class TestExtractWikiLinks:
    def test_simple_link(self):
        links = extract_wiki_links("See [[predictive-coding]] for details.")
        assert "predictive-coding" in links

    def test_aliased_link(self):
        links = extract_wiki_links("See [[predictive-coding|PC Theory]] here.")
        assert "predictive-coding" in links

    def test_multiple_links(self):
        links = extract_wiki_links("Links: [[note-a]], [[note-b]], [[note-c]]")
        assert set(links) == {"note-a", "note-b", "note-c"}

    def test_no_links(self):
        links = extract_wiki_links("No links here.")
        assert links == []

    def test_deduplication(self):
        links = extract_wiki_links("[[same]] and [[same]] again")
        assert links == ["same"]

    def test_link_with_heading_anchor(self):
        # The regex excludes # from wiki-link targets, so [[note#section]] doesn't match
        links = extract_wiki_links("See [[note#section]] for details.")
        assert links == []  # current behavior: # in link target prevents match


class TestParseNote:
    def test_full_parse(self, tmp_vault):
        path = tmp_vault / "research" / "predictive-coding.md"
        parsed = parse_note(path, tmp_vault)
        assert parsed.title == "Predictive Coding"
        assert parsed.path == "research/predictive-coding.md"
        assert "neuroscience" in parsed.frontmatter.get("tags", [])
        assert len(parsed.chunks) > 0
        assert "memory-consolidation" in parsed.wiki_links
        assert parsed.content_hash  # not empty

    def test_title_from_h1(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text("# My Title\n\nContent here.")
        parsed = parse_note(note, tmp_path)
        assert parsed.title == "My Title"

    def test_title_from_filename(self, tmp_path):
        note = tmp_path / "my-note.md"
        note.write_text("Just content, no heading.")
        parsed = parse_note(note, tmp_path)
        assert parsed.title == "my-note"
