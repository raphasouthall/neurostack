"""Tests for neurostack.capture — zero-friction inbox capture."""

import re

from neurostack.capture import _make_slug, capture_thought


class TestMakeSlug:
    def test_normal_text(self):
        assert _make_slug("Hello World") == "hello-world"

    def test_lowercases(self):
        assert _make_slug("FOO BAR BAZ") == "foo-bar-baz"

    def test_removes_special_chars(self):
        assert _make_slug("hello! @world# $test") == "hello-world-test"

    def test_collapses_multiple_hyphens(self):
        assert _make_slug("foo---bar") == "foo-bar"

    def test_strips_leading_trailing_hyphens(self):
        assert _make_slug("---hello---") == "hello"

    def test_empty_string_returns_capture(self):
        assert _make_slug("") == "capture"

    def test_only_special_chars_returns_capture(self):
        assert _make_slug("!!! @@@") == "capture"

    def test_long_text_truncates_to_max_words(self):
        text = "one two three four five six seven eight"
        slug = _make_slug(text)
        assert slug == "one-two-three-four-five"

    def test_custom_max_words(self):
        text = "one two three four five six"
        assert _make_slug(text, max_words=3) == "one-two-three"

    def test_single_word(self):
        assert _make_slug("hello") == "hello"

    def test_hyphens_preserved_within_words(self):
        assert _make_slug("well-known fact") == "well-known-fact"


class TestCaptureThought:
    def test_creates_file_in_inbox(self, tmp_path):
        result = capture_thought("A quick thought", str(tmp_path))
        abs_path = result["absolute_path"]
        assert (tmp_path / "inbox").is_dir()
        assert abs_path.startswith(str(tmp_path / "inbox"))
        assert abs_path.endswith(".md")

    def test_returns_expected_keys(self, tmp_path):
        result = capture_thought("test content", str(tmp_path))
        assert "path" in result
        assert "absolute_path" in result
        assert "title" in result

    def test_relative_path_starts_with_inbox(self, tmp_path):
        result = capture_thought("test", str(tmp_path))
        assert result["path"].startswith("inbox/")

    def test_file_content_matches(self, tmp_path):
        result = capture_thought("My brilliant idea", str(tmp_path))
        content = open(result["absolute_path"], encoding="utf-8").read()
        assert "My brilliant idea" in content

    def test_frontmatter_structure(self, tmp_path):
        result = capture_thought("test note", str(tmp_path))
        content = open(result["absolute_path"], encoding="utf-8").read()
        assert content.startswith("---\n")
        assert "type: capture" in content
        assert re.search(r"date: \d{4}-\d{2}-\d{2}", content)

    def test_frontmatter_no_tags(self, tmp_path):
        result = capture_thought("no tags here", str(tmp_path))
        content = open(result["absolute_path"], encoding="utf-8").read()
        assert "tags: []" in content

    def test_frontmatter_with_tags(self, tmp_path):
        result = capture_thought(
            "tagged thought", str(tmp_path),
            tags=["idea", "project"],
        )
        content = open(result["absolute_path"], encoding="utf-8").read()
        assert "tags: [idea, project]" in content

    def test_frontmatter_single_tag(self, tmp_path):
        result = capture_thought(
            "one tag", str(tmp_path),
            tags=["solo"],
        )
        content = open(result["absolute_path"], encoding="utf-8").read()
        assert "tags: [solo]" in content

    def test_title_is_full_content_when_short(self, tmp_path):
        text = "Short thought"
        result = capture_thought(text, str(tmp_path))
        assert result["title"] == text

    def test_title_truncated_at_80_chars(self, tmp_path):
        text = "A" * 120
        result = capture_thought(text, str(tmp_path))
        assert len(result["title"]) == 80
        assert result["title"] == "A" * 80

    def test_title_exactly_80_chars_not_truncated(self, tmp_path):
        text = "B" * 80
        result = capture_thought(text, str(tmp_path))
        assert result["title"] == text

    def test_filename_contains_slug(self, tmp_path):
        result = capture_thought("Hello World", str(tmp_path))
        assert "hello-world" in result["path"]

    def test_filename_has_timestamp(self, tmp_path):
        result = capture_thought("test", str(tmp_path))
        filename = result["path"].split("/")[-1]
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{6}_", filename)

    def test_valid_yaml_frontmatter(self, tmp_path):
        result = capture_thought(
            "yaml test", str(tmp_path),
            tags=["foo", "bar"],
        )
        content = open(result["absolute_path"], encoding="utf-8").read()
        # Frontmatter is enclosed between two --- lines
        parts = content.split("---")
        assert len(parts) >= 3
        fm = parts[1]
        assert "date:" in fm
        assert "type:" in fm
        assert "tags:" in fm

    def test_creates_inbox_dir_if_missing(self, tmp_path):
        vault = tmp_path / "nested" / "vault"
        capture_thought("test", str(vault))
        assert (vault / "inbox").is_dir()

    def test_empty_tags_list_same_as_none(self, tmp_path):
        r1 = capture_thought("a", str(tmp_path / "v1"), tags=None)
        r2 = capture_thought("b", str(tmp_path / "v2"), tags=[])
        c1 = open(r1["absolute_path"], encoding="utf-8").read()
        c2 = open(r2["absolute_path"], encoding="utf-8").read()
        assert "tags: []" in c1
        assert "tags: []" in c2
