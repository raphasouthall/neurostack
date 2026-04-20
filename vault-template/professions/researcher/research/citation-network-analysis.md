---
date: 2026-01-20
tags: [methodology, bibliometrics, network-analysis]
type: permanent
status: active
---

# Citation Network Analysis

Citation networks treat papers as nodes and citations as directed edges, revealing the intellectual structure of a field through computational analysis rather than manual reading.

## Key Techniques

- **Co-citation analysis** — papers frequently cited together share conceptual ground, even if they don't cite each other
- **Bibliographic coupling** — papers that cite the same sources are working on similar problems
- **Main path analysis** — traces the most-cited route through a field's history, identifying foundational and pivotal works
- **Community detection** — clusters of densely connected papers reveal sub-fields and research fronts

## Tools

- **VOSviewer** — free, visual, widely used for co-authorship and co-citation maps
- **CiteSpace** — temporal analysis and burst detection
- **Litmaps** / **Connected Papers** — web-based, easy entry point
- **OpenAlex API** — open metadata for programmatic analysis

## When to Use

- Entering an unfamiliar field — find the foundational papers algorithmically instead of guessing
- Scoping a review — identify clusters and gaps before committing to search strings
- Tracking research fronts — burst detection highlights emerging topics

## Connection to Vault Architecture

This vault uses a similar principle — wiki-links create a citation network of your own ideas. The `neurostack graph` command reveals your vault's intellectual structure the same way VOSviewer reveals a field's.

## Related Notes

- [[systematic-review-methodology]] — citation analysis complements database searching
- [[reproducibility-crisis]] — citation networks can reveal replication clusters
