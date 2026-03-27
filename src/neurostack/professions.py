"""Profession-specific vault scaffolding.

Each profession pack adds:
- Extra templates (in vault-template/professions/<name>/templates/)
- Seed research notes (in vault-template/professions/<name>/research/)
- Extra directories to scaffold
- AGENTS.md overlay with domain context
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _resolve_pack_root() -> Path:
    """Locate the professions directory inside the vault template."""
    # Package location first (pip/wheel installs)
    pkg = Path(__file__).resolve().parent / "vault_template" / "professions"
    if pkg.is_dir():
        return pkg
    # Repo root fallback (git checkout / editable installs)
    repo = Path(__file__).resolve().parent.parent.parent / "vault-template" / "professions"
    if repo.is_dir():
        return repo
    return repo  # return repo path even if missing — callers handle exists()


_PACK_ROOT = _resolve_pack_root()


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
    "developer": Profession(
        name="developer",
        description=(
            "Software developer or engineer"
            " — architecture decisions, code reviews, debugging"
        ),
        extra_dirs=[
            "work/architecture",
            "work/debugging",
            "research/patterns",
        ],
        claude_md_section="""\

## Developer Workflow

### Architecture Decisions
- Record decisions in `work/architecture/` using architecture-decision template
- Include context, options considered, and trade-offs
- Link to relevant technical specs and research notes

### Debugging & Investigation
- Log investigations in `work/debugging/` using debugging-log template
- Record root cause, fix, and lessons learned
- Link to related architecture decisions

### Code Reviews
- Capture recurring patterns and insights using code-review-note template
- Store reusable patterns in `research/patterns/`

### Technical Specs
- Use technical-spec template for feature and system designs
- Link to architecture decisions and related project notes
""",
    ),
    "writer": Profession(
        name="writer",
        description=(
            "Writer or content creator"
            " — fiction, articles, worldbuilding, craft notes"
        ),
        extra_dirs=[
            "home/projects/drafts",
            "research/craft",
            "literature/sources",
        ],
        claude_md_section="""\

## Writer Workflow

### Story & Article Pipeline
1. Outline in `home/projects/` using story-outline or article-draft template
2. Develop characters in `home/projects/` using character-profile template
3. Build world details using world-building-note template

### Craft Notes
- Store writing craft insights in `research/craft/`
- Extract techniques from literature into research notes

### Literature & Inspiration
- Capture source material in `literature/sources/` using literature-note template
- Extract insights into permanent research notes

### Drafts
- Work-in-progress drafts live in `home/projects/drafts/`
- Move to `archive/` when published or abandoned
""",
    ),
    "student": Profession(
        name="student",
        description=(
            "Student or lifelong learner"
            " — lectures, study guides, courses, exam prep"
        ),
        extra_dirs=[
            "work/courses",
            "work/assignments",
            "research/study-methods",
        ],
        claude_md_section="""\

## Student Workflow

### Course Management
- Create a course-overview note per course in `work/courses/`
- Link lecture notes, assignments, and study guides to the course

### Lecture Capture
- Use lecture-note template during or after class
- Tag with course name and topic
- Extract key concepts into permanent research notes

### Study & Exam Prep
- Build study guides using study-guide template
- Use active recall and spaced repetition principles
- Store study methods in `research/study-methods/`

### Assignments
- Track assignments in `work/assignments/` using assignment-tracker template
- Link to relevant lecture notes and research
""",
    ),
    "devops": Profession(
        name="devops",
        description=(
            "DevOps engineer or SRE"
            " — runbooks, incidents, infrastructure, change management"
        ),
        extra_dirs=[
            "work/runbooks",
            "work/incidents",
            "work/infrastructure",
        ],
        claude_md_section="""\

## DevOps Workflow

### Runbooks
- Store operational runbooks in `work/runbooks/` using runbook template
- Keep runbooks actionable with step-by-step commands
- Link to related infrastructure notes and incident reports

### Incident Management
- Record post-incident reviews in `work/incidents/` using incident-report template
- Include timeline, root cause, impact, and action items
- Link to runbooks that were used or need updating

### Infrastructure Documentation
- Document systems and services in `work/infrastructure/` using infrastructure-note template
- Include architecture diagrams, dependencies, and SLOs

### Change Management
- Record changes using change-request template
- Link to affected infrastructure notes and runbooks
""",
    ),
    "data-scientist": Profession(
        name="data-scientist",
        description=(
            "Data scientist or ML engineer"
            " — analyses, models, datasets, experiment tracking"
        ),
        extra_dirs=[
            "work/analyses",
            "work/models",
            "work/datasets",
            "experiments/logs",
        ],
        claude_md_section="""\

## Data Scientist Workflow

### Analysis Pipeline
1. Document datasets in `work/datasets/` using dataset-note template
2. Record analyses in `work/analyses/` using analysis-note template
3. Document models in `work/models/` using model-card template

### Experiment Tracking
- Log experiments in `experiments/logs/` using experiment-log template
- Record hypothesis, methodology, metrics, and conclusions
- Link to datasets and model cards

### Data Pipelines
- Document pipelines using pipeline-note template
- Include data lineage, transformations, and dependencies

### Research & Methods
- Store ML/stats insights as permanent research notes
- Cross-link between analyses, models, and research
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

    # 6. Append profession section to AGENTS.md (legacy CLAUDE.md also supported)
    agents_md = vault_root / "AGENTS.md"
    if not agents_md.exists():
        agents_md = vault_root / "CLAUDE.md"
    if agents_md.exists() and profession.claude_md_section:
        content = agents_md.read_text()
        marker = f"## {profession.name.title()} Workflow"
        if marker not in content:
            content = content.rstrip() + "\n" + profession.claude_md_section + "\n"
            agents_md.write_text(content)
            actions.append(f"  + {agents_md.name} (appended profession section)")

    return actions
