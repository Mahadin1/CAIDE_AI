"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Allow both local-dev (.env next to this file) and deployment to work.
    load_dotenv(Path(__file__).parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


class Settings:
    def __init__(self) -> None:
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
        self.supabase_db_password: str = os.getenv("SUPABASE_DB_PASSWORD", "")
        self.supabase_management_token: str = os.getenv(
            "SUPABASE_MANAGEMENT_TOKEN", ""
        )
        self.supabase_auth_redirect_url: str = os.getenv(
            "SUPABASE_AUTH_REDIRECT_URL", ""
        )
        self.datascope_redirect_urls: str = os.getenv(
            "DATASCOPE_REDIRECT_URLS", ""
        )
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.paddle_api_key: str = os.getenv("PADDLE_API_KEY", "")
        self.paddle_webhook_secret: str = os.getenv("PADDLE_WEBHOOK_SECRET", "")
        # Optional model override; default to a free OpenRouter endpoint.
        self.openrouter_model: str = os.getenv(
            "OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"
        )
        # Monthly report limit for free tier users.
        self.free_monthly_limit: int = int(os.getenv("FREE_MONTHLY_LIMIT", "2"))
        # --- adaptive EDA platform knobs (see docs/ARCHITECTURE.md) ---
        # Rows/columns at or below which the full file is analyzed exactly.
        self.max_rows_full: int = int(os.getenv("MAX_ROWS_FULL", "1000000"))
        self.max_columns: int = int(os.getenv("MAX_COLUMNS", "500"))
        # Deterministic sample size used when the file is larger than max_rows_full.
        self.sample_target_rows: int = int(os.getenv("SAMPLE_TARGET_ROWS", "200000"))
        # Async worker tuning.
        self.job_timeout_seconds: int = int(os.getenv("JOB_TIMEOUT_SECONDS", "900"))
        self.job_max_attempts: int = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
        self.job_stale_seconds: int = int(os.getenv("JOB_STALE_SECONDS", "1800"))
        # Narrative length cap.
        self.narrative_max_words: int = int(os.getenv("NARRATIVE_MAX_WORDS", "1200"))

    @property
    def is_configured(self) -> bool:
        # OpenRouter is optional: narrate() falls back to deterministic prose
        # when no key is set, so reports still complete.
        return bool(
            self.supabase_url
            and self.supabase_service_key
        )


settings = Settings()
