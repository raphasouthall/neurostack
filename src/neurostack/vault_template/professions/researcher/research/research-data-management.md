---
date: 2026-01-20
tags: [methodology, data-management, open-science]
type: permanent
status: active
actionable: true
compositional: true
---

# Research Data Management

Good data management is a prerequisite for reproducibility, collaboration, and compliance with funder mandates. Poor data management is the most common (and least glamorous) reason results can't be reproduced.

## FAIR Principles

- **Findable** — persistent identifiers (DOIs), rich metadata, registered in searchable resources
- **Accessible** — retrievable via standard protocols, metadata always available even if data is restricted
- **Interoperable** — uses shared vocabularies, qualified references, open formats
- **Reusable** — clear licences, provenance, community standards

## Practical Minimum

1. **File naming**: `YYYY-MM-DD_experiment-name_version.ext` — no spaces, no special characters
2. **Folder structure**: separate raw data (read-only), processed data, analysis scripts, and outputs
3. **README**: every dataset gets a README with variables, units, collection dates, and contact
4. **Version control**: Git for code, DVC or Git-LFS for data
5. **Backup**: 3-2-1 rule (3 copies, 2 media types, 1 offsite)

## Data Management Plan (DMP)

Most funders now require a DMP. Key sections:
- What data will be generated
- How it will be stored and backed up
- Who can access it and under what terms
- Where it will be archived (repository, embargo period, licence)

## Related Notes

- [[reproducibility-crisis]] — data management failures underpin many replication issues
- [[systematic-review-methodology]] — data extraction requires structured management
