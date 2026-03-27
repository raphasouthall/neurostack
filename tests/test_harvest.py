"""Tests for neurostack.harvest — session transcript insight extraction."""

import json

from neurostack.harvest import (
    AiderProvider,
    ClaudeCodeProvider,
    GeminiCLIProvider,
    Message,
    _extract_gemini_content,
    _extract_tags,
    _extract_text_claude,
    _load_harvest_state,
    _make_summary,
    _parse_jsonl,
    _prefilter_classify,
    _save_harvest_state,
)

# ---------------------------------------------------------------------------
# _parse_jsonl
# ---------------------------------------------------------------------------

class TestParseJsonl:
    def test_valid_jsonl(self, tmp_path):
        f = tmp_path / "valid.jsonl"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        result = _parse_jsonl(f)
        assert result == [{"a": 1}, {"b": 2}]

    def test_skips_malformed_lines(self, tmp_path):
        f = tmp_path / "mixed.jsonl"
        f.write_text('{"ok": true}\nnot json\n{"also": "ok"}\n')
        result = _parse_jsonl(f)
        assert result == [{"ok": True}, {"also": "ok"}]

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert _parse_jsonl(f) == []

    def test_blank_lines_skipped(self, tmp_path):
        f = tmp_path / "blanks.jsonl"
        f.write_text('\n\n{"x": 1}\n\n')
        assert _parse_jsonl(f) == [{"x": 1}]

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.jsonl"
        assert _parse_jsonl(f) == []


# ---------------------------------------------------------------------------
# _extract_text_claude
# ---------------------------------------------------------------------------

class TestExtractTextClaude:
    def test_string_content(self):
        entry = {"message": {"content": "hello world"}}
        assert _extract_text_claude(entry) == "hello world"

    def test_list_of_text_blocks(self):
        entry = {"message": {"content": [
            {"text": "part one"},
            {"text": "part two"},
        ]}}
        assert _extract_text_claude(entry) == "part one part two"

    def test_list_with_content_key(self):
        entry = {"message": {"content": [
            {"content": "from content key"},
        ]}}
        assert _extract_text_claude(entry) == "from content key"

    def test_mixed_list_strings_and_dicts(self):
        entry = {"message": {"content": [
            "raw string",
            {"text": "dict text"},
        ]}}
        assert _extract_text_claude(entry) == "raw string dict text"

    def test_empty_list(self):
        entry = {"message": {"content": []}}
        assert _extract_text_claude(entry) is None

    def test_no_content(self):
        entry = {"message": {}}
        assert _extract_text_claude(entry) is None

    def test_fallback_to_top_level_content(self):
        entry = {"content": "top level"}
        assert _extract_text_claude(entry) == "top level"


# ---------------------------------------------------------------------------
# _prefilter_classify
# ---------------------------------------------------------------------------

class TestPrefilterClassify:
    def test_bug_pattern(self):
        text = "The root cause was a missing null check in the handler function."
        assert _prefilter_classify(text, "assistant") == "bug"

    def test_decision_pattern(self):
        text = "We decided to use PostgreSQL over SQLite for the production database."
        assert _prefilter_classify(text, "assistant") == "decision"

    def test_convention_pattern(self):
        text = "You must always use absolute paths when referencing config files."
        assert _prefilter_classify(text, "assistant") == "convention"

    def test_learning_pattern(self):
        text = "I discovered that the API rate limit resets every 60 seconds not 30."
        assert _prefilter_classify(text, "assistant") == "learning"

    def test_observation_pattern(self):
        text = "The API key is stored at /etc/myapp/credentials and rotated weekly."
        assert _prefilter_classify(text, "assistant") == "observation"

    def test_short_text_rejected(self):
        assert _prefilter_classify("root cause", "assistant") is None
        assert _prefilter_classify("x" * 39, "assistant") is None

    def test_no_match(self):
        text = "Here is the output of the command that you requested from me."
        assert _prefilter_classify(text, "assistant") is None

    def test_user_correction_wait(self):
        text = "Wait, that's not what I wanted. Please use the other approach instead."
        assert _prefilter_classify(text, "user") == "convention"

    def test_user_correction_no(self):
        text = "No, don't do that. I need something completely different here."
        assert _prefilter_classify(text, "user") == "convention"

    def test_user_correction_dont(self):
        text = "Don't use that library, it has known security vulnerabilities."
        assert _prefilter_classify(text, "user") == "convention"

    def test_user_correction_actually(self):
        text = "Actually, let me reconsider — the config should go in /etc not /opt."
        assert _prefilter_classify(text, "user") == "convention"

    def test_user_correction_not_from_assistant(self):
        # Correction patterns only fire for user role
        text = "Wait, that's not what I wanted. Please use the other approach instead."
        assert _prefilter_classify(text, "assistant") is None


# ---------------------------------------------------------------------------
# _make_summary
# ---------------------------------------------------------------------------

class TestMakeSummary:
    def test_extracts_first_sentence(self):
        text = "The fix was quite simple indeed. We just needed to add a null check."
        assert _make_summary(text) == "The fix was quite simple indeed."

    def test_exclamation_sentence(self):
        text = "This was a critical finding! More details follow in the report."
        assert _make_summary(text) == "This was a critical finding!"

    def test_question_sentence(self):
        text = "Did you know the API resets hourly? That changes everything."
        assert _make_summary(text) == "Did you know the API resets hourly?"

    def test_truncation_when_long(self):
        text = "x" * 300
        result = _make_summary(text)
        assert len(result) == 200
        assert result.endswith("...")

    def test_short_text_returned_as_is(self):
        text = "Short text without punctuation"
        assert _make_summary(text) == text

    def test_multiline_collapsed(self):
        text = "Line one.\nLine two continues here."
        result = _make_summary(text)
        assert "\n" not in result
        # Regex requires 20+ chars before first sentence end, so short
        # first sentences don't match — full collapsed text is returned
        assert result == "Line one. Line two continues here."


# ---------------------------------------------------------------------------
# _extract_tags
# ---------------------------------------------------------------------------

class TestExtractTags:
    def test_python_extension(self):
        text = "Edit src/neurostack/harvest.py to fix the bug"
        tags = _extract_tags(text)
        assert "py" in tags

    def test_typescript_extension(self):
        text = "Check the file at app/components/Header.ts for the error"
        tags = _extract_tags(text)
        assert "ts" in tags

    def test_parent_directory_extracted(self):
        text = "Look at src/neurostack/harvest.py"
        tags = _extract_tags(text)
        assert "neurostack" in tags

    def test_multiple_extensions(self):
        text = "Update config.toml and handler.py and schema.json"
        tags = _extract_tags(text)
        assert "toml" in tags
        assert "py" in tags
        assert "json" in tags

    def test_max_five_tags(self):
        text = "a.py b.ts c.js d.rs e.go f.md g.toml"
        tags = _extract_tags(text)
        assert len(tags) <= 5

    def test_no_file_paths(self):
        text = "This text has no file paths at all"
        assert _extract_tags(text) == []

    def test_sorted_output(self):
        text = "z.py a.ts m.js"
        tags = _extract_tags(text)
        assert tags == sorted(tags)


# ---------------------------------------------------------------------------
# _extract_gemini_content
# ---------------------------------------------------------------------------

class TestExtractGeminiContent:
    def test_string_content(self):
        assert _extract_gemini_content("hello") == "hello"

    def test_empty_string(self):
        assert _extract_gemini_content("   ") is None

    def test_dict_with_text(self):
        assert _extract_gemini_content({"text": "from dict"}) == "from dict"

    def test_dict_empty_text(self):
        assert _extract_gemini_content({"text": ""}) is None

    def test_list_of_strings(self):
        result = _extract_gemini_content(["part one", "part two"])
        assert result == "part one part two"

    def test_list_of_dicts(self):
        result = _extract_gemini_content([{"text": "a"}, {"text": "b"}])
        assert result == "a b"

    def test_list_skips_thought_parts(self):
        content = [
            {"text": "visible", "thought": False},
            {"text": "hidden", "thought": True},
            {"text": "also visible"},
        ]
        result = _extract_gemini_content(content)
        assert result == "visible also visible"

    def test_empty_list(self):
        assert _extract_gemini_content([]) is None

    def test_none_content(self):
        assert _extract_gemini_content(None) is None

    def test_mixed_list(self):
        content = ["raw text", {"text": "dict text"}]
        result = _extract_gemini_content(content)
        assert result == "raw text dict text"


# ---------------------------------------------------------------------------
# ClaudeCodeProvider.extract_messages
# ---------------------------------------------------------------------------

class TestClaudeCodeProvider:
    def test_extract_messages(self, tmp_path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "hello"}}),
            json.dumps({"message": {"role": "assistant", "content": "world"}}),
        ]
        f.write_text("\n".join(lines) + "\n")
        provider = ClaudeCodeProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 2
        assert msgs[0] == Message(role="user", text="hello")
        assert msgs[1] == Message(role="assistant", text="world")

    def test_skips_non_user_assistant(self, tmp_path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"message": {"role": "system", "content": "sys"}}),
            json.dumps({"type": "tool_use", "content": "tool"}),
            json.dumps({"message": {"role": "user", "content": "ok"}}),
        ]
        f.write_text("\n".join(lines) + "\n")
        provider = ClaudeCodeProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 1
        assert msgs[0].role == "user"

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        provider = ClaudeCodeProvider()
        assert provider.extract_messages(f) == []


# ---------------------------------------------------------------------------
# AiderProvider.extract_messages
# ---------------------------------------------------------------------------

class TestAiderProvider:
    def test_extract_messages(self, tmp_path):
        f = tmp_path / ".aider.chat.history.md"
        f.write_text(
            "#### user\n"
            "Please fix the bug\n"
            "in the handler\n"
            "#### assistant\n"
            "I've fixed it by adding a null check.\n"
        )
        provider = AiderProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert "fix the bug" in msgs[0].text
        assert "in the handler" in msgs[0].text
        assert msgs[1].role == "assistant"
        assert "null check" in msgs[1].text

    def test_multiple_exchanges(self, tmp_path):
        f = tmp_path / ".aider.chat.history.md"
        f.write_text(
            "#### user\nFirst question\n"
            "#### assistant\nFirst answer\n"
            "#### user\nSecond question\n"
            "#### assistant\nSecond answer\n"
        )
        provider = AiderProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 4
        assert msgs[2].role == "user"
        assert "Second question" in msgs[2].text

    def test_single_hash_headers(self, tmp_path):
        f = tmp_path / "chat.md"
        f.write_text("# user\nWith single hash\n# assistant\nReply\n")
        provider = AiderProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("")
        provider = AiderProvider()
        assert provider.extract_messages(f) == []

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.md"
        provider = AiderProvider()
        assert provider.extract_messages(f) == []


# ---------------------------------------------------------------------------
# GeminiCLIProvider.extract_messages
# ---------------------------------------------------------------------------

class TestGeminiCLIProvider:
    def test_extract_messages(self, tmp_path):
        f = tmp_path / "session.json"
        data = {
            "messages": [
                {"type": "user", "content": "What is Python?"},
                {"type": "gemini", "content": "A programming language."},
            ]
        }
        f.write_text(json.dumps(data))
        provider = GeminiCLIProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 2
        assert msgs[0] == Message(role="user", text="What is Python?")
        assert msgs[1] == Message(role="assistant", text="A programming language.")

    def test_skips_info_and_error_types(self, tmp_path):
        f = tmp_path / "session.json"
        data = {
            "messages": [
                {"type": "info", "content": "Session started"},
                {"type": "error", "content": "Something failed"},
                {"type": "warning", "content": "Heads up"},
                {"type": "user", "content": "hello"},
            ]
        }
        f.write_text(json.dumps(data))
        provider = GeminiCLIProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 1
        assert msgs[0].role == "user"

    def test_dict_content(self, tmp_path):
        f = tmp_path / "session.json"
        data = {"messages": [{"type": "gemini", "content": {"text": "from dict"}}]}
        f.write_text(json.dumps(data))
        provider = GeminiCLIProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 1
        assert msgs[0].text == "from dict"

    def test_list_content_with_thoughts(self, tmp_path):
        f = tmp_path / "session.json"
        data = {"messages": [
            {"type": "gemini", "content": [
                {"text": "visible"},
                {"text": "thinking", "thought": True},
            ]},
        ]}
        f.write_text(json.dumps(data))
        provider = GeminiCLIProvider()
        msgs = provider.extract_messages(f)
        assert len(msgs) == 1
        assert msgs[0].text == "visible"

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json")
        provider = GeminiCLIProvider()
        assert provider.extract_messages(f) == []

    def test_empty_messages(self, tmp_path):
        f = tmp_path / "session.json"
        f.write_text(json.dumps({"messages": []}))
        provider = GeminiCLIProvider()
        assert provider.extract_messages(f) == []


# ---------------------------------------------------------------------------
# Harvest state persistence
# ---------------------------------------------------------------------------

class TestHarvestState:
    def test_load_save_roundtrip(self, tmp_path, monkeypatch):
        state_file = tmp_path / "harvest_state.json"
        monkeypatch.setattr(
            "neurostack.harvest._harvest_state_path",
            lambda: state_file,
        )
        # Initially empty
        assert _load_harvest_state() == {}

        # Save and reload
        state = {"/path/to/session.jsonl": 1234567890.0}
        _save_harvest_state(state)
        loaded = _load_harvest_state()
        assert loaded == state

    def test_load_corrupt_file(self, tmp_path, monkeypatch):
        state_file = tmp_path / "harvest_state.json"
        state_file.write_text("not valid json{{{")
        monkeypatch.setattr(
            "neurostack.harvest._harvest_state_path",
            lambda: state_file,
        )
        assert _load_harvest_state() == {}

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        state_file = tmp_path / "sub" / "dir" / "harvest_state.json"
        monkeypatch.setattr(
            "neurostack.harvest._harvest_state_path",
            lambda: state_file,
        )
        _save_harvest_state({"a": 1.0})
        assert state_file.exists()
        assert json.loads(state_file.read_text()) == {"a": 1.0}

    def test_overwrite_existing(self, tmp_path, monkeypatch):
        state_file = tmp_path / "harvest_state.json"
        monkeypatch.setattr(
            "neurostack.harvest._harvest_state_path",
            lambda: state_file,
        )
        _save_harvest_state({"first": 1.0})
        _save_harvest_state({"second": 2.0})
        loaded = _load_harvest_state()
        assert loaded == {"second": 2.0}
