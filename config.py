"""
config.py â€” Loads settings from .env and exposes a typed Config object.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Try to load python-dotenv; gracefully skip if unavailable (env may already be set)
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
    else:
        _example = Path(__file__).parent / ".env.example"
        if _example.exists():
            print("[config] WARNING: .env not found. Copy .env.example to .env and fill in your credentials.")
except ImportError:
    print("[config] WARNING: python-dotenv not installed. Run: pip install python-dotenv")


def _bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(val: str | None, default: int = 0) -> int:
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default


def _list(val: str | None, default: list[str] | None = None) -> list[str]:
    if not val:
        return default or []
    return [s.strip() for s in val.split(",") if s.strip()]


@dataclass
class Config:
    # LLM
    model_provider: str = "openai"          # "openai" | "gemini" | "hybrid"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    nvidia_api_key: str = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY", ""))
    nvidia_model: str = field(default_factory=lambda: os.getenv("NVIDIA_MODEL", "meta/llama3-70b-instruct"))
    # Hybrid stage models (researcher=Gemini cleans facts, writer=OpenAI writes tweet)
    hybrid_researcher_model: str = "meta/llama3-70b-instruct"
    hybrid_writer_model: str = "gpt-4o-mini"

    # X / Twitter
    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_secret: str = ""
    post_to_x: bool = False

    # Scheduler
    scrape_interval_hours: int = 1
    max_posts_per_run: int = 3

    # Deduplication
    dedup_ttl_hours: int = 48

    # Scraper
    reddit_subreddits: list[str] = field(default_factory=lambda: [
        "MachineLearning", "artificial", "LocalLLaMA",
        "singularity", "AItools", "ChatGPT",
    ])
    http_timeout: int = 15
    user_agent: str = "XAgentBot/1.0 (+https://github.com/Prudhviraj101/X_Agent)"

    # Paths (computed, not from env)
    project_root: Path = field(default_factory=lambda: Path(__file__).parent)

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    @property
    def drafts_dir(self) -> Path:
        return self.project_root / "drafts"

    @property
    def dedup_store_path(self) -> Path:
        return self.project_root / "dedup_store.json"

    def has_llm(self) -> bool:
        if self.model_provider == "nvidia": return bool(self.nvidia_api_key)
        if self.model_provider == "openai": return bool(self.openai_api_key)
        if self.model_provider == "gemini": return bool(self.gemini_api_key)
        if self.model_provider == "hybrid": return bool(self.gemini_api_key) and bool(self.openai_api_key)
        return False

    def has_x_credentials(self) -> bool:
        return all([
            self.x_api_key, self.x_api_secret,
            self.x_access_token, self.x_access_secret,
        ])

    def posting_enabled(self) -> bool:
        return self.post_to_x and self.has_x_credentials()


def load_config() -> Config:
    """Read environment variables and return a Config instance."""
    return Config(
        model_provider=os.getenv("MODEL_PROVIDER", "openai").lower(),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        hybrid_researcher_model=os.getenv("HYBRID_RESEARCHER_MODEL", "gemini-3.5-flash"),
        hybrid_writer_model=os.getenv("HYBRID_WRITER_MODEL", "gpt-4o-mini"),
        x_api_key=os.getenv("X_API_KEY", ""),
        x_api_secret=os.getenv("X_API_SECRET", ""),
        x_access_token=os.getenv("X_ACCESS_TOKEN", ""),
        x_access_secret=os.getenv("X_ACCESS_SECRET", ""),
        post_to_x=_bool(os.getenv("POST_TO_X"), default=False),
        scrape_interval_hours=_int(os.getenv("SCRAPE_INTERVAL_HOURS"), default=1),
        max_posts_per_run=_int(os.getenv("MAX_POSTS_PER_RUN"), default=3),
        dedup_ttl_hours=_int(os.getenv("DEDUP_TTL_HOURS"), default=48),
        reddit_subreddits=_list(
            os.getenv("REDDIT_SUBREDDITS"),
            default=["MachineLearning", "artificial", "LocalLLaMA",
                     "singularity", "AItools", "ChatGPT"],
        ),
        http_timeout=_int(os.getenv("HTTP_TIMEOUT"), default=15),
        user_agent=os.getenv(
            "USER_AGENT",
            "XAgentBot/1.0 (+https://github.com/your-username/x-agent)",
        ),
    )



