# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""NeuroStack retrieves, it does not answer (issue #142).

One test per acceptance item: the answering surfaces are gone, the session
summary is the caller's to write, auto-labelling never reaches for a model, and
the pre-#142 config names still load under their new names.
"""

import logging
import re
import sys
from pathlib import Path

import httpx
import pytest

from neurostack import config as nsconfig
from neurostack.config import load_config


@pytest.fixture
def no_http(monkeypatch):
    """Fail the test on any outbound HTTP request.

    Patched at the transport layer, so it catches ``httpx.post`` and any client
    the code under test builds for itself — not just one call site.
    """
    def _refuse(self, request):
        raise AssertionError(f"unexpected HTTP request to {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refuse)


# ── 1. vault_ask and `neurostack ask` are gone ──────────────────────────────


def test_vault_ask_not_registered():
    from neurostack.tools import ensure_registered

    names = {t.name for t in ensure_registered().list_tools()}
    assert "vault_ask" not in names
    assert "vault_search" in names  # the replacement is still there


def test_neurostack_ask_points_at_search(tmp_path, monkeypatch, capsys):
    from neurostack.cli import main

    monkeypatch.setattr(sys, "argv", ["neurostack", "--vault", str(tmp_path), "ask", "q?"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "removed" in out
    assert "neurostack search" in out


# ── 2. the REST answering model is gone ─────────────────────────────────────


def test_api_has_no_ask_surface():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from neurostack.api import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)

    assert client.get("/ask").status_code == 404

    model_ids = {m["id"] for m in client.get("/v1/models").json()["data"]}
    assert "neurostack-ask" not in model_ids
    assert "neurostack-search" in model_ids

    rejected = client.post(
        "/v1/chat/completions",
        json={"model": "neurostack-ask", "messages": [{"role": "user", "content": "q?"}]},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["error"]["code"] == "model_not_found"


# ── 3. the session summary is the caller's to write ─────────────────────────


@pytest.fixture
def session_db(tmp_path, monkeypatch):
    """Point the configured DB at a temp dir so the registry tools share it."""
    monkeypatch.setenv("NEUROSTACK_DB_DIR", str(tmp_path))
    nsconfig._config = None
    from neurostack.schema import get_db

    conn = get_db()
    yield conn
    conn.close()
    nsconfig._config = None


def _stored_summary(conn, session_id):
    from neurostack.memories import get_session

    return get_session(conn, session_id)["summary"]


def test_session_end_stores_caller_summary(session_db, no_http):
    from neurostack.tools.session_tools import vault_session_end, vault_session_start

    session_id = vault_session_start(source_agent="test")["session_id"]
    vault_session_end(session_id, summary="x", auto_harvest=False)

    assert _stored_summary(session_db, session_id) == "x"


def test_session_end_without_summary_stores_none_and_calls_nothing(session_db, no_http):
    from neurostack.tools.session_tools import vault_session_end, vault_session_start

    session_id = vault_session_start(source_agent="test")["session_id"]
    vault_session_end(session_id, auto_harvest=False)

    assert not _stored_summary(session_db, session_id)


# ── 4. auto-labelling needs no model ────────────────────────────────────────


def test_autolabel_produces_labels_with_no_llm(tmp_path, no_http, capsys, caplog):
    from types import SimpleNamespace

    from neurostack import autolabel
    from neurostack.cli.search import _autolabel_queries
    from neurostack.schema import get_db

    db_file = tmp_path / "labels.db"
    conn = get_db(db_file)
    conn.execute(
        "INSERT INTO notes (path, title, frontmatter, content_hash, updated_at) "
        "VALUES ('notes/alpha.md', 'Alpha', '{}', 'h1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO summaries (note_path, summary_text, content_hash, updated_at) "
        "VALUES ('notes/alpha.md', 'Configures the alpha subsystem.', 'h1', "
        "'2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    assert not hasattr(autolabel, "llm_labels")

    # The eval run embeds each unique query afterwards. That is the embedder, not
    # a generation model, so it is stubbed rather than being what this asserts.
    args = SimpleNamespace(autolabel_n=10, autolabel_seed=0, embed_url="http://embed.test")
    ev = SimpleNamespace(
        build_embedding_cache=lambda queries, embed_url: {q.query: [0.0] for q in queries},
    )

    with caplog.at_level(logging.WARNING):
        queries, cache = _autolabel_queries(args, db_file, ev)

    assert [q.category for q in queries] == ["autolabel-summary"]
    assert cache == {"Configures the alpha subsystem.": [0.0]}
    assert not [r for r in caplog.records if "LLM" in r.getMessage()]
    assert "LLM" not in capsys.readouterr().out


# ── 5. the pre-#142 config names still load ─────────────────────────────────


def _write_config(monkeypatch, tmp_path, body):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(nsconfig, "CONFIG_PATH", path)
    return path


def _config_warnings(caplog):
    return [r for r in caplog.records if r.name == "neurostack.config"]


def test_legacy_llm_url_loads_with_one_deprecation_line(tmp_path, monkeypatch, caplog):
    _write_config(monkeypatch, tmp_path, 'llm_url = "http://x"\n')

    with caplog.at_level(logging.WARNING, logger="neurostack.config"):
        cfg = load_config()

    assert cfg.index_llm_url == "http://x"
    records = _config_warnings(caplog)
    assert len(records) == 1
    assert "llm_url -> index_llm_url" in records[0].getMessage()


def test_current_name_logs_nothing(tmp_path, monkeypatch, caplog):
    _write_config(monkeypatch, tmp_path, 'index_llm_url = "http://x"\n')

    with caplog.at_level(logging.WARNING, logger="neurostack.config"):
        cfg = load_config()

    assert cfg.index_llm_url == "http://x"
    assert _config_warnings(caplog) == []


def test_current_name_wins_over_legacy(tmp_path, monkeypatch, caplog):
    _write_config(
        monkeypatch, tmp_path,
        'llm_url = "http://old"\nindex_llm_url = "http://new"\n',
    )

    with caplog.at_level(logging.WARNING, logger="neurostack.config"):
        cfg = load_config()

    assert cfg.index_llm_url == "http://new"
    assert len(_config_warnings(caplog)) == 1


def test_legacy_env_vars_load_under_new_names(tmp_path, monkeypatch, caplog):
    _write_config(monkeypatch, tmp_path, "")
    monkeypatch.setenv("NEUROSTACK_LLM_URL", "http://env-old")
    monkeypatch.setenv("NEUROSTACK_LLM_MODEL", "old-model")

    with caplog.at_level(logging.WARNING, logger="neurostack.config"):
        cfg = load_config()

    assert cfg.index_llm_url == "http://env-old"
    assert cfg.index_llm_model == "old-model"
    # One line for the whole load, naming both old names.
    records = _config_warnings(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "NEUROSTACK_LLM_URL -> NEUROSTACK_INDEX_LLM_URL" in message
    assert "NEUROSTACK_LLM_MODEL -> NEUROSTACK_INDEX_LLM_MODEL" in message


def test_new_env_var_wins_over_legacy(tmp_path, monkeypatch, caplog):
    _write_config(monkeypatch, tmp_path, "")
    monkeypatch.setenv("NEUROSTACK_LLM_URL", "http://env-old")
    monkeypatch.setenv("NEUROSTACK_INDEX_LLM_URL", "http://env-new")

    with caplog.at_level(logging.WARNING, logger="neurostack.config"):
        cfg = load_config()

    assert cfg.index_llm_url == "http://env-new"


# ── 6. no llm_url reference outside the config alias ────────────────────────


def test_llm_url_survives_only_as_a_config_alias():
    # `\bllm_url\b` cannot match inside `index_llm_url` — `_` is a word
    # character — so every hit here is a genuine pre-#142 name.
    legacy = re.compile(r"\bllm_url\b")
    src = Path(__file__).resolve().parents[1] / "src" / "neurostack"
    hits = {
        (str(path.relative_to(src)), line.strip())
        for path in src.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if legacy.search(line)
    }
    assert {f for f, _ in hits} == {"config.py"}, hits
    # ...and only inside the two alias maps that translate them.
    assert all(
        text.startswith(('"llm_url":', '"NEUROSTACK_LLM_URL":')) for _, text in hits
    ), hits
