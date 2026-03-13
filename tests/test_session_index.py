"""Tests for neurostack.session_index — text extraction and since parsing."""

import argparse
from datetime import datetime, timezone

import pytest

from neurostack.session_index import (
    extract_file_paths,
    extract_text_content,
    extract_tool_names,
    parse_since,
)


class TestExtractTextContent:
    def test_string_content(self):
        assert extract_text_content({"content": "hello"}) == "hello"

    def test_text_block(self):
        msg = {"content": [{"type": "text", "text": "hello world"}]}
        assert "hello world" in extract_text_content(msg)

    def test_thinking_block(self):
        msg = {"content": [{"type": "thinking", "thinking": "let me think"}]}
        assert "let me think" in extract_text_content(msg)

    def test_tool_use_block(self):
        msg = {
            "content": [
                {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/test"}}
            ]
        }
        result = extract_text_content(msg)
        assert "Read" in result
        assert "/tmp/test" in result

    def test_mixed_blocks(self):
        msg = {
            "content": [
                {"type": "text", "text": "First"},
                {"type": "thinking", "thinking": "Second"},
            ]
        }
        result = extract_text_content(msg)
        assert "First" in result
        assert "Second" in result

    def test_empty_content(self):
        assert extract_text_content({}) == ""

    def test_list_of_strings(self):
        msg = {"content": ["hello", "world"]}
        result = extract_text_content(msg)
        assert "hello" in result
        assert "world" in result


class TestExtractToolNames:
    def test_single_tool(self):
        msg = {"content": [{"type": "tool_use", "name": "Read"}]}
        assert extract_tool_names(msg) == "Read"

    def test_multiple_tools(self):
        msg = {
            "content": [
                {"type": "tool_use", "name": "Read"},
                {"type": "text", "text": "hello"},
                {"type": "tool_use", "name": "Write"},
            ]
        }
        assert extract_tool_names(msg) == "Read,Write"

    def test_no_tools(self):
        msg = {"content": [{"type": "text", "text": "just text"}]}
        assert extract_tool_names(msg) == ""

    def test_string_content(self):
        msg = {"content": "plain string"}
        assert extract_tool_names(msg) == ""


class TestExtractFilePaths:
    def test_absolute_paths(self):
        text = "Reading /home/user/file.txt and /etc/config"
        paths = extract_file_paths(text)
        assert "/home/user/file.txt" in paths
        assert "/etc/config" in paths

    def test_home_paths(self):
        text = "Check ~/brain/research/note.md"
        paths = extract_file_paths(text)
        assert "~/brain/research/note.md" in paths

    def test_relative_paths(self):
        text = "Edit ./src/main.py"
        paths = extract_file_paths(text)
        assert "./src/main.py" in paths

    def test_no_paths(self):
        assert extract_file_paths("no paths here") == ""

    def test_limit_to_20(self):
        text = " ".join(f"/path/to/file{i}.txt" for i in range(30))
        paths = extract_file_paths(text)
        assert len(paths.split(",")) <= 20


class TestParseSince:
    def test_days(self):
        result = parse_since("2d")
        cutoff = datetime.fromisoformat(result)
        now = datetime.now(timezone.utc)
        diff = now - cutoff.replace(tzinfo=timezone.utc)
        assert 1.9 < diff.total_seconds() / 86400 < 2.1

    def test_hours(self):
        result = parse_since("3h")
        cutoff = datetime.fromisoformat(result)
        now = datetime.now(timezone.utc)
        diff = now - cutoff.replace(tzinfo=timezone.utc)
        assert 2.9 < diff.total_seconds() / 3600 < 3.1

    def test_weeks(self):
        result = parse_since("1w")
        cutoff = datetime.fromisoformat(result)
        now = datetime.now(timezone.utc)
        diff = now - cutoff.replace(tzinfo=timezone.utc)
        assert 6.9 < diff.total_seconds() / 86400 < 7.1

    def test_invalid_format(self):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_since("invalid")
