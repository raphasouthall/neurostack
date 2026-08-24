# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Mask value-shaped credentials before they reach unattended memory writes.

Used by the harvest and synthesize save paths (issue #113), never by
``save_memory`` itself: agent-written memories are deliberate, and silently
rewriting them would corrupt intentional content. Machine-generated text —
a transcript summary or a synthesized learning — has no such claim.

Patterns match the SHAPE OF A VALUE, not a mention. `"the api key is wrong"`
and the AWS documentation example `AKIAIOSFODNN7EXAMPLE` must survive; a real
`AIzaSy…` or `nsk-…` must not. False positives here silently damage stored
knowledge, so precision beats recall.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("neurostack")

# Marker left in place of a masked value. Keeps the sentence readable and makes
# a redaction greppable after the fact.
REDACTION_MARKER = "***REDACTED***"

# Documented example keys that appear in real transcripts and carry no secret.
_ALLOWLIST = frozenset({
    "AKIAIOSFODNN7EXAMPLE",
})

# A `password=` right-hand side that is a REFERENCE, not a value: an env-var
# interpolation, an all-caps env name, or a documentation placeholder. These are
# the shapes that made the live sweep's `password` hits false positives.
_PLACEHOLDER = re.compile(
    r"""^(?:
          [$%{<]                      # ${VAR}, %VAR%, {var}, <redacted>
        | [A-Z][A-Z0-9_]*$            # BARE_ENV_NAME
        | (?:your|my|the|some)[-_]     # your-password-here
        | (?:os\.environ|process\.env|import\.meta\.env)
    )""",
    re.VERBOSE,
)

# Each pattern keeps its human-readable prefix and masks only the secret tail,
# so the redacted text still says WHICH kind of credential was removed.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("neurostack-api-key", re.compile(r"nsk-[0-9A-Za-z_\-]{16,}")),
    # `pk_live_…` is Stripe's PUBLISHABLE key — public by design, not redacted.
    ("stripe-secret-key", re.compile(r"(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    ("github-token", re.compile(r"gh[pousr]_[0-9A-Za-z]{32,}")),
    ("slack-token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]{16,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("openai-key", re.compile(r"(?<![0-9A-Za-z_\-])sk-(?:proj-)?[0-9A-Za-z_\-]{32,}")),
    ("jwt", re.compile(r"eyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}")),
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    )),
    ("bearer-token", re.compile(r"(?<=Bearer )[0-9A-Za-z_\-\.]{24,}")),
    # `password = "…"` / `password: …` — the assignment shape only. A bare
    # mention of the word ("the password survived") never matches.
    ("password-assignment", re.compile(
        r"""(?<=password)(?P<sep>["']?\s*[:=]\s*["']?)(?P<value>[^\s"',;]{8,})""",
        re.IGNORECASE | re.VERBOSE,
    )),
)


def redact_secrets(text: str) -> tuple[str, list[str]]:
    """Mask credential values in ``text``.

    Returns the redacted text and the list of pattern names that fired, in
    match order. An already-masked value is left alone: the marker contains no
    characters any pattern accepts, so re-running this is a no-op.
    """
    if not text:
        return text, []

    kinds: list[str] = []

    for name, pattern in _PATTERNS:
        def _mask(match: re.Match[str], _name: str = name) -> str:
            found = match.group(0)
            if found in _ALLOWLIST:
                return found
            if _name == "password-assignment":
                if _PLACEHOLDER.match(match.group("value")):
                    return found
                kinds.append(_name)
                return match.group("sep") + REDACTION_MARKER
            kinds.append(_name)
            for prefix in ("AIza", "nsk-", "AKIA"):
                if found.startswith(prefix):
                    return prefix + REDACTION_MARKER
            return REDACTION_MARKER

        text = pattern.sub(_mask, text)

    if kinds:
        log.warning("Redacted %d credential value(s) before save: %s",
                    len(kinds), ", ".join(sorted(set(kinds))))
    return text, kinds
