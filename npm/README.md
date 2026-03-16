# NeuroStack

**Build, maintain, and search your knowledge vault with AI.**

This is the npm wrapper for [NeuroStack](https://github.com/raphasouthall/neurostack). It installs the Python CLI tool so you can use it via `npx` or as a global command.

## Install

```bash
npm install -g neurostack
```

Or run without installing:

```bash
npx neurostack search "what do I know about deployment?"
```

## Requirements

- Linux or macOS
- Python 3.11+ (with SQLite FTS5)
- git, curl

The installer handles everything else automatically (installs `uv`, clones the repo, sets up a virtual environment).

## Modes

Full mode (semantic search, AI summaries, reranking) is installed by default. For Ollama-powered features, also pull the models:

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
```

For a minimal install without ML dependencies:

```bash
NEUROSTACK_MODE=lite npm install -g neurostack
```

## Links

- [GitHub](https://github.com/raphasouthall/neurostack)
- [Website](https://neurostack.sh)
- [PyPI](https://pypi.org/project/neurostack/)

## License

Apache-2.0
