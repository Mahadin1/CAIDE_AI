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
        # Paddle price ids per plan (3 paid tiers + free). Used to map a
        # subscription event's price back to a plan; unknown ids fall back to
        # the pro price id, then to 'pro'.
        self.paddle_starter_price_id: str = os.getenv(
            "PADDLE_STARTER_PRICE_ID", ""
        )
        self.paddle_pro_price_id: str = os.getenv("PADDLE_PRO_PRICE_ID", "")
        self.paddle_scale_price_id: str = os.getenv(
            "PADDLE_SCALE_PRICE_ID", ""
        )
        # Optional model override; default to a free OpenRouter endpoint.
        self.openrouter_model: str = os.getenv(
            "OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free"
        )
        # Monthly report limit for free tier users.
        self.free_monthly_limit: int = int(os.getenv("FREE_MONTHLY_LIMIT", "2"))
        # Monthly credit allowance per plan. One credit = one analysis job.
        # Plans are deliberately *not* unlimited: credits are the revenue unit.
        self.plan_monthly_credits: dict[str, int] = {
            "free": int(os.getenv("FREE_MONTHLY_CREDITS", "3")),
            "starter": int(os.getenv("STARTER_MONTHLY_CREDITS", "30")),
            "pro": int(os.getenv("PRO_MONTHLY_CREDITS", "100")),
            "scale": int(os.getenv("SCALE_MONTHLY_CREDITS", "300")),
        }
        self.default_plan: str = "free"
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

    def plan_for_price_id(self, price_id: str | None) -> str:
        """Map a Paddle price id to a plan name (best-effort)."""
        if not price_id:
            return self.default_plan
        if price_id == self.paddle_starter_price_id:
            return "starter"
        if price_id == self.paddle_scale_price_id:
            return "scale"
        if price_id == self.paddle_pro_price_id:
            return "pro"
        return "pro"  # legacy single-price behaviour

    def credits_for_plan(self, plan: str | None) -> int:
        return int(self.plan_monthly_credits.get(plan or self.default_plan, 0))


settings = Settings()
