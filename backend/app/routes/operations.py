"""Routes: routines, the manager overview, forecast and expenses."""
import datetime as dt

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import finance, forecast, routines
from ..agents import overview
from ..models import Expense, RoutineTask, SpecialDay
from ..schemas import SpecialDayIn, ExpenseIn, TaskToggle, TaskIn


def register(app, c):
    llm, get_db, staff, manager_only = c.llm, c.get_db, c.staff, c.manager_only

    # ---- routines (daily checklists) ---------------------------------------------------
    @app.get("/api/routines")
    def get_routines(db: Session = Depends(get_db), _=Depends(staff)):
        return routines.today_view(db)

    @app.post("/api/routines/tasks/{task_id}/toggle")
    def toggle_task(task_id: int, body: TaskToggle, db: Session = Depends(get_db), user=Depends(staff)):
        if not db.get(RoutineTask, task_id):
            raise HTTPException(404, "Task not found")
        done = routines.toggle(db, task_id, body.done_by or user.name)
        db.commit()
        return {"done": done}

    @app.get("/api/routines/history")
    def routine_history(days: int = 7, db: Session = Depends(get_db), _=Depends(manager_only)):
        return routines.history(db, max(1, min(days, 30)))

    @app.post("/api/routines/tasks")
    def add_task(body: TaskIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        t = RoutineTask(routine=body.routine, text=body.text, position=99)
        db.add(t)
        db.commit()
        return {"id": t.id}

    @app.delete("/api/routines/tasks/{task_id}")
    def remove_task(task_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        t = db.get(RoutineTask, task_id)
        if not t:
            raise HTTPException(404, "Task not found")
        t.active = False
        db.commit()
        return {"removed": task_id}

    # ---- manager overview ------------------------------------------------------------
    @app.get("/api/overview")
    def get_overview(db: Session = Depends(get_db), _=Depends(manager_only)):
        f = overview.facts(db)
        return {"facts": f, "priorities": overview.priorities(f)}

    @app.post("/api/agents/overview/run")
    def run_overview(db: Session = Depends(get_db), _=Depends(manager_only)):
        return overview.run(db, llm)

    # ---- forecast ------------------------------------------------------------------
    @app.get("/api/forecast")
    def get_forecast(db: Session = Depends(get_db), _=Depends(manager_only)):
        return forecast.forecast(db, 7)

    @app.post("/api/special-days")
    def add_special_day(body: SpecialDayIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        """Tag a day as not normal. Tagging it again changes its label."""
        day = db.scalar(select(SpecialDay).where(SpecialDay.date == body.date)) or SpecialDay(date=body.date)
        day.label = " ".join(body.label.split())
        db.add(day)
        db.commit()
        return {"id": day.id, "date": day.date.isoformat(), "label": day.label}

    @app.delete("/api/special-days/{day_id}")
    def remove_special_day(day_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        day = db.get(SpecialDay, day_id)
        if not day:
            raise HTTPException(404, "Special day not found")
        db.delete(day)
        db.commit()
        return {"removed": day_id}

    # ---- expenses and profit ------------------------------------------------------
    @app.get("/api/expenses")
    def expenses(days: int = 30, db: Session = Depends(get_db), _=Depends(manager_only)):
        return finance.summary(db, max(1, min(days, 90)))

    @app.post("/api/expenses")
    def add_expense(body: ExpenseIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        e = Expense(kind=body.kind, category=body.category, amount=body.amount, note=body.note,
                    date=body.date or dt.date.today())
        db.add(e)
        db.commit()
        return {"id": e.id}

    @app.delete("/api/expenses/{expense_id}")
    def delete_expense(expense_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        e = db.get(Expense, expense_id)
        if not e or e.kind == "purchase":
            raise HTTPException(404, "Expense not found")
        db.delete(e)
        db.commit()
        return {"deleted": expense_id}
