# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Markdown heading-based chunker with frontmatter parser."""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Chunk:
    heading_path: str  # e.g. "## Architecture > ### Networking"
    content: str
    position: int


@dataclass
class ParsedNote:
    path: str
    title: str
    frontmatter: dict = field(default_factory=dict)
    content_hash: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    wiki_links: list[str] = field(default_factory=list)


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+?)?\]\]")

# Target max chunk size in characters (~500 tokens ≈ ~2000 chars)
MAX_CHUNK_CHARS = 2000


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata, remaining_content)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[match.end() :]


def chunk_by_headings(content: str) -> list[Chunk]:
    """Split markdown content into chunks by ## headings."""
    chunks = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    position = 0

    def flush():
        nonlocal position
        text = "\n".join(current_lines).strip()
        if text:
            path = (
                " > ".join(
                    f"{'#' * lvl} {name}"
                    for lvl, name in heading_stack
                )
                if heading_stack
                else "(intro)"
            )
            # Split oversized chunks
            if len(text) > MAX_CHUNK_CHARS:
                for i in range(0, len(text), MAX_CHUNK_CHARS):
                    sub = text[i : i + MAX_CHUNK_CHARS].strip()
                    if sub:
                        chunks.append(Chunk(heading_path=path, content=sub, position=position))
                        position += 1
            else:
                chunks.append(Chunk(heading_path=path, content=text, position=position))
                position += 1

    for line in content.split("\n"):
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            name = m.group(2).strip()
            # Flush current content
            flush()
            current_lines = [line]
            # Update heading stack
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, name))
        else:
            current_lines.append(line)

    flush()
    return chunks


def extract_wiki_links(content: str) -> list[str]:
    """Extract wiki-link targets from markdown content."""
    return list(set(WIKI_LINK_RE.findall(content)))


def parse_note(path: Path, vault_root: Path) -> ParsedNote:
    """Parse a markdown note into structured data."""
    text = path.read_text(encoding="utf-8", errors="replace")
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    frontmatter, body = parse_frontmatter(text)

    # Title: from frontmatter, first H1, or filename
    title = frontmatter.get("title", "")
    if not title:
        h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = h1.group(1) if h1 else path.stem

    rel_path = str(path.relative_to(vault_root))
    chunks = chunk_by_headings(body)
    wiki_links = extract_wiki_links(body)

    return ParsedNote(
        path=rel_path,
        title=title,
        frontmatter=frontmatter,
        content_hash=content_hash,
        chunks=chunks,
        wiki_links=wiki_links,
    )
