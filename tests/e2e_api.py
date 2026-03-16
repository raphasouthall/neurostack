#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""E2E tests for OpenAI-compatible API endpoints."""

import json
import subprocess
import sys
import time

import httpx

BASE = "http://127.0.0.1:8199"
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} -- {detail}")


def test_health():
    print("\n=== /health ===")
    r = httpx.get(f"{BASE}/health")
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("status ok", d.get("status") == "ok", d)
    check("version present", "version" in d, d)


def test_models():
    print("\n=== /v1/models ===")
    r = httpx.get(f"{BASE}/v1/models")
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("object is list", d.get("object") == "list", d.get("object"))
    ids = {m["id"] for m in d.get("data", [])}
    for m in ("neurostack-ask", "neurostack-search",
              "neurostack-tiered", "neurostack-triples"):
        check(f"model {m} listed", m in ids, ids)


def test_chat_search():
    print("\n=== /v1/chat/completions (search) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-search",
        "messages": [{"role": "user", "content": "kubernetes"}],
        "top_k": 3,
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("has id", d.get("id", "").startswith("chatcmpl-"), d.get("id"))
    check("object type", d.get("object") == "chat.completion", d.get("object"))
    check("has choices", len(d.get("choices", [])) == 1, d.get("choices"))
    msg = d.get("choices", [{}])[0].get("message", {})
    check("role assistant", msg.get("role") == "assistant", msg.get("role"))
    check("content non-empty", len(msg.get("content", "")) > 0)
    choices = d.get("choices", [])
    check("finish_reason stop",
          len(choices) > 0 and choices[0].get("finish_reason") == "stop")
    check("has usage", "usage" in d, d.keys())
    u = d.get("usage", {})
    check("usage has prompt_tokens", "prompt_tokens" in u)
    check("usage has completion_tokens", "completion_tokens" in u)
    check("usage has total_tokens", "total_tokens" in u)


def test_chat_tiered():
    print("\n=== /v1/chat/completions (tiered) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-tiered",
        "messages": [{"role": "user", "content": "azure devops"}],
        "top_k": 3,
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("model echoed", d.get("model") == "neurostack-tiered")
    choices = d.get("choices", [])
    content = choices[0]["message"]["content"] if choices else ""
    check("content present", len(content) > 0)


def test_chat_triples():
    print("\n=== /v1/chat/completions (triples) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-triples",
        "messages": [{"role": "user", "content": "helm chart"}],
        "top_k": 5,
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("model echoed", d.get("model") == "neurostack-triples")


def test_chat_stream():
    print("\n=== /v1/chat/completions (stream) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-search",
        "messages": [{"role": "user", "content": "kubernetes"}],
        "top_k": 2,
        "stream": True,
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    ct = r.headers.get("content-type", "")
    check("content-type is event-stream", "text/event-stream" in ct, ct)
    # SSE lines may use \r\n; normalize and extract data: lines
    lines = r.text.replace("\r\n", "\n").strip().split("\n")
    data_lines = [
        l.removeprefix("data:").strip()
        for l in lines if l.startswith("data:")
    ]
    check("has data lines", len(data_lines) >= 3,
          f"got {len(data_lines)} data lines")
    # Filter out empty keep-alive lines
    data_lines = [d for d in data_lines if d]
    # Check first chunk has role
    first = json.loads(data_lines[0])
    check("first chunk has role",
          first["choices"][0]["delta"].get("role") == "assistant")
    # Check last real chunk has finish_reason=stop
    json_lines = [d for d in data_lines if d != "[DONE]"]
    last = json.loads(json_lines[-1])
    check("last chunk finish_reason=stop",
          last["choices"][0].get("finish_reason") == "stop")
    # Check [DONE] sentinel
    check("ends with [DONE]", data_lines[-1] == "[DONE]")


def test_chat_bad_model():
    print("\n=== /v1/chat/completions (bad model) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "test"}],
    })
    check("status 400", r.status_code == 400, f"got {r.status_code}")
    d = r.json()
    check("has error", "error" in d.get("detail", {}), d)


def test_chat_no_user_msg():
    print("\n=== /v1/chat/completions (no user msg) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-search",
        "messages": [{"role": "system", "content": "you are helpful"}],
    })
    check("status 400", r.status_code == 400, f"got {r.status_code}")


def test_embeddings_single():
    print("\n=== /v1/embeddings (single) ===")
    r = httpx.post(f"{BASE}/v1/embeddings", json={
        "input": "test embedding query",
        "model": "nomic-embed-text",
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("object is list", d.get("object") == "list")
    check("has data", len(d.get("data", [])) == 1)
    emb = d["data"][0]
    check("embedding object type", emb.get("object") == "embedding")
    check("index is 0", emb.get("index") == 0)
    vec = emb.get("embedding", [])
    check("768 dimensions", len(vec) == 768, f"got {len(vec)}")
    check("values are floats", isinstance(vec[0], float), type(vec[0]))
    check("has usage", "usage" in d)


def test_embeddings_batch():
    print("\n=== /v1/embeddings (batch) ===")
    r = httpx.post(f"{BASE}/v1/embeddings", json={
        "input": ["first text", "second text", "third text"],
        "model": "nomic-embed-text",
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()
    check("3 embeddings returned", len(d.get("data", [])) == 3)
    for i, emb in enumerate(d["data"]):
        check(f"index {i} correct", emb.get("index") == i)
        check(f"embedding {i} is 768d",
              len(emb.get("embedding", [])) == 768)


def test_auth_rejected():
    print("\n=== Auth (no key configured - should pass) ===")
    r = httpx.post(f"{BASE}/v1/chat/completions",
                   json={
                       "model": "neurostack-search",
                       "messages": [{"role": "user", "content": "test"}],
                       "top_k": 1,
                   },
                   headers={"Authorization": "Bearer wrong-key"},
                   timeout=30.0)
    # No api_key set, so any token should be accepted
    check("no auth configured = 200", r.status_code == 200,
          f"got {r.status_code}")


def test_workspace_filter():
    print("\n=== Workspace filter ===")
    r = httpx.post(f"{BASE}/v1/chat/completions", json={
        "model": "neurostack-search",
        "messages": [{"role": "user", "content": "azure"}],
        "top_k": 3,
        "workspace": "work/acme-cloud",
    }, timeout=30.0)
    check("status 200", r.status_code == 200, f"got {r.status_code}")
    content = r.json()["choices"][0]["message"]["content"]
    check("content non-empty", len(content) > 0)


if __name__ == "__main__":
    test_health()
    test_models()
    test_chat_search()
    test_chat_tiered()
    test_chat_triples()
    test_chat_stream()
    test_chat_bad_model()
    test_chat_no_user_msg()
    test_embeddings_single()
    test_embeddings_batch()
    test_auth_rejected()
    test_workspace_filter()

    print(f"\n{'='*40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
