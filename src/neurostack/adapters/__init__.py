# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Harness adapters for `neurostack hook` (issue #141).

An adapter is the smallest thing that turns a harness's events into the five
hook events and applies the verdict. Claude Code needs settings entries; omp
needs a small extension file. Both are generated here so a machine never
carries hand-written client code with a server address baked into it.
"""

from __future__ import annotations

from pathlib import Path

from ..setup import (
    _claude_settings_path,
    _read_json,
    _resolve_neurostack_binary,
    _write_json,
)

HARNESSES = ("claude", "omp")
_OMP_TEMPLATE = Path(__file__).parent / "omp_neurostack.ts"
_BIN_PLACEHOLDER = "__NEUROSTACK_BIN__"

# Claude Code hook event -> the `neurostack hook` event it maps to, plus the
# seconds Claude waits for it. SessionEnd is backgrounded: harvesting a whole
# transcript takes minutes and must not hold up the exit.
_CLAUDE_EVENTS = (
    ("SessionStart", "session-start", 15),
    ("UserPromptSubmit", "prompt", 15),
    ("PreToolUse", "tool-call", 10),
    ("PostToolUse", "tool-result", 10),
    ("Stop", "checkpoint", 20),
    ("SessionEnd", "session-end", None),
)

# Checkpoint cadence (issue #143), stated here because the adapters own the
# trigger and the CLI owns the skip rules.
CHECKPOINT_EVERY_MESSAGES = 40
CHECKPOINT_QUIET_MINUTES = 30
CHECKPOINT_MIN_MESSAGES = 5


def _hook_log() -> Path:
    return Path.home() / ".local" / "state" / "neurostack-hook.log"


def claude_hook_command(binary: str, event: str) -> str:
    """The shell command Claude Code runs for one hook event."""
    command = f"{binary} hook {event} --harness claude"
    if event == "session-end":
        return f"nohup {command} >>{_hook_log()} 2>&1 &"
    if event == "checkpoint":
        # A Stop hook that exits 0 shows its stdout to the user; only the
        # exit-2 block reason reaches the model, which is who has to answer.
        return (f'out=$({command}); '
                '[ -z "$out" ] || { printf \'%s\\n\' "$out" >&2; exit 2; }')
    return command


def claude_hook_entries(binary: str) -> dict[str, list[dict]]:
    """Settings entries for every Claude Code event the adapter owns."""
    entries: dict[str, list[dict]] = {}
    for claude_event, hook_event, timeout in _CLAUDE_EVENTS:
        hook: dict = {"type": "command", "command": claude_hook_command(binary, hook_event)}
        if timeout is not None:
            hook["timeout"] = timeout
        matcher: dict = {"hooks": [hook]}
        # SessionEnd and Stop are session-wide: Claude Code has nothing to
        # match them against.
        if claude_event not in ("SessionEnd", "Stop"):
            matcher["matcher"] = "*"
        entries[claude_event] = [matcher]
    return entries


def _is_neurostack_command(command: str) -> bool:
    """True for any hook command of ours, including the ones this replaces."""
    return "neurostack" in command.lower()


def _strip_neurostack_hooks(settings: dict, events: tuple[str, ...]) -> bool:
    """Drop our hook entries from the named events. Returns True if any went."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    removed = False
    for event in events:
        matchers = hooks.get(event)
        if not isinstance(matchers, list):
            continue
        kept = []
        for matcher in matchers:
            inner = matcher.get("hooks") if isinstance(matcher, dict) else None
            if not isinstance(inner, list):
                kept.append(matcher)  # not a shape we wrote — leave it alone
                continue
            trimmed = [
                h for h in inner
                if not (isinstance(h, dict) and _is_neurostack_command(h.get("command", "")))
            ]
            if len(trimmed) != len(inner):
                removed = True
                if not trimmed:
                    continue
            matcher["hooks"] = trimmed
            kept.append(matcher)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    return removed


def claude_adapter_installed() -> bool:
    """True when the settings already invoke `neurostack hook`."""
    settings = _read_json(_claude_settings_path())
    hooks = settings.get("hooks", {})
    for event, _hook_event, _timeout in _CLAUDE_EVENTS:
        for matcher in hooks.get(event, []) if isinstance(hooks, dict) else []:
            for hook in matcher.get("hooks", []):
                if " hook " in hook.get("command", ""):
                    return True
    return False


def claude_save_command_path() -> Path:
    """The `/save` slash command file Claude Code reads."""
    return Path.home() / ".claude" / "commands" / "save.md"


_CLAUDE_SAVE_COMMAND = """\
---
description: Checkpoint this session into NeuroStack memory
---

Run `{binary} hook checkpoint --harness claude </dev/null`.

It prints nothing when there is nothing new to save — say so and stop.

Otherwise it prints a prompt. Answer it: decide what a future session would
need from this one, then pipe your JSON array on stdin to
`{binary} hook checkpoint --save --harness claude`. Report the count it prints.
"""


def write_claude_save_command(binary: str) -> Path:
    """Write the `/save` command file. Overwrites, so re-installing is safe."""
    path = claude_save_command_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_CLAUDE_SAVE_COMMAND.format(binary=binary), encoding="utf-8")
    return path


def install_claude_adapter() -> tuple[str, Path]:
    """Write the Claude Code hook entries. Returns (status, settings path).

    Status is 'installed', 'not-detected', or 'no-binary'. Any earlier
    neurostack hook command on these events is replaced, so the RAG hook and
    the transcript poster this supersedes cannot double-fire.
    """
    path = _claude_settings_path()
    if not (Path.home() / ".claude").is_dir():
        return "not-detected", path
    binary = _resolve_neurostack_binary()
    if binary is None:
        return "no-binary", path

    settings = _read_json(path)
    events = tuple(event for event, _h, _t in _CLAUDE_EVENTS)
    _strip_neurostack_hooks(settings, events)
    if not isinstance(settings.get("hooks"), dict):
        settings["hooks"] = {}
    hooks = settings["hooks"]
    for event, matchers in claude_hook_entries(binary).items():
        if not isinstance(hooks.get(event), list):
            hooks[event] = []
        hooks[event].extend(matchers)
    _hook_log().parent.mkdir(parents=True, exist_ok=True)
    write_claude_save_command(binary)
    _write_json(path, settings)
    return "installed", path


def remove_claude_adapter() -> bool:
    """Strip our hook entries and the `/save` command from Claude Code."""
    path = _claude_settings_path()
    settings = _read_json(path)
    events = tuple(event for event, _h, _t in _CLAUDE_EVENTS)
    removed = _strip_neurostack_hooks(settings, events)
    save_command = claude_save_command_path()
    if save_command.exists():
        save_command.unlink()
        removed = True
    if not removed:
        return False
    _write_json(path, settings)
    return True


def omp_extension_path() -> Path:
    """Where omp loads user extensions from."""
    return Path.home() / ".omp" / "agent" / "extensions" / "neurostack.ts"


def render_omp_extension(binary: str) -> str:
    """The extension source with the CLI path resolved.

    The path is absolute on purpose: a hook must not depend on the PATH the
    harness happens to start with.
    """
    return _OMP_TEMPLATE.read_text(encoding="utf-8").replace(_BIN_PLACEHOLDER, binary)


def install_omp_adapter() -> tuple[str, Path]:
    """Write the omp extension. Returns (status, extension path)."""
    path = omp_extension_path()
    if not (Path.home() / ".omp").is_dir():
        return "not-detected", path
    binary = _resolve_neurostack_binary()
    if binary is None:
        return "no-binary", path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_omp_extension(binary), encoding="utf-8")
    return "installed", path


def remove_omp_adapter() -> bool:
    """Delete the generated omp extension."""
    path = omp_extension_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def install_adapter(harness: str) -> tuple[str, Path]:
    if harness == "claude":
        return install_claude_adapter()
    return install_omp_adapter()


def remove_adapter(harness: str) -> bool:
    if harness == "claude":
        return remove_claude_adapter()
    return remove_omp_adapter()
