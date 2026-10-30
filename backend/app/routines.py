"""Daily checklists. Staff tick tasks on the cashier iPad; the manager sees what is done, late or missed."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RoutineCheck, RoutineTask

# sample opening hours: due times are store-local
ROUTINES = {"opening": ("Opening", dt.time(10, 30)), "midday": ("Mid-shift", dt.time(17, 0)), "closing": ("Closing", dt.time(23, 30))}


def local_now() -> dt.datetime:
    return dt.datetime.now()


def today_view(db: Session) -> list[dict]:
    now = local_now()
    d = now.date()
    checks = {c.task_id: c for c in db.scalars(select(RoutineCheck).where(RoutineCheck.date == d))}
    out = []
    for key, (label, due) in ROUTINES.items():
        tasks = db.scalars(select(RoutineTask).where(RoutineTask.routine == key, RoutineTask.active).order_by(RoutineTask.position, RoutineTask.id)).all()
        rows = [{"id": t.id, "text": t.text, "done": t.id in checks,
                 "done_at": checks[t.id].done_at.strftime("%H:%M") if t.id in checks else None,
                 "done_by": checks[t.id].done_by if t.id in checks else None} for t in tasks]
        done = sum(r["done"] for r in rows)
        out.append({"key": key, "label": label, "due": due.strftime("%H:%M"), "tasks": rows, "done": done, "total": len(rows),
                    "overdue": now.time() > due and done < len(rows)})
    return out


def toggle(db: Session, task_id: int, done_by: str | None) -> bool:
    d = local_now().date()
    c = db.scalar(select(RoutineCheck).where(RoutineCheck.date == d, RoutineCheck.task_id == task_id))
    if c:
        db.delete(c)
        return False
    db.add(RoutineCheck(date=d, task_id=task_id, done_by=done_by, done_at=local_now()))
    return True


def history(db: Session, days: int = 7) -> list[dict]:
    """Share of tasks done per routine per day, for the days before today."""
    today = local_now().date()
    totals = {k: len(db.scalars(select(RoutineTask.id).where(RoutineTask.routine == k, RoutineTask.active)).all()) for k in ROUTINES}
    task_routine = dict(db.execute(select(RoutineTask.id, RoutineTask.routine)).all())
    out = []
    for i in range(days, 0, -1):
        d = today - dt.timedelta(days=i)
        done = {k: 0 for k in ROUTINES}
        for c in db.scalars(select(RoutineCheck).where(RoutineCheck.date == d)):
            done[task_routine[c.task_id]] += 1
        out.append({"date": d.isoformat(), **{k: round(done[k] / totals[k], 2) if totals[k] else None for k in ROUTINES}})
    return out
