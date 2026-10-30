import datetime as dt

from sqlalchemy import select

from app import nightly
from app.agents.llm import LLM
from app.config import Settings
from app.db import Base, make_engine, make_sessionmaker
from app.models import PurchaseOrder
from app.seed import seed


def test_is_due_from_the_set_time_until_a_check_has_run():
    run_at = dt.time(23, 30)
    day = dt.date(2026, 10, 30)
    at = lambda h, m: dt.datetime.combine(day, dt.time(h, m))
    assert not nightly.is_due(at(23, 29), run_at, None)
    assert nightly.is_due(at(23, 30), run_at, None)
    assert nightly.is_due(at(23, 50), run_at, at(18, 0))        # last check was before closing
    assert not nightly.is_due(at(23, 50), run_at, at(23, 31))   # already ran tonight
    assert nightly.is_due(at(23, 40), run_at, at(23, 31) - dt.timedelta(days=1))  # last night's check does not count
    assert nightly.parse_time("23:30") == run_at and nightly.parse_time("9") == dt.time(9, 0)


def test_check_runs_once_and_leaves_drafts_for_the_manager(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/n.db")
    Base.metadata.create_all(engine)
    Session_ = make_sessionmaker(engine)
    with Session_() as db:
        seed(db)
    llm = LLM(Settings(anthropic_api_key=None))
    run_at = dt.time(23, 30)
    now = dt.datetime.combine(dt.date.today(), dt.time(23, 40))
    assert not nightly.check_once(Session_, llm, run_at, now=dt.datetime.combine(dt.date.today(), dt.time(22, 0)))
    assert nightly.check_once(Session_, llm, run_at, now=now)
    with Session_() as db:
        assert db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")).first()
    assert not nightly.check_once(Session_, llm, run_at, now=now)
