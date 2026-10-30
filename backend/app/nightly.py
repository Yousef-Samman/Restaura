"""Runs the stock check by itself once the branch has closed, so the manager finds the draft orders waiting.
Off unless NIGHTLY_STOCK_CHECK is set (HH:MM, store time, for example 23:30). The manager still approves every order."""
import datetime as dt
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .agents import overview, stock_agent
from .agents.llm import LLM
from .models import AgentRun
from .routines import local_now

log = logging.getLogger("restaura.nightly")


def parse_time(text: str) -> dt.time:
    hour, _, minute = text.strip().partition(":")
    return dt.time(int(hour), int(minute or 0))


def is_due(now: dt.datetime, run_at: dt.time, last_stock_run: dt.datetime | None) -> bool:
    """True from `run_at` on, until a stock check has run since that time today."""
    start = dt.datetime.combine(now.date(), run_at)
    return now >= start and (last_stock_run is None or last_stock_run < start)


def check_once(Session_: sessionmaker, llm: LLM, run_at: dt.time, now: dt.datetime | None = None) -> bool:
    """Runs the stock check and the overview when due. Returns True when it ran."""
    now = now or local_now().replace(tzinfo=None)
    with Session_() as db:
        last = db.scalar(select(AgentRun.created_at).where(AgentRun.agent == "stock").order_by(AgentRun.id.desc()).limit(1))
        # created_at is stored in UTC; compare in store time through the same offset as `now`
        if last is not None:
            last = last + (now - dt.datetime.now(dt.UTC).replace(tzinfo=None))
        if not is_due(now, run_at, last):
            return False
        stock_agent.run(db, llm)
        overview.run(db, llm)
    return True


def start(Session_: sessionmaker, llm: LLM, run_at: dt.time, every: float = 60) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.wait(every):
            try:
                if check_once(Session_, llm, run_at):
                    log.info("Nightly stock check done")
            except Exception:  # keep the loop alive; the manager can still run the check by hand
                log.exception("Nightly stock check failed")

    threading.Thread(target=loop, name="nightly-stock-check", daemon=True).start()
    return stop
