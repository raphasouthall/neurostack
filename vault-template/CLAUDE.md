# Vault — Claude Code Instructions

This is your knowledge base. Claude Code should consult it before relying on general knowledge for any system-specific topic.

## Vault Structure

- `research/` — Permanent notes (atomic insights)
- `literature/` — Source material and research outputs
- `calendar/` — Daily notes
- `inbox/` — Quick captures, unsorted
- `templates/` — Note templates
- `work/` — Work context
- `home/` — Personal projects and resources
- `archive/` — Completed items
- `meta/` — Vault maintenance

## Principles

### Navigation-First
- Read `index.md` in a folder before scanning individual files
- Every folder has an `index.md` with `- [[filename]] — one-line description` entries

### Writing Notes
- YAML frontmatter required: `date`, `tags`, `type`
- Use `[[wiki-links]]` for internal references
- Kebab-case filenames
- Bullet points over paragraphs
- Use templates from `templates/`

### Note Types
- **Literature**: Raw research. "What sources say."
- **Permanent**: Atomic insights. "What I think."
- **Project**: Active work documentation
- **Daily**: Chronological entries

### Hot Notes
Notes with `status: active` are in their excitability window — preferentially link to them when adding connections.

### Drift Detection
Notes flagged as prediction errors may be outdated or poorly linked. Review with `neurostack prediction-errors`.
