# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Zero-friction inbox capture for quick thoughts."""

import re
from datetime import datetime
from pathlib import Path


def capture_thought(
    content: str,
    vault_root: str,
    tags: list[str] = None,
) -> dict:
    """Capture a quick thought into the vault inbox.

    Creates a timestamped markdown file in {vault_root}/inbox/.

    Returns dict with 'path' (relative to vault), 'absolute_path', 'title'.
    """
    now = datetime.now()
    slug = _make_slug(content)
    filename = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{slug}.md"

    inbox_dir = Path(vault_root) / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)

    abs_path = inbox_dir / filename
    rel_path = f"inbox/{filename}"

    tags_list = tags if tags else []
    frontmatter = (
        "---\n"
        f"date: {now.strftime('%Y-%m-%d')}\n"
        "type: capture\n"
        f"tags: {tags_list}\n"
        "---\n"
    )

    abs_path.write_text(f"{frontmatter}\n{content}\n", encoding="utf-8")

    return {
        "path": rel_path,
        "absolute_path": str(abs_path),
        "title": content[:80] if len(content) > 80 else content,
    }


def _make_slug(text: str, max_words: int = 5) -> str:
    """Generate a filename slug from the first few words of text."""
    words = text.split()[:max_words]
    slug = "-".join(words).lower()
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "capture"
