# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Unified configuration for NeuroStack."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python 3.10 fallback


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
    llm_url: str = "http://localhost:11434"
    # NOTE: Verify the license of any model you configure here.
    # phi3.5 is MIT licensed.
    llm_model: str = "phi3.5"
    llm_api_key: str = ""
    embed_api_key: str = ""
    session_dir: Path = field(default_factory=lambda: Path.home() / ".claude" / "projects")
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_key: str = ""
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
            link_section_penalty=cfg.link_section_penalty,
            link_density_threshold=cfg.link_density_threshold,
        )


def load_config() -> Config:
    """Load config from TOML file, then apply env var overrides."""
    cfg = Config()

    # Load TOML if exists
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)

        if "mode" in data:
            cfg.mode = data["mode"]
        for key in ("vault_root", "db_dir", "session_dir"):
            if key in data:
                setattr(cfg, key, Path(os.path.expanduser(data[key])))
        for key in ("embed_url", "embed_model", "llm_url", "llm_model",
                    "llm_api_key", "embed_api_key", "api_host", "api_key"):
            if key in data:
                setattr(cfg, key, data[key])
        if "embed_dim" in data:
            cfg.embed_dim = int(data["embed_dim"])
        if "api_port" in data:
            cfg.api_port = int(data["api_port"])
        if "cooccurrence_boost_weight" in data:
            cfg.cooccurrence_boost_weight = float(data["cooccurrence_boost_weight"])
        if "link_section_penalty" in data:
            cfg.link_section_penalty = float(data["link_section_penalty"])
        if "link_density_threshold" in data:
            cfg.link_density_threshold = float(data["link_density_threshold"])
        for key in ("convergence_weight", "hotness_weight",
                    "inhibition_threshold", "inhibition_strength"):
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
        "NEUROSTACK_LLM_URL": ("llm_url", str),
        "NEUROSTACK_LLM_MODEL": ("llm_model", str),
        "NEUROSTACK_LLM_API_KEY": ("llm_api_key", str),
        "NEUROSTACK_EMBED_API_KEY": ("embed_api_key", str),
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

    for env_key, (attr, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            if typ is Path:
                setattr(cfg, attr, Path(os.path.expanduser(val)))
            elif typ is bool:
                setattr(cfg, attr, val.lower() in ("1", "true", "yes"))
            else:
                setattr(cfg, attr, typ(val))

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
