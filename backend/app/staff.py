"""Staff shifts and attendance. Staff clock in and out on the cashier iPad with a 4-digit PIN;
the manager sees who is on shift, who is late or missing, and hours worked."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth
from .models import Attendance, Shift, StaffMember
from .routines import local_now

LATE_AFTER = dt.timedelta(minutes=10)


def _span(date: dt.date, start: dt.time, end: dt.time) -> tuple[dt.datetime, dt.datetime]:
    a = dt.datetime.combine(date, start)
    b = dt.datetime.combine(date, end)
    return a, b if b > a else b + dt.timedelta(days=1)


def clock(db: Session, pin: str) -> dict:
    """Clock in, or out if already in. Returns None when no one has this PIN."""
    member = next((m for m in db.scalars(select(StaffMember).where(StaffMember.active)) if auth.verify_password(pin, m.pin_hash)), None)
    if not member:
        return None
    now = local_now()
    open_ = db.scalar(select(Attendance).where(Attendance.staff_id == member.id, Attendance.clock_out.is_(None)))
    if open_:
        open_.clock_out = now
        return {"name": member.name, "action": "out", "at": now.strftime("%H:%M"), "hours": round((now - open_.clock_in).total_seconds() / 3600, 1)}
    db.add(Attendance(staff_id=member.id, date=now.date(), clock_in=now))
    return {"name": member.name, "action": "in", "at": now.strftime("%H:%M")}


def on_shift(db: Session) -> list[str]:
    return [a.staff.name for a in db.scalars(select(Attendance).where(Attendance.clock_out.is_(None)))]


def today_view(db: Session) -> dict:
    now = local_now()
    d = now.date()
    shifts = db.scalars(select(Shift).where(Shift.date == d).order_by(Shift.start)).all()
    att = {a.staff_id: a for a in db.scalars(select(Attendance).where(Attendance.date == d))}
    rows = []
    for s in shifts:
        start, end = _span(s.date, s.start, s.end)
        a = att.get(s.staff_id)
        if a:
            status = "late" if a.clock_in > start + LATE_AFTER else "on_time"
            if a.clock_out:
                status = "done" if status == "on_time" else "late"
        else:
            status = "missing" if now > start + LATE_AFTER else "upcoming"
        rows.append({"staff": s.staff.name, "role": s.staff.role, "start": s.start.strftime("%H:%M"), "end": s.end.strftime("%H:%M"),
                     "status": status, "clock_in": a.clock_in.strftime("%H:%M") if a else None,
                     "clock_out": a.clock_out.strftime("%H:%M") if a and a.clock_out else None,
                     "late_min": max(0, round((a.clock_in - start).total_seconds() / 60)) if a else None, "in_now": bool(a and not a.clock_out)})
    return {"date": d.isoformat(), "shifts": rows, "on_shift": on_shift(db)}


def week(db: Session) -> dict:
    """Saudi work week: Sunday to Saturday, containing today."""
    today = local_now().date()
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    days = [sunday + dt.timedelta(days=i) for i in range(7)]
    staff = db.scalars(select(StaffMember).where(StaffMember.active).order_by(StaffMember.name)).all()
    shifts = db.scalars(select(Shift).where(Shift.date >= days[0], Shift.date <= days[-1])).all()
    since = today - dt.timedelta(days=7)
    worked = {m.id: 0.0 for m in staff}
    late = {m.id: 0 for m in staff}
    for a in db.scalars(select(Attendance).where(Attendance.date >= since, Attendance.date < today, Attendance.clock_out.is_not(None))):
        worked[a.staff_id] = worked.get(a.staff_id, 0) + (a.clock_out - a.clock_in).total_seconds() / 3600
        s = db.scalar(select(Shift).where(Shift.staff_id == a.staff_id, Shift.date == a.date))
        if s and a.clock_in > _span(s.date, s.start, s.end)[0] + LATE_AFTER:
            late[a.staff_id] = late.get(a.staff_id, 0) + 1
    grid = {(s.staff_id, s.date): f"{s.start.strftime('%H:%M')}–{s.end.strftime('%H:%M')}" for s in shifts}
    return {
        "days": [d.isoformat() for d in days],
        "staff": [{"id": m.id, "name": m.name, "role": m.role, "shifts": [grid.get((m.id, d)) for d in days],
                   "hours_7d": round(worked.get(m.id, 0), 1), "late_7d": late.get(m.id, 0)} for m in staff],
    }
