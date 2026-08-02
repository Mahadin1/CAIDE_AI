"""Application configuration loaded from environment variables."""
import os


class Settings:
    def __init__(self) -> None:
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
        self.supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
        self.openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
        self.paddle_api_key: str = os.getenv("PADDLE_API_KEY", "")
        self.paddle_webhook_secret: str = os.getenv("PADDLE_WEBHOOK_SECRET", "")
        # Optional model override; default to a free OpenRouter endpoint.
        self.openrouter_model: str = os.getenv(
            "OPENROUTER_MODEL", "qwen/qwen-2.5-7b-instruct:free"
        )
        # Monthly report limit for free tier users.
        self.free_monthly_limit: int = int(os.getenv("FREE_MONTHLY_LIMIT", "2"))
        # Maximum accepted CSV size in bytes (10 MB).
        self.max_upload_bytes: int = 10 * 1024 * 1024

    @property
    def is_configured(self) -> bool:
        # OpenRouter is optional: narrate() falls back to deterministic prose
        # when no key is set, so reports still complete.
        return bool(
            self.supabase_url
            and self.supabase_service_key
        )


settings = Settings()
