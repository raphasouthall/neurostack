# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""`neurostack agent <job>`: run a bundled Pi agent job (issue #217).

Jobs that need tools and reasoning, promotion first, run on the Pi SDK instead
of a harness CLI. The runner and its package.json ship as package data; the
Node dependencies install once into the state directory and are reused until
package.json changes.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"
JOBS = {
    "promotion": {"timeout_s": 2700, "thinking": "medium"},
}
# A prompt file you supply runs with these limits; the job name only picks a
# bundled prompt, so personal jobs stay out of the package.
CUSTOM = {"timeout_s": 1800, "thinking": "medium"}
MIN_NODE = (22, 19)


class AgentError(RuntimeError):
    """The agent cannot start: node, npm, or an API key is missing."""


def _state_dir() -> Path:
    return Path.home() / ".cache" / "neurostack" / "agent"


def _check_node() -> str:
    node = shutil.which("node")
    if not node:
        raise AgentError(f"node not found; install Node.js {MIN_NODE[0]}.{MIN_NODE[1]} or newer")
    raw = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    version = tuple(int(x) for x in raw.strip().lstrip("v").split(".")[:2])
    if version < MIN_NODE:
        raise AgentError(f"node {raw.strip()} is too old; need "
                         f"{MIN_NODE[0]}.{MIN_NODE[1]} or newer")
    return node


def _install(state: Path) -> None:
    """Copy the runner in and install its dependencies when package.json changed."""
    manifest = (AGENT_DIR / "package.json").read_bytes()
    stamp = state / ".installed"
    digest = hashlib.sha256(manifest).hexdigest()
    state.mkdir(parents=True, exist_ok=True)
    if not stamp.exists() or stamp.read_text() != digest:
        (state / "package.json").write_bytes(manifest)
        npm = shutil.which("npm")
        if not npm:
            raise AgentError("npm not found")
        subprocess.run([npm, "install", "--no-audit", "--no-fund", "--omit=dev"],
                       cwd=state, check=True)
        stamp.write_text(digest)
    shutil.copyfile(AGENT_DIR / "run.mjs", state / "run.mjs")


def job_prompt(job: str) -> str:
    return (AGENT_DIR / "jobs" / f"{job}.md").read_text(encoding="utf-8")


def run_agent(cfg, prompt: str, spec: dict[str, Any], *, cwd: str, model: str | None = None,
              timeout: int | None = None) -> int:
    """Run one Pi agent job to completion and return the runner's exit code.

    The runner's stdout goes to whatever `sys.stdout` is, so `run-due` can keep
    its own stdout for the JSON report.
    """
    node = _check_node()
    key = cfg.agent_api_key or cfg.judge_api_key
    if not key:
        raise AgentError("set agent_api_key (or judge_api_key) in config.toml")

    state = _state_dir()
    _install(state)
    job = {
        "cwd": cwd,
        "prompt": prompt,
        "state_dir": str(state),
        "provider": cfg.agent_provider,
        "model": model or cfg.agent_model,
        "base_url": cfg.agent_base_url,
        "api_key": key,
        "thinking": spec["thinking"],
        "timeout_s": timeout or spec["timeout_s"],
    }
    env = {
        **os.environ,
        "NEUROSTACK_AGENT_JOB": json.dumps(job),
        "NEUROSTACK_AGENT_CLI": json.dumps([sys.executable, "-m", "neurostack"]),
    }
    return subprocess.run([node, str(state / "run.mjs")], cwd=cwd, env=env,
                          stdout=sys.stdout).returncode


def cmd_agent(args):
    from ..config import get_config

    cfg = get_config()
    if bool(args.job) == bool(args.prompt_file):
        sys.exit("neurostack agent: give a bundled job or --prompt-file, not both or neither")
    if args.job:
        spec = JOBS[args.job]
        prompt = job_prompt(args.job)
    else:
        spec = CUSTOM
        src = sys.stdin if args.prompt_file == "-" else open(args.prompt_file, encoding="utf-8")
        with src:
            prompt = src.read()
    if args.mode:
        prompt += f"\n\n## RUN MODE\nMODE={args.mode}\n"
    cwd = str(Path(args.cwd or cfg.vault_root).expanduser())
    try:
        code = run_agent(cfg, prompt, spec, cwd=cwd, model=args.model, timeout=args.timeout)
    except AgentError as exc:
        sys.exit(f"neurostack agent: {exc}")
    sys.exit(code)
