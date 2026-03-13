# Contributing to NeuroStack

Thanks for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/neurostack.git`
3. Install in development mode:
   ```bash
   cd neurostack
   uv sync --extra dev --extra full
   ```
4. Create a branch: `git checkout -b feature/your-feature`

## Development

- Run tests: `uv run pytest`
- Lint: `uv run ruff check src/`
- Format: `uv run ruff format src/`

## Pull Requests

- Keep PRs focused on a single change
- Include tests for new features
- Update docs if needed
- Ensure all tests pass before submitting

## Reporting Issues

Use [GitHub Issues](https://github.com/raphasouthall/neurostack/issues) with:
- Steps to reproduce
- Expected vs actual behavior
- OS, Python version, install mode (lite/full)

## Code of Conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
