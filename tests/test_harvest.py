"""Tests for neurostack.harvest — session transcript insight extraction."""

import json
import logging
from types import SimpleNamespace

from neurostack.harvest import (
    MAX_TRANSCRIPT_BYTES,
    AiderProvider,
    ClaudeCodeProvider,
    GeminiCLIProvider,
    Message,
    OmpProvider,
    _extract_gemini_content,
    _extract_tags,
    _extract_text_claude,
    _llm_classify,
    _load_harvest_state,
    _make_summary,
    _parse_jsonl,
    _prefilter_classify,
    _save_harvest_state,
    get_provider_names,
    harvest_transcript,
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

    def test_context_pattern(self):
        # Credentials/endpoints/URLs default to ephemeral 'context' (issue #30 p3).
        text = "The API key is stored at /etc/myapp/credentials and rotated weekly."
        assert _prefilter_classify(text, "assistant") == "context"

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


# ---------------------------------------------------------------------------
# _llm_classify — type validation (regression for #30)
# ---------------------------------------------------------------------------

def _skip_all(n):
    """A well-formed all-SKIP JSON reply covering n candidates."""
    return json.dumps([{"n": i + 1, "verdict": "SKIP"} for i in range(n)])


class TestLlmClassify:
    """The LLM classifier's valid-type set gates which entity types harvest emits."""

    @staticmethod
    def _stub_llm(monkeypatch, content):
        """Make _llm_classify see a fixed LLM response, with no real config/network."""
        import httpx

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": content}}]}

        monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
        cfg = SimpleNamespace(llm_api_key=None)
        monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
        monkeypatch.setattr("neurostack.config._auth_headers", lambda _key: {})

    def test_context_type_accepted(self, monkeypatch):
        # context is a real memory type (TTL-168h branch) but was missing from the
        # classifier's valid set, so harvest could never emit it — see issue #30.
        self._stub_llm(
            monkeypatch,
            '[{"n": 1, "verdict": "KEEP", "type": "context", '
            '"summary": "Vault LXC token expires Friday, rotate before then"}]',
        )
        candidates = [{
            "text": "The vault LXC token expires Friday — rotate it before then.",
            "role": "assistant",
            "prefilter_type": "observation",
        }]
        out = _llm_classify(candidates, "http://llm.test", "model")
        assert len(out) == 1
        assert out[0]["entity_type"] == "context"

    def test_unknown_type_falls_back_to_prefilter(self, monkeypatch):
        self._stub_llm(
            monkeypatch,
            '[{"n": 1, "verdict": "KEEP", "type": "banana", "summary": "nonsense label"}]',
        )
        candidates = [{
            "text": "Some candidate insight text long enough to be considered.",
            "role": "assistant",
            "prefilter_type": "observation",
        }]
        out = _llm_classify(candidates, "http://llm.test", "model")
        assert out[0]["entity_type"] == "observation"

    @staticmethod
    def _capture_prompt(monkeypatch, content):
        """Same stub, but hand back the prompt the classifier actually sent."""
        import httpx

        sent = {}

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": content}}]}

        def _post(*_a, **kwargs):
            sent["prompt"] = kwargs["json"]["messages"][0]["content"]
            sent["max_tokens"] = kwargs["json"]["max_tokens"]
            return _Resp()

        monkeypatch.setattr(httpx, "post", _post)
        cfg = SimpleNamespace(llm_api_key=None)
        monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
        monkeypatch.setattr("neurostack.config._auth_headers", lambda _key: {})
        return sent

    @staticmethod
    def _candidates(n):
        return [{
            "text": f"The root cause of failure number {i} was a missing guard clause.",
            "role": "assistant",
            "prefilter_type": "bug",
        } for i in range(n)]

    def test_prompt_demands_one_object_per_candidate(self, monkeypatch):
        # Issue #117: without the explicit count the model answered 5 of 10 and
        # kept none. The count instruction is the fix, so it is pinned here.
        # Issue #127 moved the reply to JSON and added few-shot SKIP examples.
        sent = self._capture_prompt(monkeypatch, _skip_all(3))
        _llm_classify(self._candidates(3), "http://llm.test", "model")
        assert "EXACTLY 3 objects" in sent["prompt"]
        assert '"verdict": "SKIP"' in sent["prompt"]
        assert "narration - SKIP it" in sent["prompt"]
        # One summary-carrying object per candidate does not fit in 500 tokens.
        assert sent["max_tokens"] >= 2000

    def test_batches_are_five(self, monkeypatch):
        # Issue #127: 10 let the model stop early even at 16k context.
        calls = []
        self._stub_llm(monkeypatch, _skip_all(5))
        import httpx
        real = httpx.post
        monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(
            k["json"]["messages"][0]["content"]) or real(*a, **k))
        _llm_classify(self._candidates(12), "http://llm.test", "model")
        assert [p.count("EXACTLY") for p in calls] == [1, 1, 1]
        assert "EXACTLY 5 objects" in calls[0]
        assert "EXACTLY 2 objects" in calls[2]

    def test_partial_answer_retries_missing_then_logs(self, monkeypatch, caplog):
        # A dropped candidate is a silent capture loss unless it is announced.
        # Issue #127: the unanswered indices get exactly one retry first.
        replies = iter([
            '[{"n": 1, "verdict": "SKIP"}, {"n": 2, "verdict": "KEEP", '
            '"type": "bug", "summary": "Second one mattered"}]',
            '[{"n": 1, "verdict": "KEEP", "type": "bug", "summary": "Third recovered"}]',
        ])
        prompts = []
        self._stub_llm(monkeypatch, "")
        import httpx

        class _Resp:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": self.content}}]}

        def _post(*_a, **kwargs):
            prompts.append(kwargs["json"]["messages"][0]["content"])
            return _Resp(next(replies, "[]"))

        monkeypatch.setattr(httpx, "post", _post)
        with caplog.at_level(logging.WARNING, logger="neurostack"):
            out = _llm_classify(self._candidates(5), "http://llm.test", "model")
        assert len(prompts) == 2
        assert "EXACTLY 3 objects" in prompts[1]
        assert [c["summary"] for c in out] == ["Second one mattered", "Third recovered"]
        assert "answered 3 of 5" in caplog.text
        assert "2 dropped unclassified" in caplog.text

    def test_full_answer_logs_nothing(self, monkeypatch, caplog):
        # An all-SKIP reply that covers every candidate is a real verdict, not a
        # failure — it must not cry wolf.
        self._stub_llm(monkeypatch, _skip_all(3))
        with caplog.at_level(logging.WARNING, logger="neurostack"):
            out = _llm_classify(self._candidates(3), "http://llm.test", "model")
        assert out == []
        assert "dropped unclassified" not in caplog.text

    def test_reply_tolerates_code_fence_and_prose(self, monkeypatch):
        self._stub_llm(
            monkeypatch,
            'Sure, here it is:\n```json\n[{"n": 1, "verdict": "KEEP", '
            '"type": "learning", "summary": "Fenced but fine"}]\n```',
        )
        out = _llm_classify(self._candidates(1), "http://llm.test", "model")
        assert out[0]["summary"] == "Fenced but fine"

    def test_malformed_reply_counts_as_unanswered(self, monkeypatch, caplog):
        self._stub_llm(monkeypatch, "not json at all")
        with caplog.at_level(logging.WARNING, logger="neurostack"):
            out = _llm_classify(self._candidates(2), "http://llm.test", "model")
        assert out == []
        assert "answered 0 of 2" in caplog.text

    def test_invalid_type_without_keyword_hint_becomes_observation(self, monkeypatch):
        # Issue #125: candidates without a keyword hit carry prefilter_type None.
        self._stub_llm(
            monkeypatch,
            '[{"n": 1, "verdict": "KEEP", "type": "wat", "summary": "Something worth keeping"}]',
        )
        candidates = [{"text": "x" * 50, "role": "assistant", "prefilter_type": None}]
        out = _llm_classify(candidates, "http://llm.test", "model")
        assert out[0]["entity_type"] == "observation"

    def test_llm_failure_keeps_only_keyword_hits(self, monkeypatch):
        # One LLM outage must not save every widened candidate as a memory.
        import httpx

        def _boom(*a, **k):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "post", _boom)
        cfg = SimpleNamespace(llm_api_key=None)
        monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
        monkeypatch.setattr("neurostack.config._auth_headers", lambda _key: {})
        candidates = [
            {"text": "The root cause was a stale cache entry in the loader.",
             "role": "assistant", "prefilter_type": "bug"},
            {"text": "Cloning the repository now and reading the layout.",
             "role": "assistant", "prefilter_type": None},
        ]
        out = _llm_classify(candidates, "http://llm.test", "model")
        assert [c["entity_type"] for c in out] == ["bug"]


class TestPrefilterRecall:
    """Issue #125: with an LLM the keyword gate is a hint, not a filter."""

    _PLAIN = "Cloning the website repo now and reading the Svelte layout for you."

    def test_llm_sees_messages_without_keywords(self, in_memory_db, tmp_path, monkeypatch):
        import neurostack.harvest as harvest_mod
        TestHarvestTranscript._setup(in_memory_db, tmp_path, monkeypatch)
        seen = []
        real = harvest_mod._llm_classify
        harvest_mod._llm_classify = lambda cands, *a, **k: seen.extend(cands) or []
        try:
            harvest_transcript(_claude_line("assistant", self._PLAIN) + "\n",
                               session_id="s", source_agent="claude-code", use_llm=True)
        finally:
            harvest_mod._llm_classify = real
        assert [c["prefilter_type"] for c in seen] == [None]

    def test_regex_path_still_gated_by_keywords(self, in_memory_db, tmp_path, monkeypatch):
        TestHarvestTranscript._setup(in_memory_db, tmp_path, monkeypatch)
        report = harvest_transcript(_claude_line("assistant", self._PLAIN) + "\n",
                                    session_id="s", source_agent="claude-code", use_llm=False)
        assert report["saved"] == [] and report["counts"] == {}


# ---------------------------------------------------------------------------
# harvest_sessions — per-type TTL on harvest-created memories (issue #36)
# ---------------------------------------------------------------------------

class TestHarvestTtl:
    """Auto-captured context expires in 7 days, observations in 30; durable
    types (learning, decision, ...) stay permanent. Agent-written memories are
    unaffected — the TTL lives in the harvest save path only."""

    def _run_harvest(self, in_memory_db, tmp_path, monkeypatch, classified):
        import numpy as np

        import neurostack.embedder as embedder_mod
        import neurostack.harvest as harvest_mod
        from neurostack.harvest import SessionFile

        session = SessionFile(path=tmp_path / "s.jsonl", mtime=1.0,
                              provider="claude-code")
        monkeypatch.setattr(harvest_mod, "find_recent_sessions",
                            lambda *a, **k: [session])
        monkeypatch.setattr(harvest_mod, "extract_messages", lambda s: [
            Message(role="assistant", text=c["text"]) for c in classified
        ])
        monkeypatch.setattr(harvest_mod, "_llm_classify",
                            lambda cands, *a, **k: classified)
        monkeypatch.setattr(harvest_mod, "_harvest_state_path",
                            lambda: tmp_path / "state.json")
        monkeypatch.setattr("neurostack.schema.get_db",
                            lambda path: in_memory_db)
        cfg = SimpleNamespace(embed_url="http://embed.test",
                              llm_url="http://llm.test", llm_model="m",
                              llm_api_key=None, writeback_enabled=False)
        monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)
        monkeypatch.setattr(embedder_mod, "get_embedding",
                            lambda *a, **k: np.ones(768, dtype=np.float32))
        from neurostack.harvest import harvest_sessions
        return harvest_sessions(n_sessions=1, dry_run=False)

    def test_per_type_ttl(self, in_memory_db, tmp_path, monkeypatch):
        classified = [
            {"text": "The API key is stored at /etc/app/credentials for the deploy.",
             "role": "assistant", "prefilter_type": "context",
             "entity_type": "context",
             "summary": "API key stored at /etc/app/credentials for deploys"},
            {"text": "The dashboard pipeline currently runs on agent pool two.",
             "role": "assistant", "prefilter_type": "decision",
             "entity_type": "observation",
             "summary": "Dashboard pipeline currently runs on agent pool two"},
            {"text": "We decided to use merge commits over squash for this repo.",
             "role": "assistant", "prefilter_type": "decision",
             "entity_type": "decision",
             "summary": "Use merge commits over squash for this repository"},
        ]
        report = self._run_harvest(in_memory_db, tmp_path, monkeypatch, classified)

        assert [r["status"] for r in report["saved"]] == ["saved"] * 3
        rows = {r["entity_type"]: r for r in in_memory_db.execute(
            "SELECT entity_type, expires_at,"
            " round((julianday(expires_at) - julianday('now')) * 24) AS ttl_h"
            " FROM memories").fetchall()}
        assert rows["context"]["ttl_h"] == 168
        assert rows["observation"]["ttl_h"] == 720
        assert rows["decision"]["expires_at"] is None


# ---------------------------------------------------------------------------
# OmpProvider
# ---------------------------------------------------------------------------

class TestOmpProvider:
    """Message lines carry typed content parts; only "text" parts on the
    user/assistant roles are transcript. "toolResult" text is raw tool output."""

    def test_extract_messages(self, tmp_path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "session", "cwd": "/tmp/proj", "title": "t",
                        "version": "1"}),
            json.dumps({"type": "message", "message": {
                "role": "user",
                "content": [{"type": "text", "text": "why did the build break"}]}}),
            "{not json at all",
            json.dumps({"type": "message", "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "text": "let me look"},
                    {"type": "text", "text": "the root cause was a stale lockfile"},
                    {"type": "text", "text": "the fix was to regenerate it"},
                    {"type": "toolCall", "name": "bash"},
                ]}}),
            json.dumps({"type": "message", "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "tool output noise"}]}}),
            json.dumps({"type": "custom", "customType": "note", "data": {}}),
        ]
        f.write_text("\n".join(lines) + "\n")
        msgs = OmpProvider().extract_messages(f)
        assert msgs == [
            Message(role="user", text="why did the build break"),
            Message(role="assistant",
                    text="the root cause was a stale lockfile\n"
                         "the fix was to regenerate it"),
        ]

    def test_string_content_tolerated(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(json.dumps({"type": "message", "message": {
            "role": "user", "content": "plain string body"}}) + "\n")
        assert OmpProvider().extract_messages(f) == [
            Message(role="user", text="plain string body"),
        ]

    def test_missing_content_skipped(self, tmp_path):
        f = tmp_path / "session.jsonl"
        lines = [
            json.dumps({"type": "message", "message": {"role": "user"}}),
            json.dumps({"type": "message", "message": "not a dict"}),
        ]
        f.write_text("\n".join(lines) + "\n")
        assert OmpProvider().extract_messages(f) == []

    def test_find_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        proj = tmp_path / ".omp" / "agent" / "sessions" / "-tools-neurostack"
        proj.mkdir(parents=True)
        f = proj / "2026-01-01T00-00-00Z_abc.jsonl"
        f.write_text("{}\n")
        found = OmpProvider().find_sessions(5)
        assert [s.path for s in found] == [f]
        assert found[0].provider == "omp"

    def test_registered(self):
        assert "omp" in get_provider_names()


# ---------------------------------------------------------------------------
# harvest_transcript — MCP-native harvest (issue #115)
# ---------------------------------------------------------------------------

# Same shape as a Google API key, none of its characters — assembled here so no
# secret-shaped literal is ever committed.
FAKE_GOOGLE_KEY = "AIza" + "Sy" + "B" * 33


def _claude_line(role, text):
    return json.dumps({"message": {"role": role, "content": text}})


_BUG_INSIGHT = ("The root cause was a stale resolver cache, and the fix was to "
                "invalidate the entry on every write.")
_DECISION_INSIGHT = ("We decided to keep the harvest dedup threshold at 0.88 "
                     "rather than tightening it for posted chunks.")


class TestHarvestTranscript:
    """The client posts its own transcript, so the server needs no access to the
    client's filesystem (issue #115)."""

    @staticmethod
    def _setup(in_memory_db, tmp_path, monkeypatch):
        import zlib

        import numpy as np

        import neurostack.embedder as embedder_mod
        import neurostack.harvest as harvest_mod

        monkeypatch.setattr(harvest_mod, "_harvest_state_path",
                            lambda: tmp_path / "state.json")
        monkeypatch.setattr("neurostack.schema.get_db", lambda path: in_memory_db)
        cfg = SimpleNamespace(embed_url="http://embed.test",
                              llm_url="http://llm.test", llm_model="m",
                              llm_api_key=None, writeback_enabled=False)
        monkeypatch.setattr("neurostack.config.get_config", lambda: cfg)

        def embed(content, *a, **k):
            # One-hot per distinct text: unrelated insights stay orthogonal,
            # a re-posted identical insight still lands on cosine 1.0.
            v = np.zeros(768, dtype=np.float32)
            v[zlib.crc32(content.encode()) % 768] = 1.0
            return v

        monkeypatch.setattr(embedder_mod, "get_embedding", embed)

    @staticmethod
    def _memory_contents(conn):
        return [r[0] for r in conn.execute("SELECT content FROM memories")]

    def test_saves_and_cleans_up_temp_file(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        seen = []
        real = ClaudeCodeProvider.extract_messages

        def spy(self, path):
            seen.append(path)
            return real(self, path)

        monkeypatch.setattr(ClaudeCodeProvider, "extract_messages", spy)

        report = harvest_transcript(
            _claude_line("assistant", _BUG_INSIGHT) + "\n",
            session_id="sess-1", source_agent="claude-code", use_llm=False,
        )
        assert [r["status"] for r in report["saved"]] == ["saved"]
        assert report["session_id"] == "sess-1"
        assert report["provider"] == "claude-code"
        assert report["counts"] == {"bug": 1}
        assert self._memory_contents(in_memory_db) == [_BUG_INSIGHT]
        # The transcript went through a temp file that must not outlive the call.
        assert seen and not seen[0].exists()

    def test_unknown_source_agent(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        report = harvest_transcript(
            _claude_line("assistant", _BUG_INSIGHT), session_id="sess-1",
            source_agent="not-a-provider", use_llm=False,
        )
        assert "not-a-provider" in report["error"]
        for name in get_provider_names():
            assert name in report["error"]
        assert report["saved"] == [] and report["counts"] == {}
        assert self._memory_contents(in_memory_db) == []

    def test_empty_transcript(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        report = harvest_transcript("   \n\n", session_id="s", source_agent="claude-code")
        assert "error" in report
        assert self._memory_contents(in_memory_db) == []

    def test_over_cap_asks_for_newline_chunks(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        report = harvest_transcript(
            "x" * (MAX_TRANSCRIPT_BYTES + 1), session_id="s",
            source_agent="claude-code", use_llm=False,
        )
        assert "newline" in report["error"]
        assert report["saved"] == [] and report["counts"] == {}
        assert self._memory_contents(in_memory_db) == []

    def test_repost_guard(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        transcript = _claude_line("assistant", _BUG_INSIGHT) + "\n"

        first = harvest_transcript(transcript, session_id="sess-1",
                                   source_agent="claude-code", use_llm=False)
        assert [r["status"] for r in first["saved"]] == ["saved"]

        again = harvest_transcript(transcript, session_id="sess-1",
                                   source_agent="claude-code", use_llm=False)
        assert again["note"] == "transcript already harvested"
        assert again["saved"] == [] and again["counts"] == {}

        # A changed transcript for the same session is harvested again: the
        # repeated insight dedups, the new one saves. This is what makes
        # client-side chunking with overlap safe.
        grown = transcript + _claude_line("assistant", _DECISION_INSIGHT) + "\n"
        changed = harvest_transcript(grown, session_id="sess-1",
                                     source_agent="claude-code", use_llm=False)
        assert "note" not in changed
        assert [r["status"] for r in changed["saved"]] == ["saved"]
        assert [r["status"] for r in changed["skipped"]] == ["skipped (duplicate)"]
        assert sorted(self._memory_contents(in_memory_db)) == sorted(
            [_BUG_INSIGHT, _DECISION_INSIGHT]
        )

    def test_redacts_before_storing(self, in_memory_db, tmp_path, monkeypatch):
        # The #113 contract holds on the posted path too: the shared seam
        # redacts before both the dedup check and the save.
        self._setup(in_memory_db, tmp_path, monkeypatch)
        text = (f"The root cause was the hardcoded apiKey: {FAKE_GOOGLE_KEY} in "
                "the deploy script, which nothing ever rotated.")
        report = harvest_transcript(
            _claude_line("assistant", text) + "\n", session_id="sess-1",
            source_agent="claude-code", use_llm=False,
        )
        assert report["saved"][0]["redacted"] == ["google-api-key"]
        stored = self._memory_contents(in_memory_db)
        assert len(stored) == 1
        assert "***REDACTED***" in stored[0]
        assert FAKE_GOOGLE_KEY not in stored[0]

    def test_no_messages_is_not_an_error(self, in_memory_db, tmp_path, monkeypatch):
        self._setup(in_memory_db, tmp_path, monkeypatch)
        report = harvest_transcript(
            json.dumps({"message": {"role": "system", "content": "ignored"}}) + "\n",
            session_id="sess-1", source_agent="claude-code", use_llm=False,
        )
        assert "error" not in report
        assert report["messages"] == 0
        assert report["counts"] == {} and report["saved"] == []

    def test_zero_yield_is_not_guarded(self, in_memory_db, tmp_path, monkeypatch):
        # LLM classification is not deterministic (issue #117), so recording the
        # digest after a run that kept nothing would make that loss permanent.
        # A zero-yield post stays re-postable.
        self._setup(in_memory_db, tmp_path, monkeypatch)
        transcript = _claude_line("assistant", _BUG_INSIGHT) + "\n"
        # Stand in for the model returning all-SKIP on a keepable candidate.
        # Restored by hand rather than monkeypatch.undo(), which would also
        # revert _setup's db and state-path patches.
        import neurostack.harvest as harvest_mod
        real_classify = harvest_mod._llm_classify
        harvest_mod._llm_classify = lambda *a, **k: []
        try:
            empty = harvest_transcript(transcript, session_id="sess-1",
                                       source_agent="claude-code", use_llm=True)
        finally:
            harvest_mod._llm_classify = real_classify
        assert empty["counts"] == {} and empty["saved"] == []

        retry = harvest_transcript(transcript, session_id="sess-1",
                                   source_agent="claude-code", use_llm=False)
        assert "note" not in retry
        assert len(retry["saved"]) == 1
