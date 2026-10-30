"""Settings come from environment variables only. Nothing secret lives in the repository."""
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./restaura.db"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    model: str = field(default_factory=lambda: os.getenv("RESTAURA_MODEL", "claude-opus-5-5"))
    store_name: str = field(default_factory=lambda: os.getenv("STORE_NAME", "Demo Store"))
    smtp_host: str | None = field(default_factory=lambda: os.getenv("SMTP_HOST") or None)
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str | None = field(default_factory=lambda: os.getenv("SMTP_USER") or None)
    smtp_password: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD") or None)
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", "orders@restaura.local"))
    # In a demo, every supplier email can be redirected to one inbox you control.
    demo_supplier_email: str | None = field(default_factory=lambda: os.getenv("DEMO_SUPPLIER_EMAIL") or None)
    seed_demo_data: bool = field(default_factory=lambda: os.getenv("SEED_DEMO_DATA", "1") == "1")


def get_settings() -> Settings:
    return Settings()
