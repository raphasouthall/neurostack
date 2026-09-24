# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unified configuration for NeuroStack."""

import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 fallback

log = logging.getLogger(__name__)

# Pre-#142 names for the index-time LLM settings. They date from when the same
# endpoint also answered questions while a caller waited; the split needs the
# index_llm_* form, so the old names are still read and reported once.
_LEGACY_LLM_KEYS = {
    "llm_url": "index_llm_url",
    "llm_model": "index_llm_model",
    "llm_api_key": "index_llm_api_key",
}
_LEGACY_LLM_ENV = {
    "NEUROSTACK_LLM_URL": "index_llm_url",
    "NEUROSTACK_LLM_MODEL": "index_llm_model",
    "NEUROSTACK_LLM_API_KEY": "index_llm_api_key",
}


def _data_dir() -> Path:
    """Platform-aware application data directory."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local" / "neurostack"
    return Path.home() / ".local" / "share" / "neurostack"


def _config_dir() -> Path:
    """Platform-aware config directory."""
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Local" / "neurostack"
    return Path.home() / ".config" / "neurostack"


CONFIG_PATH = _config_dir() / "config.toml"


@dataclass
class Config:
    """NeuroStack configuration with env var overrides."""

    mode: str = "local"  # "local"
    vault_root: Path = field(default_factory=lambda: Path.home() / "brain")
    db_dir: Path = field(default_factory=_data_dir)
    embed_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    # Deadline per single-text embed call; retried once. Two tries stay under
    # the 30 s MCP client timeout. Raise it for a slow local model.
    embed_timeout_s: float = 12.0
    # Index-time LLM: note summaries, triples, community labels, harvest
    # classification, synthesize, consolidate. Nothing on a retrieval path calls
    # it — #142 removed the request-time answering paths, so no user ever waits
    # on this endpoint.
    index_llm_url: str = "http://localhost:11434"
    # NOTE: Verify the license of any model you configure here.
    # phi3.5 is MIT licensed.
    index_llm_model: str = "phi3.5"
    index_llm_api_key: str = ""
    # Shell command that answers a prompt on stdin and prints the reply on
    # stdout, used instead of `index_llm_url` when set. It exists so a job can
    # run through a subscription CLI (`claude -p --model haiku`), which has no
    # HTTP endpoint, optionally over an SSH hop to the host holding the login.
    index_llm_command: str = ""
    index_llm_command_timeout_s: float = 300.0
    # Judgement model (`judge.py`): picks a label, scores an option, answers
    # yes/no. It never generates text, so summaries and triples stay on the
    # index LLM. Two callers today: harvest classification, which runs offline,
    # and `vault_search(rerank=True)`, which a caller has to ask for by name so
    # #142 still keeps the default retrieval path LLM-free.
    judge_url: str = "https://openrouter.ai/api"
    judge_model: str = "~typesafe/jev-latest"
    judge_api_key: str = ""
    judge_concurrency: int = 8
    judge_timeout_s: float = 30.0
    # Let the judgement model pick harvest entity types instead of the index
    # LLM. Measured +7.9pp agreement on 191 held-out memories (p=0.039) and
    # 13x faster; falls back to the index LLM's own answer on any failure.
    harvest_judge_types: bool = True
    # One extra index-LLM call per harvested session (#259) that reads the
    # transcript tail and saves up to three session verdicts, the conclusions
    # the per-message pass misses because they span several messages.
    harvest_conclusions: bool = True
    # After a /save checkpoint succeeds, the server worker also runs the
    # vault-save Pi agent (#268) on the same transcript, which patches vault
    # notes in place. Off by default: it needs Node and an agent key, and it
    # commits and pushes the vault.
    vault_save_on_checkpoint: bool = False
    # `neurostack agent <job>` (#217): the Pi agent that runs jobs needing tools
    # and reasoning. Provider and model are Pi's names. Sonnet 5 matched Opus 5
    # on placement in a 13-memory bake-off at 44% of the cost. An empty key
    # falls back to judge_api_key, which is the same OpenRouter key in practice.
    agent_provider: str = "openrouter"
    agent_model: str = "anthropic/claude-sonnet-5"
    agent_api_key: str = ""
    # Base URL for the agent's provider API. Empty uses the provider's own
    # endpoint. Set it to reach a compatible proxy, such as CLIProxyAPI serving
    # the Anthropic Messages API from a Claude subscription login.
    agent_base_url: str = ""
    # `neurostack run-due` (#225). A failed job run's row goes to this shell
    # command as JSON on stdin, e.g. `ntfy publish mytopic` or a curl to a
    # webhook. Empty sends nothing.
    notify_command: str = ""
    # Names of the scheduled jobs this host runs, e.g. ["decay", "reindex"].
    # None runs every job whose requirements this host meets.
    jobs: list[str] | None = None
    # The server's checkpoint-worker and harvest-worker (#233) pipe each
    # checkpoint prompt through this shell command and save what it prints,
    # e.g. `claude -p --model haiku`, or a script that posts to an
    # OpenAI-style endpoint. Empty turns both workers off on this host.
    checkpoint_command: str = ""
    checkpoint_timeout_s: float = 300.0
    # Largest window one server checkpoint summarizes, 0 for no cap. Same
    # meaning as the client.toml key: a backlog transcript can exceed the
    # model's context, so the window is cut and the cursor walks on.
    checkpoint_max_messages: int = 0
    # Notes in flight at once during `backfill triples`. Only the network side
    # (LLM extraction + embedding) runs in parallel; every database write stays
    # on one thread. 1 is the old serial loop. 8 took a 741-note backfill from
    # ~18 hours to ~2.5 on an OpenRouter-hosted index LLM.
    triple_backfill_workers: int = 1
    embed_api_key: str = ""
    session_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: str = ""
    # Tools to keep out of the MCP surface. Every registered tool's schema is
    # injected into every client session, so a tool nobody calls costs tokens on
    # each turn and lengthens the menu the model chooses from. Names are the tool
    # names as registered, e.g. ["vault_communities", "vault_checkpoint"].
    disabled_tools: list[str] = field(default_factory=list)
    cooccurrence_boost_weight: float = 0.1
    # Link-section down-weighting (issue #41): a chunk that is mostly wiki-link
    # markup — ## Related blocks, index / map-of-content notes — is navigational,
    # not substantive. Matches there are penalized so a tangential note whose only
    # hit is a dense link block can't outrank a note whose body covers the query.
    link_section_penalty: float = 0.5     # score multiplier for link-list chunk matches
    link_density_threshold: float = 0.5   # chunk is a "link section" when this fraction
                                          # or more of its characters are wiki-link markup
    # Ranking-signal weights (issue #66). Scalars that hybrid_search blends on top
    # of the base FTS+cosine score. These four were hardcoded in search.py before
    # #66; the defaults reproduce that exact behaviour. A weight sweep
    # (RankingWeights + the tune harness) varies them against the eval metrics
    # (recall@k / MRR / NDCG), and a validated set can be pinned here or via env.
    convergence_weight: float = 0.3       # blend: score = (1-w)*score + w*convergence
    hotness_weight: float = 0.2           # blend: score = (1-w)*score + w*hotness
    inhibition_threshold: float = 0.65    # suppress a result only when its cosine sim to a
                                          # higher-ranked result exceeds this
    inhibition_strength: float = 0.30     # max fractional score reduction at sim = 1.0
    # Auto-router merge (issue #58): depth="auto" merges the triple ranking with
    # an independent summary search instead of returning triple order with summary
    # text attached. This is the weight given to the (normalized) summary score in
    # the blended note ranking; the triple score gets (1 - auto_summary_weight).
    auto_summary_weight: float = 0.5      # 0.0 = triples only, 1.0 = summaries only
    # Community-detection staleness (issue #65): detect_communities runs only on
    # `communities build` / `init`, never in the index pipeline, so the partition
    # and its LLM summaries drift as notes are added or edited. These thresholds
    # decide when vault_stats / vault_communities flag the partition stale and
    # when `communities build --if-stale` triggers a rebuild.
    community_stale_age_days: float = 14.0   # flag/rebuild if last build older than this
    community_stale_drift: float = 0.10      # ...or if this fraction of notes changed since
    # Implicit-feedback loop (issue #66): when enabled, searches are logged and a
    # subsequent deliberate use of a surfaced note is attributed back to the query,
    # producing usage-grounded labels the tuner can learn from. Off by default —
    # opting in adds a lightweight write to the search + record-usage paths.
    feedback_enabled: bool = False
    feedback_window_seconds: float = 1800.0  # a use counts as feedback if within this of the search
    feedback_log_retention: int = 5000       # cap on retained search_log rows
    # Two-tier activation signal (issue #95): vault_context injections are logged
    # as 'primed' (synaptic tag — sub-threshold), deliberate record_usage / reads
    # stay 'used' (capture — consolidating). Primed events carry a small hotness
    # weight, their total contribution is capped BELOW one real use, and they only
    # count within a decay window — priming alone must never promote a note.
    primed_weight: float = 0.1        # hotness weight of one primed event vs one use
    primed_cap: float = 0.5           # ceiling on total primed contribution (< 1.0 use)
    primed_decay_days: float = 14.0   # primed events older than this contribute nothing
    # Vault write-back (issue #20): opt-in persistence of qualifying memories as
    # markdown files under a quarantined directory (default ``.neurostack/``).
    # Off by default — the DB stays the source of truth; files are exports. Only
    # persistent (no-TTL) decision/convention/learning/bug memories are written;
    # observation/context are written only when include_observations is set.
    writeback_enabled: bool = False
    writeback_path: str = ".neurostack"   # relative to vault_root; NeuroStack only
                                          # ever writes inside this directory
    writeback_include_observations: bool = False

    @property
    def db_path(self) -> Path:
        return self.db_dir / "neurostack.db"

    @property
    def session_db(self) -> Path:
        return self.db_dir / "sessions.db"


@dataclass(frozen=True)
class RankingWeights:
    """The tunable ranking-signal scalars ``hybrid_search`` blends on top of the
    base FTS+cosine score (issue #66).

    Defaults reproduce the production constants. Passing a ``RankingWeights`` to
    ``hybrid_search(weights=...)`` overrides them for that call without touching
    global config — the mechanism the weight-tuning sweep uses to evaluate a
    candidate vector against the eval harness. Production callers pass nothing and
    get :meth:`from_config`, which reads the operator's config.toml / env.
    """

    convergence_weight: float = 0.3
    hotness_weight: float = 0.2
    inhibition_threshold: float = 0.65
    inhibition_strength: float = 0.30
    cooccurrence_boost_weight: float = 0.1
    primed_weight: float = 0.1
    link_section_penalty: float = 0.5
    link_density_threshold: float = 0.5

    @classmethod
    def from_config(cls, cfg: "Config") -> "RankingWeights":
        """Build the weight vector from a loaded :class:`Config`."""
        return cls(
            convergence_weight=cfg.convergence_weight,
            hotness_weight=cfg.hotness_weight,
            inhibition_threshold=cfg.inhibition_threshold,
            inhibition_strength=cfg.inhibition_strength,
            cooccurrence_boost_weight=cfg.cooccurrence_boost_weight,
            primed_weight=cfg.primed_weight,
            link_section_penalty=cfg.link_section_penalty,
            link_density_threshold=cfg.link_density_threshold,
        )


def load_config() -> Config:
    """Load config from TOML file, then apply env var overrides."""
    cfg = Config()
    # (old name, current name) for every pre-#142 LLM key seen in this load.
    # Collected across TOML and env so the whole load reports once.
    legacy: list[tuple[str, str]] = []

    # Load TOML if exists
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        if "mode" in data:
            cfg.mode = data["mode"]
        for key in ("vault_root", "db_dir", "session_dir"):
            if key in data:
                setattr(cfg, key, Path(os.path.expanduser(data[key])))
        for key in ("embed_url", "embed_model", "index_llm_url", "index_llm_model",
                    "index_llm_api_key", "index_llm_command", "embed_api_key",
                    "judge_url", "judge_model", "judge_api_key",
                    "agent_provider", "agent_model", "agent_api_key", "agent_base_url",
                    "notify_command", "checkpoint_command",
                    "api_host", "api_key"):
            if key in data:
                setattr(cfg, key, data[key])
        if "index_llm_command_timeout_s" in data:
            cfg.index_llm_command_timeout_s = float(data["index_llm_command_timeout_s"])
        if "checkpoint_timeout_s" in data:
            cfg.checkpoint_timeout_s = float(data["checkpoint_timeout_s"])
        if "checkpoint_max_messages" in data:
            cfg.checkpoint_max_messages = int(data["checkpoint_max_messages"])
        if "judge_concurrency" in data:
            cfg.judge_concurrency = int(data["judge_concurrency"])
        if "judge_timeout_s" in data:
            cfg.judge_timeout_s = float(data["judge_timeout_s"])
        if "harvest_judge_types" in data:
            cfg.harvest_judge_types = bool(data["harvest_judge_types"])
        if "harvest_conclusions" in data:
            cfg.harvest_conclusions = bool(data["harvest_conclusions"])
        if "vault_save_on_checkpoint" in data:
            cfg.vault_save_on_checkpoint = bool(data["vault_save_on_checkpoint"])
        if "triple_backfill_workers" in data:
            cfg.triple_backfill_workers = int(data["triple_backfill_workers"])
        for old, new in _LEGACY_LLM_KEYS.items():
            if old not in data:
                continue
            # The current name wins when a file carries both.
            if new not in data:
                setattr(cfg, new, data[old])
            legacy.append((old, new))
        if "embed_dim" in data:
            cfg.embed_dim = int(data["embed_dim"])
        if "embed_timeout_s" in data:
            cfg.embed_timeout_s = float(data["embed_timeout_s"])
        if "api_port" in data:
            cfg.api_port = int(data["api_port"])
        if "disabled_tools" in data:
            raw = data["disabled_tools"]
            if isinstance(raw, str):
                raw = [p for p in raw.replace(",", " ").split() if p]
            cfg.disabled_tools = [str(t).strip() for t in raw if str(t).strip()]
        if "jobs" in data:
            raw = data["jobs"]
            if isinstance(raw, str):
                raw = raw.replace(",", " ").split()
            cfg.jobs = [str(j).strip() for j in raw if str(j).strip()]
        if "cooccurrence_boost_weight" in data:
            cfg.cooccurrence_boost_weight = float(data["cooccurrence_boost_weight"])
        if "link_section_penalty" in data:
            cfg.link_section_penalty = float(data["link_section_penalty"])
        if "link_density_threshold" in data:
            cfg.link_density_threshold = float(data["link_density_threshold"])
        for key in ("convergence_weight", "hotness_weight",
                    "inhibition_threshold", "inhibition_strength",
                    "primed_weight", "primed_cap", "primed_decay_days"):
            if key in data:
                setattr(cfg, key, float(data[key]))
        if "feedback_enabled" in data:
            cfg.feedback_enabled = bool(data["feedback_enabled"])
        if "feedback_window_seconds" in data:
            cfg.feedback_window_seconds = float(data["feedback_window_seconds"])
        if "feedback_log_retention" in data:
            cfg.feedback_log_retention = int(data["feedback_log_retention"])
        if "auto_summary_weight" in data:
            cfg.auto_summary_weight = float(data["auto_summary_weight"])
        if "community_stale_age_days" in data:
            cfg.community_stale_age_days = float(data["community_stale_age_days"])
        if "community_stale_drift" in data:
            cfg.community_stale_drift = float(data["community_stale_drift"])

        # Write-back is configured under a [writeback] table.
        wb = data.get("writeback")
        if isinstance(wb, dict):
            if "enabled" in wb:
                cfg.writeback_enabled = bool(wb["enabled"])
            if "path" in wb:
                cfg.writeback_path = str(wb["path"])
            if "include_observations" in wb:
                cfg.writeback_include_observations = bool(wb["include_observations"])

    # Env var overrides (NEUROSTACK_ prefix)
    env_map = {
        "NEUROSTACK_MODE": ("mode", str),
        "NEUROSTACK_VAULT_ROOT": ("vault_root", Path),
        "NEUROSTACK_DB_DIR": ("db_dir", Path),
        "NEUROSTACK_EMBED_URL": ("embed_url", str),
        "NEUROSTACK_EMBED_MODEL": ("embed_model", str),
        "NEUROSTACK_EMBED_DIM": ("embed_dim", int),
        "NEUROSTACK_EMBED_TIMEOUT_S": ("embed_timeout_s", float),
        "NEUROSTACK_INDEX_LLM_URL": ("index_llm_url", str),
        "NEUROSTACK_INDEX_LLM_MODEL": ("index_llm_model", str),
        "NEUROSTACK_INDEX_LLM_API_KEY": ("index_llm_api_key", str),
        "NEUROSTACK_EMBED_API_KEY": ("embed_api_key", str),
        "NEUROSTACK_JUDGE_URL": ("judge_url", str),
        "NEUROSTACK_JUDGE_MODEL": ("judge_model", str),
        "NEUROSTACK_JUDGE_API_KEY": ("judge_api_key", str),
        "NEUROSTACK_AGENT_PROVIDER": ("agent_provider", str),
        "NEUROSTACK_AGENT_MODEL": ("agent_model", str),
        "NEUROSTACK_AGENT_API_KEY": ("agent_api_key", str),
        "NEUROSTACK_AGENT_BASE_URL": ("agent_base_url", str),
        "NEUROSTACK_NOTIFY_COMMAND": ("notify_command", str),
        "NEUROSTACK_CHECKPOINT_COMMAND": ("checkpoint_command", str),
        "NEUROSTACK_CHECKPOINT_TIMEOUT_S": ("checkpoint_timeout_s", float),
        "NEUROSTACK_CHECKPOINT_MAX_MESSAGES": ("checkpoint_max_messages", int),
        "NEUROSTACK_JUDGE_CONCURRENCY": ("judge_concurrency", int),
        "NEUROSTACK_JUDGE_TIMEOUT_S": ("judge_timeout_s", float),
        "NEUROSTACK_HARVEST_JUDGE_TYPES": ("harvest_judge_types", bool),
        "NEUROSTACK_HARVEST_CONCLUSIONS": ("harvest_conclusions", bool),
        "NEUROSTACK_VAULT_SAVE_ON_CHECKPOINT": ("vault_save_on_checkpoint", bool),
        "NEUROSTACK_TRIPLE_BACKFILL_WORKERS": ("triple_backfill_workers", int),
        "NEUROSTACK_SESSION_DIR": ("session_dir", Path),
        "NEUROSTACK_API_HOST": ("api_host", str),
        "NEUROSTACK_API_PORT": ("api_port", int),
        "NEUROSTACK_API_KEY": ("api_key", str),
        "NEUROSTACK_COOCCURRENCE_BOOST": ("cooccurrence_boost_weight", float),
        "NEUROSTACK_LINK_SECTION_PENALTY": ("link_section_penalty", float),
        "NEUROSTACK_LINK_DENSITY_THRESHOLD": ("link_density_threshold", float),
        "NEUROSTACK_CONVERGENCE_WEIGHT": ("convergence_weight", float),
        "NEUROSTACK_HOTNESS_WEIGHT": ("hotness_weight", float),
        "NEUROSTACK_INHIBITION_THRESHOLD": ("inhibition_threshold", float),
        "NEUROSTACK_INHIBITION_STRENGTH": ("inhibition_strength", float),
        "NEUROSTACK_PRIMED_WEIGHT": ("primed_weight", float),
        "NEUROSTACK_PRIMED_CAP": ("primed_cap", float),
        "NEUROSTACK_PRIMED_DECAY_DAYS": ("primed_decay_days", float),
        "NEUROSTACK_FEEDBACK_ENABLED": ("feedback_enabled", bool),
        "NEUROSTACK_FEEDBACK_WINDOW_SECONDS": ("feedback_window_seconds", float),
        "NEUROSTACK_FEEDBACK_LOG_RETENTION": ("feedback_log_retention", int),
        "NEUROSTACK_AUTO_SUMMARY_WEIGHT": ("auto_summary_weight", float),
        "NEUROSTACK_COMMUNITY_STALE_AGE_DAYS": ("community_stale_age_days", float),
        "NEUROSTACK_COMMUNITY_STALE_DRIFT": ("community_stale_drift", float),
        "NEUROSTACK_WRITEBACK_ENABLED": ("writeback_enabled", bool),
        "NEUROSTACK_WRITEBACK_PATH": ("writeback_path", str),
        "NEUROSTACK_WRITEBACK_INCLUDE_OBSERVATIONS": (
            "writeback_include_observations", bool,
        ),
    }

    # Pre-#142 env names, applied before the current ones so a NEUROSTACK_INDEX_LLM_*
    # override still wins.
    for env_key, attr in _LEGACY_LLM_ENV.items():
        val = os.environ.get(env_key)
        if val is None:
            continue
        setattr(cfg, attr, val)
        legacy.append((env_key, "NEUROSTACK_" + attr.upper()))

    for env_key, (attr, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if typ is Path:
                setattr(cfg, attr, Path(os.path.expanduser(val)))
            elif typ is bool:
                setattr(cfg, attr, val.lower() in ("1", "true", "yes"))
            else:
                setattr(cfg, attr, typ(val))

    # Comma- or space-separated, e.g. NEUROSTACK_DISABLED_TOOLS="vault_merge,vault_diff"
    disabled_env = os.environ.get("NEUROSTACK_DISABLED_TOOLS")
    if disabled_env is not None:
        cfg.disabled_tools = [
            p for p in disabled_env.replace(",", " ").split() if p
        ]

    if legacy:
        # One line per load, however many old names appear — a per-key warning
        # would repeat on every get_config() miss and bury the rename.
        log.warning(
            "deprecated LLM config name(s) in use; rename to the index_llm_* form: %s",
            ", ".join(f"{old} -> {new}" for old, new in legacy),
        )

    return cfg


def _auth_headers(api_key: str) -> dict[str, str]:
    """Build Authorization header dict if an API key is set."""
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


# Module-level singleton
_config: Config | None = None


def get_config() -> Config:
    """Get or create the singleton config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config
