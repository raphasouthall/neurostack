"""Profession-specific vault scaffolding.

Each profession pack adds:
- Extra templates (in vault-template/professions/<name>/templates/)
- Seed research notes (in vault-template/professions/<name>/research/)
- Extra directories to scaffold
- CLAUDE.md overlay with domain context
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Resolve the vault-template root relative to this package
_PACK_ROOT = Path(__file__).resolve().parent.parent.parent / "vault-template" / "professions"


@dataclass
class Profession:
    """Definition of a profession pack."""

    name: str
    description: str
    extra_dirs: list[str] = field(default_factory=list)
    claude_md_section: str = ""


# ── Registry ────────────────────────────────────────────────────────
PROFESSIONS: dict[str, Profession] = {
    "researcher": Profession(
        name="researcher",
        description=(
            "Academic or independent researcher"
            " — literature reviews, experiments, thesis work"
        ),
        extra_dirs=[
            "research/methods",
            "literature/sources",
            "experiments",
            "experiments/logs",
        ],
        claude_md_section="""\

## Researcher Workflow

### Literature Pipeline
1. Capture source → `literature/sources/` using literature-note template
2. Extract atomic insights → `research/` using research-note template
3. Synthesise across sources → `research/` using synthesis-note template

### Experiment Tracking
- Log each experiment in `experiments/logs/` using experiment-log template
- Record hypothesis, method, results, and interpretation
- Link to relevant literature and research notes

### Methodology Notes
- Store reusable methods in `research/methods/`
- Cross-link from experiment logs

### Writing Projects
- Use `home/projects/` for papers, theses, and grant applications
- Use project-note template with writing-specific sections
""",
    ),
}


def list_professions() -> list[Profession]:
    """Return all registered professions."""
    return list(PROFESSIONS.values())


def get_profession(name: str) -> Optional[Profession]:
    """Look up a profession by name (case-insensitive)."""
    return PROFESSIONS.get(name.lower())


def apply_profession(vault_root: Path, profession: Profession) -> list[str]:
    """Apply a profession pack to an initialised vault.

    Returns list of actions taken (for CLI output).
    """
    actions: list[str] = []
    pack_dir = _PACK_ROOT / profession.name

    if not pack_dir.exists():
        raise FileNotFoundError(f"Profession pack not found: {pack_dir}")

    # 1. Create extra directories
    for d in profession.extra_dirs:
        p = vault_root / d
        if not p.exists():
            p.mkdir(parents=True)
            # Create index.md stub
            idx = p / "index.md"
            idx.write_text(f"# {p.name.replace('-', ' ').title()}\n\n")
            actions.append(f"  + {d}/")

    # 2. Copy profession-specific templates
    src_templates = pack_dir / "templates"
    dst_templates = vault_root / "templates"
    if src_templates.exists():
        dst_templates.mkdir(parents=True, exist_ok=True)
        for tmpl in sorted(src_templates.glob("*.md")):
            dst = dst_templates / tmpl.name
            if not dst.exists():
                shutil.copy2(tmpl, dst)
                actions.append(f"  + templates/{tmpl.name}")

    # 3. Copy seed research notes
    src_research = pack_dir / "research"
    dst_research = vault_root / "research"
    if src_research.exists():
        dst_research.mkdir(parents=True, exist_ok=True)
        for note in sorted(src_research.glob("*.md")):
            if note.name == "index.md":
                continue  # handled separately
            dst = dst_research / note.name
            if not dst.exists():
                shutil.copy2(note, dst)
                actions.append(f"  + research/{note.name}")

        # Append to research index if seed index exists
        seed_index = src_research / "index.md"
        if seed_index.exists():
            dst_idx = dst_research / "index.md"
            existing = dst_idx.read_text() if dst_idx.exists() else "# Research\n\n"
            seed_entries = seed_index.read_text()
            # Extract just the entries (skip the heading)
            lines = seed_entries.strip().split("\n")
            entries = [line for line in lines if line.startswith("- ")]
            if entries:
                # Check which entries are already present
                new_entries = [e for e in entries if e not in existing]
                if new_entries:
                    existing = existing.rstrip() + "\n" + "\n".join(new_entries) + "\n"
                    dst_idx.write_text(existing)
                    actions.append(f"  + research/index.md (appended {len(new_entries)} entries)")

    # 4. Copy seed literature notes
    src_literature = pack_dir / "literature"
    dst_literature = vault_root / "literature"
    if src_literature.exists():
        dst_literature.mkdir(parents=True, exist_ok=True)
        for note in sorted(src_literature.glob("*.md")):
            if note.name == "index.md":
                continue
            dst = dst_literature / note.name
            if not dst.exists():
                shutil.copy2(note, dst)
                actions.append(f"  + literature/{note.name}")

    # 5. Copy experiment seed notes (or any other pack-specific dirs)
    for extra_dir in profession.extra_dirs:
        src_extra = pack_dir / extra_dir
        dst_extra = vault_root / extra_dir
        if src_extra.exists():
            dst_extra.mkdir(parents=True, exist_ok=True)
            for note in sorted(src_extra.glob("*.md")):
                if note.name == "index.md":
                    continue
                dst = dst_extra / note.name
                if not dst.exists():
                    shutil.copy2(note, dst)
                    actions.append(f"  + {extra_dir}/{note.name}")

    # 6. Append profession section to CLAUDE.md
    claude_md = vault_root / "CLAUDE.md"
    if claude_md.exists() and profession.claude_md_section:
        content = claude_md.read_text()
        marker = f"## {profession.name.title()} Workflow"
        if marker not in content:
            content = content.rstrip() + "\n" + profession.claude_md_section + "\n"
            claude_md.write_text(content)
            actions.append("  + CLAUDE.md (appended profession section)")

    return actions
