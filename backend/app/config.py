"""Settings come from environment variables only. Nothing secret lives in the repository."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./restaura.db"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or os.getenv("RESTAURA_ANTHROPIC_API_KEY") or None)
    model: str = field(default_factory=lambda: os.getenv("RESTAURA_MODEL", "claude-haiku-5-5"))
    # results of `python -m evals`, shown on the manager's Agent evaluation page
    eval_results: Path = field(default_factory=lambda: Path(os.getenv("RESTAURA_EVAL_RESULTS",
                                                                     Path(__file__).resolve().parent.parent / "evals" / "results" / "latest.json")))
    llm_timeout: float = field(default_factory=lambda: float(os.getenv("RESTAURA_LLM_TIMEOUT", "30")))
    store_name: str = field(default_factory=lambda: os.getenv("STORE_NAME", "Demo Store"))
    smtp_host: str | None = field(default_factory=lambda: os.getenv("SMTP_HOST") or None)
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str | None = field(default_factory=lambda: os.getenv("SMTP_USER") or None)
    smtp_password: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD") or None)
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", "orders@restaura.local"))
    # In a demo, every supplier email can be redirected to one inbox you control.
    demo_supplier_email: str | None = field(default_factory=lambda: os.getenv("DEMO_SUPPLIER_EMAIL") or None)
    # Same for WhatsApp orders: international number, digits only (e.g. 9665XXXXXXXX).
    demo_supplier_whatsapp: str | None = field(default_factory=lambda: os.getenv("DEMO_SUPPLIER_WHATSAPP") or None)
    # Demo accounts are created on first start. Set your own passwords before showing the app to anyone.
    manager_password: str = field(default_factory=lambda: os.getenv("MANAGER_PASSWORD", "manager-demo"))
    cashier_password: str = field(default_factory=lambda: os.getenv("CASHIER_PASSWORD", "cashier-demo"))
    # Time of day (HH:MM, store time) when the stock check runs by itself, e.g. "23:30". Empty means only on demand.
    nightly_stock_check: str | None = field(default_factory=lambda: os.getenv("NIGHTLY_STOCK_CHECK") or None)
    # Demo mode shows one-tap sign-in buttons and the demo logins on the sign-in page, for people trying the app.
    # Set DEMO_MODE=0 for a real store.
    demo_mode: bool = field(default_factory=lambda: os.getenv("DEMO_MODE", "1") == "1")
    secure_cookies: bool = field(default_factory=lambda: os.getenv("SECURE_COOKIES", "0") == "1")
    seed_demo_data: bool = field(default_factory=lambda: os.getenv("SEED_DEMO_DATA", "1") == "1")


def get_settings() -> Settings:
    return Settings()
