# Privacy Policy

**Last updated:** 3 June 2026

NeuroStack is an open-source (Apache-2.0) knowledge management tool created by Raphael Southall. It runs entirely on your own machine.

---

## What NeuroStack collects

Nothing. NeuroStack has no telemetry, no analytics, no crash reporting, and no phone-home behaviour. The maintainer receives no personal data from your use of the software.

## How your data is handled

- NeuroStack reads your Markdown vault and indexes it into a local SQLite database at `~/.local/share/neurostack/`.
- Your vault files are read-only during indexing. NeuroStack never modifies your source files unless you explicitly use the opt-in MCP write tools, which act on your own local git repository.
- The index stays on your machine. It is never sent to any server operated by NeuroStack or its maintainer.

## Third-party LLM and embedding providers

In Full mode, NeuroStack sends vault text to a language and embedding backend to generate summaries, embeddings, and knowledge-graph triples. By default this is a local [Ollama](https://ollama.ai) instance on `localhost`, so that traffic never leaves your machine.

If you configure NeuroStack to use a third-party provider instead (for example an OpenAI-compatible endpoint, Together AI, or Groq), the text and queries you send for processing go to that provider and are handled under that provider's privacy policy. This is the only situation in which any data leaves your machine, and it happens only because you configured it.

## Deleting your data

Delete the database directory at `~/.local/share/neurostack/`, or run `neurostack uninstall`. Your vault files are untouched.

## Changes to this policy

Material changes will be announced through the project's GitHub repository and changelog.

## Contact

- **GitHub:** [https://github.com/raphasouthall/neurostack](https://github.com/raphasouthall/neurostack)
