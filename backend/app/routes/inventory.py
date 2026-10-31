"""Routes: stock, what the stock agent learned and the data check."""
import json

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import stock
from ..agents import data_check, stock_agent, stock_memory
from ..models import AgentRun, Ingredient, DataFlag, Lesson
from ..schemas import DataCheckIn, CountLine


def register(app, c):
    llm, get_db, manager_only = c.llm, c.get_db, c.manager_only

    # ---- stock and the stock-to-order agent ----------------------------------
    @app.get("/api/stock")
    def get_stock(db: Session = Depends(get_db), _=Depends(manager_only)):
        return stock.stock_report(db)

    @app.post("/api/stock/count")
    def stock_count(lines: list[CountLine], db: Session = Depends(get_db), _=Depends(manager_only)):
        diffs = {db.get(Ingredient, l.ingredient_id).name: round(stock.count(db, l.ingredient_id, l.counted), 1) for l in lines}
        db.commit()
        return {"adjustments": diffs}

    @app.post("/api/agents/stock/run")
    def run_stock_agent(db: Session = Depends(get_db), _=Depends(manager_only)):
        return stock_agent.run(db, llm)

    # ---- what the stock agent learned: suggestions the manager applies or not ----------------------------------
    @app.get("/api/lessons")
    def lessons(db: Session = Depends(get_db), _=Depends(manager_only)):
        waiting = stock_memory.refresh(db)
        db.commit()
        return {"waiting": [stock_memory.as_dict(l) for l in waiting],
                "applied": [stock_memory.as_dict(l) for l in stock_memory.applied(db)]}

    def get_lesson(db: Session, lesson_id: int) -> Lesson:
        l = db.get(Lesson, lesson_id)
        if not l or l.status != "suggested":
            raise HTTPException(404, "This suggestion is no longer waiting")
        return l

    @app.post("/api/lessons/{lesson_id}/apply")
    def apply_lesson(lesson_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        l = get_lesson(db, lesson_id)
        stock_memory.apply(db, l)
        db.commit()
        return stock_memory.as_dict(l)

    @app.post("/api/lessons/{lesson_id}/dismiss")
    def dismiss_lesson(lesson_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        l = get_lesson(db, lesson_id)
        stock_memory.dismiss(l)
        db.commit()
        return stock_memory.as_dict(l)

    # ---- the data check: records that don't fit, held out of learning until the manager decides --------------------
    @app.get("/api/data-checks")
    def data_checks(db: Session = Depends(get_db), _=Depends(manager_only)):
        waiting = data_check.run(db, llm)
        db.commit()
        return {"waiting": [data_check.as_dict(f) for f in waiting]}

    @app.post("/api/data-checks/{flag_id}")
    def decide_data_check(flag_id: int, body: DataCheckIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        f = db.get(DataFlag, flag_id)
        if not f or f.status != "waiting":
            raise HTTPException(404, "This check is no longer waiting")
        data_check.decide(db, f, body.correct, body.label)
        db.commit()
        return data_check.as_dict(f)

    @app.get("/api/agents/runs")
    def agent_runs(db: Session = Depends(get_db), _=Depends(manager_only)):
        runs = db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(20))
        return [{"id": r.id, "at": r.created_at.isoformat(), "agent": r.agent, "source": r.source,
                 **json.loads(r.summary)} for r in runs]
