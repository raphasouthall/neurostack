# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack checkpoint-llm`: answer a checkpoint prompt with the index LLM (issue #236).

`checkpoint_command` is any shell command that reads a prompt on stdin and
prints the model's reply. `neurostack init` points it here, so a checkpoint
uses the same endpoint, model and key as summaries do and nobody has to write
a curl script.
"""

import sys


def cmd_checkpoint_llm(args):
    import httpx

    from ..config import _auth_headers, get_config
    from ..synthesize import run_index_llm

    cfg = get_config()
    prompt = sys.stdin.read()
    try:
        if cfg.index_llm_command:
            reply = run_index_llm(prompt, cfg.index_llm_command, cfg.checkpoint_timeout_s)
        else:
            resp = httpx.post(
                f"{cfg.index_llm_url}/v1/chat/completions",
                headers=_auth_headers(cfg.index_llm_api_key),
                json={"model": cfg.index_llm_model, "stream": False, "temperature": 0.2,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=cfg.checkpoint_timeout_s,
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        # The checkpoint runner reports the last stderr line when this exits non-zero.
        sys.exit(f"neurostack checkpoint-llm: {type(exc).__name__}: {exc}")
    print(reply)
