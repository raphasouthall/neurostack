# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Setup, installation, and diagnostic CLI commands."""

import json
import os
import sys
from pathlib import Path

from .. import __version__
from ..config import CONFIG_PATH, get_config
from .cloud import _cmd_cloud_device_login, cmd_cloud_push
from .utils import _get_vault_template_dir


def _detect_hardware():
    """Detect RAM and GPU for mode recommendation."""
    import shutil
    import subprocess

    ram_gb = 0
    try:
        import os as _os
        mem_bytes = _os.sysconf("SC_PAGE_SIZE") * _os.sysconf("SC_PHYS_PAGES")
        ram_gb = mem_bytes / (1024 ** 3)
    except (ValueError, OSError):
        pass

    gpu_name = None
    gpu_vram_gb = 0
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                line = result.stdout.strip().split("\n")[0]
                parts = line.split(", ")
                if len(parts) == 2:
                    gpu_name = parts[0].strip()
                    gpu_vram_gb = int(parts[1].strip()) / 1024
        except Exception:
            pass

    return ram_gb, gpu_name, gpu_vram_gb


def _print_hardware_recommendation():
    """Print hardware info and recommend lite or full mode."""
    ram_gb, gpu_name, gpu_vram_gb = _detect_hardware()

    print("  \033[1mSystem\033[0m")
    if ram_gb > 0:
        print(f"    RAM:  {ram_gb:.0f} GB")
    if gpu_name:
        print(f"    GPU:  {gpu_name} ({gpu_vram_gb:.0f} GB VRAM)")
    else:
        print("    GPU:  None detected")

    # Recommendation: full needs 16GB+ RAM and a GPU with 6GB+ VRAM
    if gpu_name and gpu_vram_gb >= 6 and ram_gb >= 16:
        print(
            "    \033[32m✓\033[0m Recommended: \033[1mfull\033[0m mode"
            " (embeddings + LLM summaries)"
        )
        print("      Upgrade anytime: neurostack install --mode full")
    elif gpu_name and gpu_vram_gb >= 4:
        print(
            "    \033[33m!\033[0m Recommended: \033[1mlite\033[0m mode"
            " (GPU has limited VRAM for full mode)"
        )
        print("      Upgrade anytime: neurostack install --mode full")
    else:
        print(
            "    \033[36m▸\033[0m Recommended: \033[1mlite\033[0m mode"
            " (full mode requires a GPU with 6+ GB VRAM)"
        )
        print("      Upgrade anytime: neurostack install --mode full")


def _prompt(label, default="", choices=None):
    """Interactive prompt with optional default and choices."""
    if choices:
        print(f"\n  \033[1m{label}\033[0m")
        for i, (value, desc) in enumerate(choices, 1):
            marker = "\033[36m>\033[0m" if value == default else " "
            print(f"  {marker} {i}) {desc}")
        while True:
            raw = input(f"\n  Choice [1-{len(choices)}] (default: {default}): ").strip()
            if not raw:
                return default
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx][0]
            except ValueError:
                # Allow typing the value directly
                for value, _ in choices:
                    if raw.lower() == value.lower():
                        return value
            print(f"  \033[31mInvalid choice.\033[0m Enter 1-{len(choices)}.")
    else:
        raw = input(f"  {label} [{default}]: ").strip()
        return raw if raw else default


def _confirm(label, default=True):
    """Yes/no prompt."""
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"  {label} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _do_init(vault_root, cfg, profession_name=None, run_index=False):
    """Core init logic — creates vault, config, applies profession."""
    import shutil

    from ..config import CONFIG_PATH
    from ..professions import apply_profession, get_profession

    vault_root = Path(vault_root)

    # Create vault directory structure
    dirs = ["research", "literature", "calendar", "inbox", "templates", "archive", "meta"]
    context_dirs = ["home/projects", "home/resources", "work"]
    created = []
    for d in dirs + context_dirs:
        p = vault_root / d
        if not p.exists():
            p.mkdir(parents=True)
            created.append(d)

    # Copy base templates from vault-template/
    base_template = _get_vault_template_dir()
    if base_template is not None:
        src_agents = base_template / "AGENTS.md"
        dst_agents = vault_root / "AGENTS.md"
        if src_agents.exists() and not dst_agents.exists():
            shutil.copy2(src_agents, dst_agents)
            created.append("AGENTS.md")

        src_templates = base_template / "templates"
        dst_templates = vault_root / "templates"
        if src_templates.exists():
            for tmpl in sorted(src_templates.glob("*.md")):
                dst = dst_templates / tmpl.name
                if not dst.exists():
                    shutil.copy2(tmpl, dst)

        src_research = base_template / "research"
        if src_research.exists():
            for note in sorted(src_research.glob("*.md")):
                dst = vault_root / "research" / note.name
                if not dst.exists():
                    shutil.copy2(note, dst)

    # Create index.md files
    for d in dirs + context_dirs:
        idx = vault_root / d / "index.md"
        if not idx.exists():
            label = d.split("/")[-1].replace("-", " ").title()
            idx.write_text(f"# {label}\n\n")

    # Write config — preserve existing [cloud] section
    try:
        import tomllib as _tomllib
    except ImportError:
        import tomli as _tomllib  # type: ignore
    import tomli_w as _tomli_w

    existing = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            existing = _tomllib.load(f)

    existing["mode"] = cfg.mode
    existing["vault_root"] = str(vault_root)
    existing["embed_url"] = cfg.embed_url
    existing["llm_url"] = cfg.llm_url
    existing["llm_model"] = cfg.llm_model
    if cfg.llm_api_key:
        existing["llm_api_key"] = cfg.llm_api_key
    if cfg.embed_api_key:
        existing["embed_api_key"] = cfg.embed_api_key

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "wb") as f:
        _tomli_w.dump(existing, f)

    # Create DB directory
    cfg.db_dir.mkdir(parents=True, exist_ok=True)

    if created:
        print(f"\n  \033[32m✓\033[0m Created vault at {vault_root}")
        print(f"    Directories: {', '.join(created)}")
    else:
        print(f"\n  \033[32m✓\033[0m Vault already exists at {vault_root}")

    print(f"  \033[32m✓\033[0m Config: {CONFIG_PATH}")

    # Apply profession pack
    if profession_name and profession_name != "none":
        profession = get_profession(profession_name)
        if profession:
            print(f"  \033[32m✓\033[0m Applying '{profession.name}' profession pack...")
            actions = apply_profession(vault_root, profession)
            for action in actions:
                print(f"  {action}")

    print(f"  \033[32m✓\033[0m Database: {cfg.db_path}")

    # Run index if requested
    if run_index:
        print("\n  Indexing vault...")
        from ..watcher import full_index

        full_index(
            vault_root=vault_root,
            embed_url=cfg.embed_url,
            summarize_url=cfg.llm_url,
            skip_summary=True,
            skip_triples=True,
        )
        print("  \033[32m✓\033[0m Indexing complete")


def _find_project_root() -> Path:
    """Find the project root (where pyproject.toml lives)."""
    project_root = Path(__file__).resolve().parent.parent.parent
    if (project_root / "pyproject.toml").exists():
        return project_root
    fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
    if (fallback / "pyproject.toml").exists():
        return fallback
    return project_root


def _find_uv() -> str | None:
    """Find uv binary on PATH or at ~/.local/bin/uv."""
    import shutil

    uv = shutil.which("uv")
    if uv:
        return uv
    fallback = Path.home() / ".local" / "bin" / "uv"
    if fallback.exists():
        return str(fallback)
    return None


def _sync_dependencies(project_root: Path, uv_bin: str, mode: str) -> bool:
    """Run uv sync for the given mode. Returns True on success."""
    import subprocess

    sync_cmd = [uv_bin, "sync", "--project", str(project_root)]
    if mode == "full":
        sync_cmd += ["--extra", "full"]

    print(f"  Syncing dependencies ({mode} mode)...")
    try:
        result = subprocess.run(
            sync_cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"  \033[31m✗\033[0m uv sync failed:\n{result.stderr}")
            return False
        print(f"  \033[32m✓\033[0m Dependencies synced ({mode})")
        return True
    except FileNotFoundError:
        print(f"  \033[31m✗\033[0m Failed to run: {uv_bin}")
        return False


def _create_cli_wrapper(project_root: Path) -> None:
    """Create CLI wrapper scripts (bash on Unix, .cmd on Windows)."""
    import sys

    if sys.platform == "win32":
        wrapper_dir = Path.home() / "AppData" / "Local" / "neurostack" / "bin"
        wrapper_dir.mkdir(parents=True, exist_ok=True)
        content = f'@echo off\r\nuv run --project "{project_root}" python -m neurostack.cli %*\r\n'
        wrapper = wrapper_dir / "neurostack.cmd"
        wrapper.write_text(content)
        alias = wrapper_dir / "ns.cmd"
        alias.write_text(content)
        print(f"  \033[32m✓\033[0m CLI wrapper: {wrapper} (alias: ns.cmd)")
    else:
        wrapper = Path.home() / ".local" / "bin" / "neurostack"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "#!/usr/bin/env bash\n"
            f'exec uv run --project "{project_root}" python -m neurostack.cli "$@"\n'
        )
        wrapper.write_text(content)
        wrapper.chmod(0o755)
        alias = wrapper.parent / "ns"
        alias.write_text(content)
        alias.chmod(0o755)
        print(f"  \033[32m✓\033[0m CLI wrapper: {wrapper} (alias: ns)")


def _setup_ollama(pull_models, embed_model, llm_model, cfg):
    """Check Ollama, optionally install and pull models."""
    import shutil
    import subprocess

    ollama = shutil.which("ollama")
    if not ollama:
        print("  \033[33m!\033[0m Ollama not found")
        if sys.stdin.isatty() and _confirm(
            "Install Ollama now?", default=True,
        ):
            _install_ollama(subprocess)
            ollama = shutil.which("ollama")
            if not ollama:
                print("  \033[33m!\033[0m Ollama install"
                      " may need a shell restart")
        else:
            print("    Install later:"
                  " https://ollama.com/download")

    if ollama and pull_models:
        _pull_ollama_models(ollama, embed_model, llm_model, subprocess)

        cfg.embed_model = embed_model
        cfg.llm_model = llm_model
        from ..config import CONFIG_PATH
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            f'vault_root = "{cfg.vault_root}"\n'
            f'embed_url = "{cfg.embed_url}"\n'
            f'embed_model = "{embed_model}"\n'
            f'llm_url = "{cfg.llm_url}"\n'
            f'llm_model = "{llm_model}"\n'
        )
        print(f"  \033[32m✓\033[0m Config updated: {CONFIG_PATH}")


def _full_index_pipeline(vault_root, cfg):
    """Run complete indexing: full index + backfill + communities."""
    from ..watcher import (
        backfill_stale_summaries,
        backfill_summaries,
        backfill_triples,
        full_index,
    )

    print("\n  Indexing vault (full mode — this may take several minutes)...")
    full_index(
        vault_root=vault_root,
        embed_url=cfg.embed_url,
        summarize_url=cfg.llm_url,
        skip_summary=False,
        skip_triples=False,
    )
    print("  \033[32m✓\033[0m Index complete")

    print("  Backfilling summaries...")
    backfill_summaries(vault_root=vault_root, summarize_url=cfg.llm_url)
    backfill_stale_summaries(vault_root=vault_root, summarize_url=cfg.llm_url)
    print("  \033[32m✓\033[0m Summaries complete")

    print("  Backfilling triples...")
    backfill_triples(
        vault_root=vault_root,
        embed_url=cfg.embed_url,
        summarize_url=cfg.llm_url,
    )
    print("  \033[32m✓\033[0m Triples complete")

    print("  Building communities...")
    try:
        from ..attractor import detect_communities
        from ..community import summarize_all_communities

        n_coarse, n_fine = detect_communities()
        print(f"  Detected {n_coarse} coarse, {n_fine} fine communities.")
        print("  Generating community summaries...")
        summarize_all_communities(
            summarize_url=cfg.llm_url,
            embed_url=cfg.embed_url,
        )
        print("  \033[32m✓\033[0m Communities complete")
    except ImportError:
        print("  \033[33m!\033[0m Skipped communities (numpy required)")
    except Exception as e:
        print(f"  \033[33m!\033[0m Communities failed: {e}")


def cmd_init(args):
    """Initialize a new NeuroStack vault — one command to set up everything."""
    import platform
    import sqlite3
    import subprocess

    from ..professions import list_professions

    cfg = get_config()

    # Non-interactive mode: use flags directly
    if args.path or args.profession or not sys.stdin.isatty():
        vault_root = Path(args.path) if args.path else cfg.vault_root
        mode = getattr(args, "mode", None) or "lite"
        use_cloud = getattr(args, "cloud", False)

        if use_cloud:
            mode = "lite"
        cfg.mode = "cloud" if use_cloud else "local"
        if mode == "full":
            uv_bin = _find_uv()
            if uv_bin:
                _sync_dependencies(_find_project_root(), uv_bin, "full")

        _do_init(vault_root, cfg, profession_name=args.profession,
                 run_index=args.index)

        if mode == "full" and args.index:
            _full_index_pipeline(vault_root, cfg)

        print("\n  \033[32m✓\033[0m Setup complete.")
        print("    neurostack search 'query' # Search")
        print("    neurostack serve          # Start MCP server")
        return

    # ── Interactive setup wizard ──
    print("\n  \033[1m━━━ NeuroStack Setup ━━━\033[0m\n")

    # System info
    py_ver = platform.python_version()
    print(f"  Python:   {py_ver}")
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _t USING fts5(c)")
        conn.close()
        print("  FTS5:     available")
    except Exception:
        print("  \033[31mFTS5:     MISSING"
              " — SQLite compiled without FTS5\033[0m")
        sys.exit(1)

    uv_bin = _find_uv()
    if uv_bin:
        try:
            uv_ver = subprocess.run(
                ["uv", "--version"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            print(f"  uv:       {uv_ver}")
        except Exception:
            print(f"  uv:       {uv_bin}")
    else:
        print("  \033[31muv:       NOT FOUND\033[0m")
        print("  Install:  curl -LsSf"
              " https://astral.sh/uv/install.sh | sh")
        sys.exit(1)

    # ── Step 1: Cloud or Local? ──
    print()
    setup_choices = [
        ("cloud", "Cloud — Gemini indexes your vault, no GPU needed"),
        ("local", "Local — self-hosted with Ollama"),
    ]
    setup = _prompt(
        "How do you want to run NeuroStack?",
        default="cloud", choices=setup_choices,
    )
    use_cloud = setup == "cloud"

    mode = "lite"
    pull_models = False
    embed_model = cfg.embed_model
    llm_model = cfg.llm_model

    if use_cloud:
        mode = "lite"
    else:
        # ── Step 2: Lite or Full? ──
        _print_hardware_recommendation()
        print()
        mode_choices = [
            ("lite",
             "Lite — FTS5 search + graph, no ML (~130 MB)"),
            ("full",
             "Full — + embeddings, summaries, communities (~560 MB)"),
        ]
        mode = _prompt(
            "Installation mode",
            default="full", choices=mode_choices,
        )

        if mode == "full":
            print("\n  \033[1mOllama Models\033[0m")
            print("  Full mode uses Ollama for embeddings"
                  " and summaries.")
            pull_models = _confirm(
                "Pull Ollama models now?", default=True,
            )
            if pull_models:
                embed_model = _prompt(
                    "Embedding model", default=cfg.embed_model,
                )
                model_choices = [
                    ("phi3.5", "phi3.5 — MIT, fast, 3.8B"),
                    ("qwen3:8b", "qwen3:8b — Apache 2.0, strong"),
                    ("llama3.1:8b", "llama3.1:8b — Meta license"),
                    ("mistral:7b", "mistral:7b — Apache 2.0"),
                ]
                llm_model = _prompt(
                    "LLM model",
                    default=cfg.llm_model,
                    choices=model_choices,
                )

    # ── Step 3: Vault path ──
    print()
    print("  Your vault is the directory where your Markdown notes live.")
    print("  Point this to an existing notes folder,"
          " or a new path to start fresh.\n")
    vault_root = Path(_prompt(
        "\033[1mVault path\033[0m",
        default=str(cfg.vault_root),
    )).expanduser()

    # ── Step 4: Profession pack ──
    professions = list_professions()
    prof_choices = [("none", "None — start with base structure")]
    for p in professions:
        prof_choices.append((p.name, f"{p.name.title()} — {p.description}"))
    profession = _prompt("Profession pack", default="none", choices=prof_choices)

    # ── Step 5: LLM configuration (full mode only) ──
    embed_url = cfg.embed_url
    llm_url = cfg.llm_url
    llm_api_key = ""
    embed_api_key = ""

    if mode == "full":
        print("\n  \033[1mLLM Configuration\033[0m")
        print("  NeuroStack works with any OpenAI-compatible endpoint")
        print("  (Ollama, vLLM, Together AI, Groq, OpenRouter, etc.)\n")

        embed_url = _prompt("Embedding endpoint", default=cfg.embed_url)
        llm_url = _prompt("LLM endpoint", default=cfg.llm_url)

        is_local = any(
            h in llm_url for h in ("localhost", "127.0.0.1", "0.0.0.0")
        )
        if not is_local:
            print("\n  \033[1mAPI Authentication\033[0m")
            print("  Cloud providers require an API key.\n")
            llm_api_key = _prompt("LLM API key", default="")
            if embed_url != llm_url:
                embed_api_key = _prompt("Embedding API key", default="")
            else:
                embed_api_key = llm_api_key

    # ── Summary ──
    print("\n  \033[1m━━━ Plan ━━━\033[0m\n")
    print(f"  Mode:       {'cloud' if use_cloud else mode}")
    print(f"  Vault:      {vault_root}")
    print(f"  Profession: {profession}")
    if mode == "full":
        print(f"  Embed URL:  {embed_url}")
        print(f"  LLM URL:    {llm_url}")
        print(f"  LLM model:  {llm_model}")
        if pull_models:
            print(f"  Embed model: {embed_model}")
        auth_label = "yes" if (llm_api_key or embed_api_key) else "no"
        print(f"  API auth:   {auth_label}")
        print("  Index:      full (summaries + triples + communities)")
    elif use_cloud:
        print("  Index:      cloud (Gemini)")
    else:
        print("  Index:      lite (FTS5 only)")

    if not _confirm("\n  Proceed?", default=True):
        print("\n  Cancelled.")
        return

    # ── Execute ──
    print()
    project_root = _find_project_root()

    # 1. Sync dependencies
    if mode == "full":
        if not _sync_dependencies(project_root, uv_bin, "full"):
            sys.exit(1)
    _create_cli_wrapper(project_root)

    # 2. Ollama setup (full mode)
    if mode == "full":
        _setup_ollama(pull_models, embed_model, llm_model, cfg)

    # 3. Apply config + create vault structure
    cfg.mode = "cloud" if use_cloud else "local"
    cfg.vault_root = vault_root
    cfg.embed_url = embed_url
    cfg.llm_url = llm_url
    cfg.llm_model = llm_model
    cfg.llm_api_key = llm_api_key
    cfg.embed_api_key = embed_api_key

    if mode == "full":
        # Full mode: create vault, then run full index pipeline
        _do_init(vault_root, cfg, profession_name=profession, run_index=False)
        _full_index_pipeline(vault_root, cfg)
    else:
        # Lite/cloud: create vault with FTS5-only index
        _do_init(vault_root, cfg, profession_name=profession, run_index=True)

    # 4. Cloud path: login + push
    if use_cloud:
        print("\n  \033[1m━━━ Cloud Login ━━━\033[0m\n")
        _cmd_cloud_device_login()

        from ..cloud.config import load_cloud_config
        cloud_cfg = load_cloud_config()
        if cloud_cfg.cloud_api_key:
            print("\n  \033[32m✓\033[0m Logged in")
            from ..cloud.client import CloudClient
            tier = "Free"
            try:
                client = CloudClient(cloud_cfg)
                info = client.status()
                tier = (info.get("tier") or "free").capitalize()
            except Exception:
                pass
            print(f"  Plan:     {tier}")

            if sys.stdin.isatty() and _confirm(
                "\n  Push vault to cloud now?", default=True,
            ):
                print()
                cmd_cloud_push(args)
                print()
                print("  Check progress:"
                      " https://app.neurostack.sh")
            else:
                print("\n  Run later: neurostack cloud push")
        else:
            print("\n  \033[33m!\033[0m Login skipped.")
            print("  Run later: neurostack cloud login")

    # 5. PATH check
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", ""):
        print("\n  \033[33m!\033[0m Add to PATH:"
              ' export PATH="$HOME/.local/bin:$PATH"')

    # Done
    print("\n  \033[32m✓\033[0m Setup complete.\033[0m")
    print("    neurostack search 'query' # Search")
    print("    neurostack serve          # Start MCP server")
    print("    neurostack doctor         # Check health")
    print()


def cmd_scaffold(args):
    """Apply a profession pack to an existing vault."""
    from ..professions import apply_profession, get_profession, list_professions

    if args.list:
        professions = list_professions()
        print("Available profession packs:\n")
        for p in professions:
            print(f"  {p.name:<20} {p.description}")
        return

    if not args.profession:
        print("Usage: neurostack scaffold <profession>")
        print("       neurostack scaffold --list")
        sys.exit(1)

    profession = get_profession(args.profession)
    if not profession:
        names = ", ".join(p.name for p in list_professions())
        print(f"Unknown profession: {args.profession}")
        print(f"Available: {names}")
        sys.exit(1)

    cfg = get_config()
    vault_root = Path(args.vault) if hasattr(args, "vault") and args.vault else cfg.vault_root

    if not vault_root.exists():
        print(f"Vault not found at {vault_root}")
        print("Run 'neurostack init' first, or use --vault to specify the path")
        sys.exit(1)

    print(f"Applying '{profession.name}' pack to {vault_root}...")
    actions = apply_profession(vault_root, profession)
    for action in actions:
        print(action)
    if actions:
        print(f"\n{len(actions)} items added")
    else:
        print("Pack already applied (no new items)")


def cmd_onboard(args):
    """Onboard an existing directory of notes into a NeuroStack vault."""
    import shutil
    from datetime import date

    from ..chunker import parse_frontmatter
    from ..config import CONFIG_PATH

    cfg = get_config()
    target = Path(args.path).resolve()

    if not target.exists():
        print(f"Directory not found: {target}")
        sys.exit(1)
    if not target.is_dir():
        print(f"Not a directory: {target}")
        sys.exit(1)

    dry_run = args.dry_run
    prefix = "[dry-run] " if dry_run else ""

    # Stats
    notes_found = 0
    frontmatter_added = 0
    indexes_created = 0
    dirs_created = 0

    # 1. Scan for all markdown files
    md_files = sorted(target.rglob("*.md"))
    notes_found = len(md_files)

    print(f"Scanning {target}...")
    print(f"  Found {notes_found} markdown files\n")

    # 2. Generate metadata for notes without frontmatter
    #    Stored in SQLite note_metadata — vault files are NEVER modified.
    #    Use --write-frontmatter to opt in to file modification.
    today = date.today().isoformat()
    write_fm = getattr(args, "write_frontmatter", False)
    # Files to skip — NeuroStack scaffolding, not user notes
    skip_names = {"index.md", "AGENTS.md", "CLAUDE.md"}
    skip_dirs = {"templates", ".obsidian", ".claude"}

    # Collect metadata for SQLite insertion after indexing
    pending_metadata: list[tuple] = []

    for md in md_files:
        if md.name in skip_names:
            continue
        rel = md.relative_to(target)
        if any(part in skip_dirs for part in rel.parts):
            continue
        content = md.read_text(encoding="utf-8", errors="replace")
        fm, _ = parse_frontmatter(content)
        if not fm:
            # Derive tags from parent dir name
            parent_tag = rel.parent.name if rel.parent.name else ""
            tags_list = [parent_tag] if parent_tag else []

            # Guess note type from location
            parent_lower = rel.parent.name.lower() if rel.parent.name else ""
            if parent_lower in ("literature", "sources", "references"):
                note_type = "literature"
            elif parent_lower in (
                "projects", "work", "home",
            ):
                note_type = "project"
            elif parent_lower in ("calendar", "daily", "journal"):
                note_type = "daily"
            else:
                note_type = "permanent"

            if write_fm and not dry_run:
                tags_str = f"[{parent_tag}]" if parent_tag else "[]"
                new_fm = (
                    f"---\ndate: {today}\ntags: {tags_str}\n"
                    f"type: {note_type}\nstatus: active\n---\n\n"
                )
                md.write_text(
                    new_fm + content, encoding="utf-8",
                )
                print(f"  {prefix}+ frontmatter → {rel}")
            else:
                pending_metadata.append((
                    str(rel), "active",
                    json.dumps(tags_list),
                    note_type, today,
                ))
                print(f"  {prefix}+ metadata → {rel}")
            frontmatter_added += 1

    # 3. Generate index.md for directories that have .md files
    dirs_with_notes: dict[Path, list[Path]] = {}
    for md in md_files:
        if md.name in skip_names:
            continue
        rel_check = md.relative_to(target)
        if any(part in skip_dirs for part in rel_check.parts):
            continue
        parent = md.parent
        if parent not in dirs_with_notes:
            dirs_with_notes[parent] = []
        dirs_with_notes[parent].append(md)

    for dir_path, notes in sorted(dirs_with_notes.items()):
        idx = dir_path / "index.md"
        if idx.exists():
            continue
        rel_dir = dir_path.relative_to(target)
        label = dir_path.name.replace("-", " ").replace("_", " ").title()
        lines = [f"# {label}\n"]
        for note in sorted(notes, key=lambda p: p.stem):
            # Try to extract title from first heading
            desc = _extract_first_heading(note)
            if desc:
                lines.append(f"- [[{note.stem}]] — {desc}")
            else:
                display = note.stem.replace("-", " ").replace(
                    "_", " ",
                ).title()
                lines.append(f"- [[{note.stem}]] — {display}")
        content = "\n".join(lines) + "\n"
        if not dry_run:
            idx.write_text(content, encoding="utf-8")
        print(f"  {prefix}+ index.md → {rel_dir}/ ({len(notes)} entries)")
        indexes_created += 1

    # 4. Add missing NeuroStack structural dirs
    structural = [
        "templates", "meta", "inbox", "archive", "calendar",
    ]
    for d in structural:
        p = target / d
        if not p.exists():
            if not dry_run:
                p.mkdir(parents=True)
                idx = p / "index.md"
                label = d.replace("-", " ").title()
                idx.write_text(f"# {label}\n\n")
            print(f"  {prefix}+ {d}/")
            dirs_created += 1

    # 5. Copy AGENTS.md and base templates if missing
    base_template = _get_vault_template_dir()
    if base_template is not None:
        src_agents = base_template / "AGENTS.md"
        dst_agents = target / "AGENTS.md"
        if src_agents.exists() and not dst_agents.exists():
            if not dry_run:
                shutil.copy2(src_agents, dst_agents)
            print(f"  {prefix}+ AGENTS.md")

        src_templates = base_template / "templates"
        dst_templates = target / "templates"
        if src_templates.exists():
            dst_templates.mkdir(parents=True, exist_ok=True)
            for tmpl in sorted(src_templates.glob("*.md")):
                dst = dst_templates / tmpl.name
                if not dst.exists():
                    if not dry_run:
                        shutil.copy2(tmpl, dst)
                    print(f"  {prefix}+ templates/{tmpl.name}")

    # 6. Create config pointing to this vault
    if not dry_run and not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            f'vault_root = "{target}"\n'
            f'embed_url = "{cfg.embed_url}"\n'
            f'llm_url = "{cfg.llm_url}"\n'
            f'llm_model = "{cfg.llm_model}"\n'
        )
        print(f"  Config written to {CONFIG_PATH}")

    # Summary
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Onboard complete:")
    print(f"  {notes_found} notes found")
    print(f"  {frontmatter_added} frontmatter blocks added")
    print(f"  {indexes_created} index files generated")
    print(f"  {dirs_created} structural dirs created")

    # 7. Apply profession pack if specified
    if args.profession and not dry_run:
        from ..professions import apply_profession, get_profession, list_professions

        profession = get_profession(args.profession)
        if not profession:
            names = ", ".join(p.name for p in list_professions())
            print(f"\nUnknown profession: {args.profession}")
            print(f"Available: {names}")
        else:
            print(f"\nApplying '{profession.name}' profession pack...")
            actions = apply_profession(target, profession)
            for action in actions:
                print(action)
            if actions:
                print(f"  {len(actions)} items added")

    # 8. Index the vault unless skipped or dry run
    if not dry_run and not args.no_index:
        print("\nIndexing vault...")
        from ..schema import DB_PATH, get_db
        from ..watcher import full_index

        full_index(
            vault_root=target,
            embed_url=cfg.embed_url,
            summarize_url=cfg.llm_url,
            skip_summary=False,
            skip_triples=False,
        )
        db_path = Path(os.environ.get("NEUROSTACK_DB_PATH", DB_PATH))
        conn = get_db(db_path)

        # Insert pending metadata for notes without frontmatter
        if pending_metadata:
            conn.executemany(
                "INSERT OR IGNORE INTO note_metadata"
                " (note_path, status, tags, note_type, date_added)"
                " VALUES (?, ?, ?, ?, ?)",
                pending_metadata,
            )
            conn.commit()

        notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = conn.execute(
            "SELECT COUNT(*) FROM chunks",
        ).fetchone()[0]
        edges = conn.execute(
            "SELECT COUNT(*) FROM graph_edges",
        ).fetchone()[0]
        print(
            f"Indexed {notes} notes, {chunks} chunks, {edges} graph edges.",
        )

        print("\nNext steps:")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
    elif not dry_run:
        print("\nNext steps:")
        print("  neurostack index          # Index your vault")
        print("  neurostack search 'query' # Search")
        print("  neurostack doctor         # Check health")
    else:
        print(
            "\nRun without --dry-run to apply changes.",
        )


def _extract_first_heading(path: Path) -> str:
    """Extract the first markdown heading from a file, or empty string."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# ") and not line.startswith("# {"):
                    return line.lstrip("# ").strip()
    except OSError:
        pass
    return ""


def _install_ollama(subprocess):
    """Attempt to install Ollama via the official installer."""
    import platform as _plat

    system = _plat.system()
    if system == "Linux":
        print("  Installing Ollama (Linux)...")
        proc = subprocess.run(
            ["bash", "-c",
             "curl -fsSL https://ollama.com/install.sh | sh"],
            timeout=120,
        )
        if proc.returncode == 0:
            print("  \033[32m✓\033[0m Ollama installed")
        else:
            print("  \033[31m✗\033[0m Ollama install failed")
            print(
                "    Try manually:"
                " https://ollama.com/download"
            )
    elif system == "Darwin":
        print(
            "  \033[33m!\033[0m On macOS, download Ollama from:"
            " https://ollama.com/download"
        )
    else:
        print(
            "  \033[33m!\033[0m Install Ollama from:"
            " https://ollama.com/download"
        )


def _get_ollama_models(ollama_bin, subprocess):
    """Return set of locally available Ollama model names."""
    try:
        proc = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return set()
        models = set()
        for line in proc.stdout.strip().splitlines()[1:]:
            name = line.split()[0] if line.split() else ""
            if name:
                models.add(name)
                # Also add without :latest tag
                if ":" in name:
                    models.add(name.split(":")[0])
        return models
    except Exception:
        return set()


def _pull_ollama_models(ollama_bin, embed_model, llm_model, subprocess):
    """Pull Ollama models, skipping any already available."""
    available = _get_ollama_models(ollama_bin, subprocess)

    for model_name in (embed_model, llm_model):
        base = model_name.split(":")[0] if ":" in model_name else model_name
        if model_name in available or base in available:
            print(f"  \033[32m✓\033[0m {model_name} already available")
            continue
        print(f"  Pulling {model_name}...")
        try:
            proc = subprocess.run(
                [ollama_bin, "pull", model_name],
                timeout=600,
            )
            if proc.returncode == 0:
                print(f"  \033[32m✓\033[0m {model_name} ready")
            else:
                print(
                    f"  \033[33m!\033[0m Failed to pull"
                    f" {model_name}"
                )
        except subprocess.TimeoutExpired:
            print(
                f"  \033[33m!\033[0m Timeout pulling {model_name}"
                f" — try: ollama pull {model_name}"
            )


def cmd_skills(args):
    """Manage agent skill files (.md slash commands)."""
    import shutil

    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    subcmd = getattr(args, "skills_command", None)

    if subcmd == "list":
        if not skills_dir.exists():
            print("No skills directory found.")
            return
        files = sorted(skills_dir.glob("*.md"))
        if not files:
            print("No skill files found.")
            return
        for f in files:
            print(f"  {f.stem}")
        print(f"\n{len(files)} skill(s) available.")
        return

    if subcmd == "install":
        if not skills_dir.exists():
            print("No skills directory found in package.")
            sys.exit(1)

        provider = getattr(args, "provider", "claude")
        provider_paths = {
            "claude": Path.home() / ".claude" / "commands",
            "codex": Path.home() / ".codex" / "commands",
            "gemini": Path.home() / ".gemini" / "commands",
        }
        target = provider_paths.get(provider)
        if not target:
            print(
                f"Unknown provider: {provider}. "
                f"Supported: {', '.join(provider_paths)}"
            )
            sys.exit(1)

        target.mkdir(parents=True, exist_ok=True)

        files = sorted(skills_dir.glob("*.md"))
        if not files:
            print("No skill files found.")
            return

        for f in files:
            dest = target / f.name
            shutil.copy2(f, dest)
            print(f"  Installed {f.name} -> {dest}")
        print(
            f"\n{len(files)} skill(s) installed"
            f" to {target} ({provider})"
        )
        return

    # No subcommand - show help
    print("Usage: neurostack skills {install,list}")
    print("  install [provider]  Install skills"
          " (claude, codex, gemini)")
    print("  list                List available skills")


def cmd_update(args):
    """Pull latest source from GitHub and re-sync dependencies."""
    import shutil
    import subprocess
    import tarfile
    import tempfile
    import urllib.request

    TARBALL_URL = "https://github.com/raphasouthall/neurostack/archive/refs/heads/main.tar.gz"

    project_root = Path(__file__).resolve().parent.parent.parent
    if not (project_root / "pyproject.toml").exists():
        fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
        if (fallback / "pyproject.toml").exists():
            project_root = fallback
        else:
            print("  \033[31m✗\033[0m Cannot find project root")
            sys.exit(1)

    print(f"  Updating from {project_root}...\n")
    print(f"  Current version: {__version__}")

    is_git_repo = (project_root / ".git").exists()
    git = shutil.which("git")

    if is_git_repo and git:
        # Check for stale pre-rewrite history (sensitive refs removed 2026-03-20).
        # If old root commit exists, re-clone to drop stale objects.
        old_root_check = subprocess.run(
            ["git", "cat-file", "-t", "e146d12"],
            cwd=project_root, capture_output=True, text=True,
        )
        if old_root_check.returncode == 0:
            print("  \033[33m!\033[0m Outdated history detected — re-cloning for clean history...")
            repo_url = "https://github.com/raphasouthall/neurostack.git"
            parent = project_root.parent
            import tempfile
            tmp = Path(tempfile.mkdtemp(dir=parent))
            subprocess.run(["git", "clone", repo_url, str(tmp / "repo")],
                           capture_output=True, text=True, timeout=120)
            # Swap directories
            old_dir = project_root.with_name(project_root.name + ".old")
            project_root.rename(old_dir)
            (tmp / "repo").rename(project_root)
            shutil.rmtree(old_dir, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)
            print("  \033[32m✓\033[0m Re-cloned with clean history")
        else:
            # Normal git pull
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=project_root, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                print(f"  \033[31m✗\033[0m git pull failed:\n{result.stderr}")
                sys.exit(1)
            pulled = result.stdout.strip()
            if "Already up to date" in pulled:
                print("  \033[32m✓\033[0m Already up to date")
            else:
                print(f"  \033[32m✓\033[0m Pulled: {pulled.splitlines()[-1]}")
    else:
        # Tarball-based install — re-download from GitHub
        print("  Downloading latest source...")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_path = tmp.name
                urllib.request.urlretrieve(TARBALL_URL, tmp_path)

            # Extract over existing install (strip top-level dir)
            with tarfile.open(tmp_path, "r:gz") as tar:
                members = tar.getmembers()
                # Strip the first path component (neurostack-main/)
                for member in members:
                    parts = Path(member.name).parts
                    if len(parts) > 1:
                        member.name = str(Path(*parts[1:]))
                        tar.extract(member, project_root)

            Path(tmp_path).unlink(missing_ok=True)
            print("  \033[32m✓\033[0m Source updated")
        except Exception as e:
            print(f"  \033[31m✗\033[0m Download failed: {e}")
            sys.exit(1)

    # Detect current mode
    mode = "lite"
    try:
        import numpy  # noqa: F401
        mode = "full"
    except ImportError:
        pass

    # uv sync
    uv = shutil.which("uv")
    if not uv:
        uv_fallback = Path.home() / ".local" / "bin" / "uv"
        if uv_fallback.exists():
            uv = str(uv_fallback)
        else:
            print("  \033[31m✗\033[0m uv not found")
            sys.exit(1)

    sync_cmd = [uv, "sync", "--project", str(project_root)]
    if mode == "full":
        sync_cmd += ["--extra", "full"]

    print(f"  Syncing dependencies ({mode} mode)...")
    result = subprocess.run(
        sync_cmd, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  \033[31m✗\033[0m uv sync failed:\n{result.stderr}")
        sys.exit(1)
    print("  \033[32m✓\033[0m Dependencies synced")

    # Show new version
    try:
        new_ver = subprocess.run(
            [uv, "run", "--project", str(project_root),
             "python", "-c",
             "from neurostack import __version__; print(__version__)"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if new_ver and new_ver != __version__:
            print(f"  \033[32m✓\033[0m Updated: {__version__} -> {new_ver}")
        else:
            print(f"  Version: {new_ver or __version__}")
    except Exception:
        pass

    print("\n  Done.")


def cmd_install(args):
    """Streamlined installation: local or cloud, deps, and setup.

    DEPRECATED: Use 'neurostack init' instead, which combines installation
    and vault setup into a single command.
    """
    print("  \033[33mNote:\033[0m 'neurostack install' is deprecated."
          " Use 'neurostack init' instead.\n")
    import platform
    import shutil
    import sqlite3
    import subprocess

    cfg = get_config()

    # ── Non-interactive mode ──
    if args.mode or not sys.stdin.isatty():
        mode = args.mode or "lite"
        pull_models = args.pull_models
        embed_model = args.embed_model or cfg.embed_model
        llm_model = args.llm_model or cfg.llm_model
        use_cloud = False
    else:
        # ── Interactive wizard ──
        print("\n  \033[1m━━━ NeuroStack Install ━━━\033[0m\n")

        # 1. Show system info
        py_ver = platform.python_version()
        print(f"  Python:   {py_ver}")
        try:
            conn = sqlite3.connect(":memory:")
            conn.execute(
                "CREATE VIRTUAL TABLE _t USING fts5(c)"
            )
            conn.close()
            print("  FTS5:     available")
        except Exception:
            print(
                "  \033[31mFTS5:     MISSING"
                " — SQLite compiled without FTS5\033[0m"
            )
            sys.exit(1)

        uv_path = shutil.which("uv")
        if uv_path:
            try:
                uv_ver = subprocess.run(
                    ["uv", "--version"],
                    capture_output=True, text=True, timeout=5,
                ).stdout.strip()
                print(f"  uv:       {uv_ver}")
            except Exception:
                print(f"  uv:       {uv_path}")
        else:
            print("  \033[31muv:       NOT FOUND\033[0m")
            print(
                "  Install:  curl -LsSf"
                " https://astral.sh/uv/install.sh | sh"
            )
            sys.exit(1)

        # 2. Local or Cloud?
        setup_choices = [
            ("cloud", "Cloud — Gemini indexes your vault, no GPU needed"),
            ("local", "Local — self-hosted with Ollama (requires GPU)"),
        ]
        setup = _prompt(
            "How do you want to run NeuroStack?",
            default="cloud", choices=setup_choices,
        )
        use_cloud = setup == "cloud"

        if use_cloud:
            # ── Cloud path: lite deps, then login ──
            mode = "lite"
            pull_models = False
            embed_model = cfg.embed_model
            llm_model = cfg.llm_model
        else:
            # ── Local path: existing flow ──
            # Detect current mode
            current_mode = "lite"
            try:
                import numpy  # noqa: F401
                current_mode = "full"
            except ImportError:
                pass
            print(f"  Current:  {current_mode} mode\n")

            mode_choices = [
                ("lite",
                 "Lite — FTS5 search + graph, no ML (~130 MB)"),
                ("full",
                 "Full — + embeddings, summaries, communities (~560 MB)"),
            ]
            mode = _prompt(
                "Installation mode",
                default=current_mode, choices=mode_choices,
            )

            pull_models = False
            embed_model = cfg.embed_model
            llm_model = cfg.llm_model
            if mode == "full":
                print("\n  \033[1mOllama Models\033[0m")
                print(
                    "  Full mode uses Ollama for embeddings"
                    " and summaries."
                )
                pull_models = _confirm(
                    "Pull Ollama models now?", default=True,
                )
                if pull_models:
                    embed_model = _prompt(
                        "Embedding model", default=cfg.embed_model,
                    )
                    model_choices = [
                        ("phi3.5",
                         "phi3.5 — MIT, fast, 3.8B"),
                        ("qwen3:8b",
                         "qwen3:8b — Apache 2.0, strong"),
                        ("llama3.1:8b",
                         "llama3.1:8b — Meta license"),
                        ("mistral:7b",
                         "mistral:7b — Apache 2.0"),
                    ]
                    llm_model = _prompt(
                        "LLM model",
                        default=cfg.llm_model,
                        choices=model_choices,
                    )

            print("\n  \033[1m━━━ Plan ━━━\033[0m\n")
            print(f"  Mode:     {mode}")
            if pull_models:
                print(f"  Embed:    ollama pull {embed_model}")
                print(f"  LLM:      ollama pull {llm_model}")
            else:
                print("  Models:   skip")
            if not _confirm("\n  Proceed?", default=True):
                print("\n  Cancelled.")
                return

    # ── Execute installation ──
    print()

    # Find project root (where pyproject.toml lives)
    project_root = Path(__file__).resolve().parent.parent.parent
    if not (project_root / "pyproject.toml").exists():
        # Fallback: check standard install location
        fallback = Path.home() / ".local" / "share" / "neurostack" / "repo"
        if (fallback / "pyproject.toml").exists():
            project_root = fallback
        else:
            print("  \033[31m✗\033[0m Cannot find project root (pyproject.toml)")
            sys.exit(1)

    # 1. uv sync — find uv on PATH or at ~/.local/bin/uv
    uv_bin = shutil.which("uv")
    if not uv_bin:
        fallback_uv = Path.home() / ".local" / "bin" / "uv"
        if fallback_uv.exists():
            uv_bin = str(fallback_uv)
    if not uv_bin:
        print("  \033[31m✗\033[0m uv not found.")
        print("  Install: curl -LsSf https://astral.sh/uv/install.sh | sh")
        sys.exit(1)

    sync_cmd = [uv_bin, "sync", "--project", str(project_root)]
    if mode == "full":
        sync_cmd += ["--extra", "full"]

    print(f"  Syncing dependencies ({mode} mode)...")
    try:
        result = subprocess.run(
            sync_cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            print(f"  \033[31m✗\033[0m uv sync failed:\n{result.stderr}")
            sys.exit(1)
        print(f"  \033[32m✓\033[0m Dependencies synced ({mode})")
    except FileNotFoundError:
        print(f"  \033[31m✗\033[0m Failed to run: {uv_bin}")
        sys.exit(1)

    # 2. Create/update wrapper script
    wrapper = Path.home() / ".local" / "bin" / "neurostack"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper_content = (
        "#!/usr/bin/env bash\n"
        f'exec uv run --project "{project_root}" python -m neurostack.cli "$@"\n'
    )
    wrapper.write_text(wrapper_content)
    wrapper.chmod(0o755)
    # Create ns alias
    alias = wrapper.parent / "ns"
    alias.write_text(wrapper_content)
    alias.chmod(0o755)
    print(f"  \033[32m✓\033[0m CLI wrapper: {wrapper} (alias: ns)")

    # 3. Ollama setup (full mode)
    if pull_models or (mode == "full" and not pull_models
                       and not args.mode):
        # Check if Ollama is installed
        ollama = shutil.which("ollama")
        if not ollama:
            if mode == "full":
                print("  \033[33m!\033[0m Ollama not found")
                if sys.stdin.isatty() and _confirm(
                    "Install Ollama now?", default=True
                ):
                    _install_ollama(subprocess)
                    ollama = shutil.which("ollama")
                    if not ollama:
                        print(
                            "  \033[33m!\033[0m Ollama install"
                            " may need a shell restart"
                        )
                        print(
                            "    Then run:"
                            " neurostack install --pull-models"
                        )
                else:
                    print(
                        "    Install later:"
                        " https://ollama.com/download"
                    )

        if ollama and pull_models:
            _pull_ollama_models(
                ollama, embed_model, llm_model, subprocess
            )

            # Update config with chosen models
            cfg.embed_model = embed_model
            cfg.llm_model = llm_model
            from ..config import CONFIG_PATH
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                f'vault_root = "{cfg.vault_root}"\n'
                f'embed_url = "{cfg.embed_url}"\n'
                f'embed_model = "{embed_model}"\n'
                f'llm_url = "{cfg.llm_url}"\n'
                f'llm_model = "{llm_model}"\n'
            )
            print(f"  \033[32m✓\033[0m Config updated: {CONFIG_PATH}")

    # 4. PATH check
    local_bin = str(Path.home() / ".local" / "bin")
    if local_bin not in os.environ.get("PATH", ""):
        print("\n  \033[33m!\033[0m Add to PATH:"
              " export PATH=\"$HOME/.local/bin:$PATH\"")

    # 5. Cloud setup (if cloud path was chosen)
    if use_cloud:
        print("\n  \033[32m✓\033[0m Dependencies installed (lite)")
        print("\n  \033[1m━━━ Cloud Login ━━━\033[0m\n")
        _cmd_cloud_device_login()

        # Check if login succeeded
        from ..cloud.config import load_cloud_config
        cloud_cfg = load_cloud_config()
        if cloud_cfg.cloud_api_key:
            print("\n  \033[32m✓\033[0m Logged in")

            # Fetch tier
            from ..cloud.client import CloudClient
            tier = "Free"
            try:
                client = CloudClient(cloud_cfg)
                info = client.status()
                tier = (info.get("tier") or "free").capitalize()
            except Exception:
                pass
            print(f"  Plan:     {tier}")
            print("  Dashboard:"
                  " https://app.neurostack.sh")

            # Auto-run init — set defaults for init args
            print("\n  \033[1m━━━ Vault Setup ━━━\033[0m\n")
            args.path = None
            args.profession = None
            args.index = True
            cmd_init(args)
        else:
            print("\n  \033[33m!\033[0m Login skipped")
            print("\n  \033[32mInstalled!\033[0m (lite)"
                  " Run this next:")
            print("    neurostack init"
                  "              # Set up your vault")
            print("    neurostack cloud login"
                  "       # Sign in later")
            print()
        return

    # Summary (local path)
    print(f"\n  \033[32mInstalled!\033[0m ({mode} mode)")
    print()
    print("  Next steps:")
    print("    neurostack init          # Set up vault")
    print("    neurostack doctor        # Verify setup")
    print()


def cmd_uninstall(args):
    """Remove NeuroStack data, config, CLI wrapper, and npm package."""
    import shutil
    import subprocess

    cfg = get_config()
    install_dir = Path.home() / ".local" / "share" / "neurostack"
    config_dir = Path.home() / ".config" / "neurostack"
    wrapper = Path.home() / ".local" / "bin" / "neurostack"

    if not args.yes and sys.stdin.isatty():
        print("\n  \033[1m━━━ NeuroStack Uninstall ━━━\033[0m\n")
        print("  This will remove:")
        print(f"    Data:     {install_dir}")
        print(f"    Config:   {config_dir}")
        if not args.keep_db:
            print(f"    Database: {cfg.db_path}")
        if wrapper.exists():
            print(f"    CLI:      {wrapper}")
        print("    npm:      neurostack (global)")
        print()
        print("  \033[33m!\033[0m Your vault will NOT be touched.")
        if not _confirm("  Proceed with uninstall?", default=False):
            print("\n  Cancelled.")
            return

    print("\n  \033[1mUninstalling NeuroStack\033[0m\n")

    # Remove database files
    if not args.keep_db:
        for db in (cfg.db_path, cfg.session_db):
            for suffix in ("", "-wal", "-shm"):
                f = Path(str(db) + suffix)
                if f.exists():
                    f.unlink()
        print("  \033[36m▸\033[0m Removed databases")

    # Remove entire data directory (repo, memories, harvest state, etc.)
    if install_dir.exists():
        shutil.rmtree(install_dir)
        print(f"  \033[36m▸\033[0m Removed data: {install_dir}")

    # Remove config directory
    if config_dir.exists():
        shutil.rmtree(config_dir)
        print(f"  \033[36m▸\033[0m Removed config: {config_dir}")

    # Remove CLI wrapper and alias
    for p in (wrapper, wrapper.parent / "ns"):
        if p.exists():
            p.unlink()
            print(f"  \033[36m▸\033[0m Removed: {p}")

    # Remove npm package
    npm = shutil.which("npm")
    if npm:
        try:
            result = subprocess.run(
                [npm, "uninstall", "-g", "neurostack"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                print("  \033[36m▸\033[0m Removed npm package")
            else:
                print("  \033[33m▸\033[0m npm uninstall failed"
                      " (may not be installed via npm)")
        except Exception:
            print("  \033[33m▸\033[0m Could not run npm uninstall")

    print()
    print("  \033[32m✓ NeuroStack fully uninstalled.\033[0m")
    print()


def cmd_doctor(args):
    """Validate all NeuroStack subsystems."""

    cfg = get_config()
    checks = []

    # Check vault exists
    if cfg.vault_root.exists():
        note_count = len(list(cfg.vault_root.rglob("*.md")))
        checks.append(("Vault", "OK", f"{cfg.vault_root} ({note_count} .md files)"))
    else:
        checks.append(("Vault", "WARN", f"{cfg.vault_root} not found. Run: neurostack init"))

    # Check database
    if cfg.db_path.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(cfg.db_path))
            notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            conn.close()
            checks.append(("Database", "OK", f"{cfg.db_path} ({notes} indexed notes)"))
        except Exception as e:
            checks.append(("Database", "ERROR", str(e)))
    else:
        checks.append(("Database", "WARN", "Run: neurostack index"))

    # Check Python version
    import platform
    py_ver = platform.python_version()
    checks.append(("Python", "OK", py_ver))

    # Check FTS5
    import sqlite3
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        conn.close()
        checks.append(("FTS5", "OK", "Available"))
    except Exception:
        checks.append(("FTS5", "ERROR", "SQLite compiled without FTS5 support"))

    # Check for stale embed_url port in config file
    config_path = Path.home() / ".config" / "neurostack" / "config.toml"
    if config_path.exists():
        config_text = config_path.read_text()
        if "11435" in config_text:
            checks.append((
                "Config", "WARN",
                f"embed_url contains port 11435 (old default)."
                f" Ollama uses 11434."
                f"\n         Fix: edit {config_path}"
                f" and change 11435 → 11434"
            ))

    # Check Ollama embedding endpoint
    try:
        import httpx
        r = httpx.get(f"{cfg.embed_url}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_embed = any(cfg.embed_model in m for m in models)
            status = "OK" if has_embed else "WARN"
            if models:
                detail = (
                    f"{cfg.embed_url}"
                    f" ({', '.join(models[:3])})"
                )
            else:
                detail = f"{cfg.embed_url} (no models)"
            if not has_embed:
                detail += (
                    f"\n         {cfg.embed_model}"
                    " not found. Pull:"
                    f" ollama pull {cfg.embed_model}"
                )
            checks.append(("Embeddings", status, detail))
        else:
            checks.append((
                "Embeddings", "WARN",
                f"{cfg.embed_url} returned"
                f" {r.status_code} (lite mode still works)",
            ))
    except Exception:
        checks.append((
            "Embeddings", "WARN",
            f"{cfg.embed_url} unreachable"
            " (lite mode still works)",
        ))

    # Check Ollama LLM endpoint
    try:
        import httpx
        r = httpx.get(f"{cfg.llm_url}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_llm = any(cfg.llm_model in m for m in models)
            status = "OK" if has_llm else "WARN"
            detail = (
                f"{cfg.llm_url}"
                f" ({', '.join(models[:3])})"
            )
            if not has_llm:
                detail += (
                    f"\n         {cfg.llm_model}"
                    " not found. Pull:"
                    f" ollama pull {cfg.llm_model}"
                )
            checks.append(("LLM", status, detail))
        else:
            checks.append((
                "LLM", "WARN",
                f"{cfg.llm_url} returned {r.status_code}",
            ))
    except Exception:
        checks.append((
            "LLM", "WARN",
            f"{cfg.llm_url} unreachable"
            " (search still works, summaries disabled)",
        ))

    # Check optional deps
    try:
        import numpy
        checks.append(("numpy", "OK", numpy.__version__))
    except ImportError:
        checks.append((
            "numpy", "SKIP",
            "Not installed (install with:"
            " pip install neurostack[full])",
        ))

    # Print results
    if args.json:
        output = {
            "checks": [
                {"name": name, "status": status, "detail": detail}
                for name, status, detail in checks
            ],
            "errors": sum(1 for _, s, _ in checks if s == "ERROR"),
            "warnings": sum(1 for _, s, _ in checks if s == "WARN"),
        }
        print(json.dumps(output, indent=2, default=str))
        if output["errors"]:
            sys.exit(1)
        if args.strict and output["warnings"]:
            sys.exit(1)
        return

    print("\nNeuroStack Doctor\n" + "=" * 40)
    for name, status, detail in checks:
        icon = {"OK": "+", "WARN": "!", "ERROR": "X", "SKIP": "-", "MISSING": "X"}[status]
        print(f"  [{icon}] {name}: {detail}")

    errors = sum(1 for _, s, _ in checks if s == "ERROR")
    warns = sum(1 for _, s, _ in checks if s == "WARN")
    if errors:
        print(f"\n{errors} error(s) found. Fix them before proceeding.")
        sys.exit(1)
    elif warns:
        print(f"\n{warns} warning(s). Lite mode works. Install optional deps for full features.")
        if args.strict:
            sys.exit(1)
    else:
        print("\nAll systems operational.")


def cmd_demo(args):
    """Run an interactive demo with the sample vault."""
    import shutil
    import tempfile

    from ..chunker import parse_note
    from ..graph import build_graph, compute_pagerank, get_neighborhood
    from ..schema import SCHEMA_SQL, SCHEMA_VERSION
    from ..search import fts_search

    # Copy sample vault to a temp directory
    sample_src = _get_vault_template_dir()
    if sample_src is None:
        print("Error: vault-template not found. "
              "Please reinstall neurostack.")
        sys.exit(1)

    tmpdir = Path(tempfile.mkdtemp(prefix="neurostack-demo-"))
    vault = tmpdir / "demo-vault"
    shutil.copytree(sample_src, vault)
    db_path = tmpdir / "demo.db"

    print("=" * 60)
    print("  NeuroStack Demo")
    print("=" * 60)
    print()
    print(f"  Sample vault: {vault}")
    print(f"  Database: {db_path}")
    print()

    try:
        # Create DB directly (bypass module-level singletons)
        import hashlib
        import sqlite3
        from datetime import datetime, timezone

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO schema_version VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()

        # Step 1: Index
        print("--- Step 1: Indexing sample vault (FTS5 lite mode) ---")
        print()

        md_files = sorted(vault.rglob("*.md"))
        md_files = [
            f for f in md_files
            if ".git" not in f.parts
            and f.name not in ("AGENTS.md", "CLAUDE.md")
        ]

        now = datetime.now(timezone.utc).isoformat()
        for path in md_files:
            parsed = parse_note(path, vault)
            fm_json = json.dumps(parsed.frontmatter, default=str)
            conn.execute(
                "INSERT OR REPLACE INTO notes "
                "(path, title, frontmatter, content_hash, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (parsed.path, parsed.title, fm_json,
                 parsed.content_hash, now),
            )
            for chunk in parsed.chunks:
                conn.execute(
                    "INSERT INTO chunks (note_path, heading_path, "
                    "content, content_hash, position) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (parsed.path, chunk.heading_path, chunk.content,
                     hashlib.sha256(
                         chunk.content.encode()
                     ).hexdigest()[:16],
                     chunk.position),
                )
        conn.commit()

        notes = conn.execute(
            "SELECT COUNT(*) as c FROM notes"
        ).fetchone()["c"]
        chunks = conn.execute(
            "SELECT COUNT(*) as c FROM chunks"
        ).fetchone()["c"]
        print(f"  Indexed {notes} notes, {chunks} chunks")

        # Step 2: Search
        print()
        print("--- Step 2: FTS5 search for 'prediction errors' ---")
        print()
        results = fts_search(conn, "prediction errors", limit=3)
        for r in results:
            snippet = r["content"][:120].replace("\n", " ")
            print(f"  {r['note_path']}")
            print(f"    {snippet}...")
            print()

        # Step 3: Graph
        print(
            "--- Step 3: Wiki-link graph for "
            "'memory-consolidation' ---"
        )
        print()
        build_graph(conn, vault)
        compute_pagerank(conn)
        result = get_neighborhood(
            "research/memory-consolidation.md", depth=1, conn=conn
        )
        if result:
            print(f"  Center: {result.center.title} "
                  f"(PageRank: {result.center.pagerank:.4f})")
            print(f"  Neighbors ({len(result.neighbors)}):")
            for n in result.neighbors:
                print(f"    - {n.title} "
                      f"(PageRank: {n.pagerank:.4f})")

        # Step 4: Stats
        print()
        print("--- Step 4: Index stats ---")
        print()
        edges = conn.execute(
            "SELECT COUNT(*) as c FROM graph_edges"
        ).fetchone()["c"]
        print(f"  Notes: {notes}")
        print(f"  Chunks: {chunks}")
        print(f"  Wiki-link edges: {edges}")

        conn.close()

        print()
        print("=" * 60)
        print("  Demo complete!")
        print()
        print("  To use with your own vault:")
        print("    neurostack init ~/my-vault")
        print("    neurostack index")
        print("    neurostack search 'your query'")
        print("=" * 60)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cmd_setup_desktop(args):
    """Auto-configure Claude Desktop to use NeuroStack MCP server."""
    from ..setup import setup_desktop
    setup_desktop(dry_run=args.dry_run)


def cmd_setup_client(args):
    """Auto-configure a supported AI client to use NeuroStack MCP server."""
    from ..setup import list_clients, setup_client
    if args.list:
        list_clients()
        return
    if not args.client:
        list_clients()
        return
    setup_client(args.client, dry_run=args.dry_run)


def cmd_status(args):
    """Show NeuroStack status overview."""
    cfg = get_config()

    if args.json:
        output = {
            "version": __version__,
            "vault_root": str(cfg.vault_root),
            "db_path": str(cfg.db_path),
            "config_path": str(CONFIG_PATH),
            "initialized": cfg.db_path.exists(),
        }
        if cfg.db_path.exists():
            import sqlite3
            conn = sqlite3.connect(str(cfg.db_path))
            conn.row_factory = sqlite3.Row
            output["notes"] = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
            output["chunks"] = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
            output["embedded"] = conn.execute(
                "SELECT COUNT(*) as c FROM chunks WHERE embedding IS NOT NULL"
            ).fetchone()["c"]
            conn.close()
            output["mode"] = "full" if output["embedded"] > 0 else "lite"
        print(json.dumps(output, indent=2, default=str))
        return

    print(f"NeuroStack v{__version__}")
    print(f"  Vault:    {cfg.vault_root}")
    print(f"  Database: {cfg.db_path}")
    print(f"  Config:   {CONFIG_PATH}")

    if cfg.db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(cfg.db_path))
        conn.row_factory = sqlite3.Row
        notes = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
        chunks = conn.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
        embedded = conn.execute(
            "SELECT COUNT(*) as c FROM chunks"
            " WHERE embedding IS NOT NULL"
        ).fetchone()["c"]
        conn.close()

        mode = "full" if embedded > 0 else "lite"
        print(f"  Mode:     {mode}")
        print(f"  Notes:    {notes}")
        print(f"  Chunks:   {chunks} ({embedded} embedded)")
    else:
        print("  Status:   Not initialized. Run: neurostack init")
