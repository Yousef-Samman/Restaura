"""Shared helpers: a throwaway database per experiment, and small metric functions."""
import contextlib
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.agents.llm import LLM
from app.db import Base, make_engine, make_sessionmaker


@contextlib.contextmanager
def fresh_db():
    """An empty database in a temporary folder, deleted afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{Path(tmp) / 'eval.db'}")
        Base.metadata.create_all(engine)
        with make_sessionmaker(engine)() as db:
            yield db
        engine.dispose()


def no_llm() -> LLM:
    return LLM(Settings(anthropic_api_key=None))


def ai_llm(model: str) -> LLM | None:
    """Claude with the key from the environment, or None when no key is set."""
    settings = Settings(model=model)
    return LLM(settings) if settings.anthropic_api_key else None


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def rate(hits: int, n: int) -> float | None:
    return hits / n if n else None


__all__ = ["Session", "fresh_db", "no_llm", "ai_llm", "pct", "rate"]
