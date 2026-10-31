"""Routes: clock-in, shifts and the staff coach."""
import datetime as dt
import json
from .. import staff as staffing

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, routines
from ..agents import staff_agent
from ..models import AgentRun, Shift, StaffMember, StaffReview, StaffTip
from ..schemas import ReviewIn, ClockIn, StaffIn, ShiftIn


def register(app, c):
    llm, get_db, staff, manager_only, staff_id, guarded, who = c.llm, c.get_db, c.staff, c.manager_only, c.staff_id, c.guarded, c.who

    # ---- staff and attendance -------------------------------------------------------
    @app.post("/api/staff/clock")
    def clock(body: ClockIn, request: Request, db: Session = Depends(get_db), _=Depends(staff)):
        def attempt():
            r = staffing.clock(db, body.pin)
            if not r:
                raise HTTPException(404, "PIN not recognised")
            return r
        r = guarded(f"clock:{who(request)}", attempt)
        db.commit()
        return r

    @app.get("/api/staff/on-shift")
    def on_shift(db: Session = Depends(get_db), _=Depends(staff)):
        return staffing.on_shift(db)

    @app.get("/api/staff/today")
    def staff_today(db: Session = Depends(get_db), _=Depends(manager_only)):
        return staffing.today_view(db)

    @app.get("/api/staff/week")
    def staff_week(db: Session = Depends(get_db), _=Depends(manager_only)):
        return staffing.week(db)

    # ---- the staff coach: weekly measures, the manager's weekly review and one tip per person ----------
    @app.get("/api/staff/coach")
    def staff_coach(db: Session = Depends(get_db), _=Depends(manager_only)):
        last = db.scalar(select(AgentRun).where(AgentRun.agent == "staff").order_by(AgentRun.id.desc()))
        return staff_agent.overview(db) | {
            "last_run": {"at": last.created_at.isoformat() + "Z", "source": last.source,
                         "headline": json.loads(last.summary)["headline"]} if last else None}

    @app.get("/api/staff/{member_id}/coach")
    def staff_coach_person(member_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        p = next((p for p in staff_agent.overview(db)["people"] if p["id"] == member_id), None)
        if not p:
            raise HTTPException(404, "Staff member not found")
        tips = db.scalars(select(StaffTip).where(StaffTip.staff_id == member_id).order_by(StaffTip.id.desc()).limit(6))
        reviews = db.scalars(select(StaffReview).where(StaffReview.staff_id == member_id)
                             .order_by(StaffReview.week_start.desc()).limit(6))
        return p | {
            "tips": [{"tip": t.tip, "why": t.why, "label": staff_agent.FOCUS[t.focus][0], "at": t.created_at.isoformat() + "Z",
                      "seen": t.seen_at is not None, "result": staff_agent.tip_result(db, t)} for t in tips],
            "reviews": [{"week_start": r.week_start.isoformat(), "quality": r.quality, "speed": r.speed,
                         "cleanliness": r.cleanliness, "teamwork": r.teamwork, "note": r.note} for r in reviews]}

    @app.post("/api/staff/{member_id}/review")
    def save_review(member_id: int, body: ReviewIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        """The manager's review for this week. Saving again in the same week replaces it."""
        if not db.get(StaffMember, member_id):
            raise HTTPException(404, "Staff member not found")
        week = staff_agent.week_start(routines.local_now().date())
        r = db.scalar(select(StaffReview).where(StaffReview.staff_id == member_id, StaffReview.week_start == week))
        if not r:
            r = StaffReview(staff_id=member_id, week_start=week)
            db.add(r)
        r.quality, r.speed, r.cleanliness, r.teamwork = body.quality, body.speed, body.cleanliness, body.teamwork
        r.note = (body.note or "").strip() or None
        db.commit()
        return {"saved": True, "week_start": week.isoformat()}

    @app.post("/api/agents/staff/run")
    def run_staff_agent(db: Session = Depends(get_db), _=Depends(manager_only)):
        return staff_agent.run(db, llm)

    @app.get("/api/me/tip")
    def my_tip(db: Session = Depends(get_db), user=Depends(staff)):
        """The latest tip for the signed-in staff member, shown once after the PIN until they tap Got it."""
        sid = staff_id(user)
        t = sid and db.scalar(select(StaffTip).where(StaffTip.staff_id == sid).order_by(StaffTip.id.desc()))
        if not t or t.seen_at:
            return {"tip": None}
        prev = db.scalar(select(StaffTip).where(StaffTip.staff_id == sid, StaffTip.id < t.id).order_by(StaffTip.id.desc()))
        return {"tip": {"id": t.id, "tip": t.tip, "why": t.why, "label": staff_agent.FOCUS[t.focus][0]},
                "previous": {"label": staff_agent.FOCUS[prev.focus][0], "result": staff_agent.tip_result(db, prev)} if prev else None}

    @app.post("/api/me/tip/{tip_id}/seen")
    def tip_seen(tip_id: int, db: Session = Depends(get_db), user=Depends(staff)):
        t = db.get(StaffTip, tip_id)
        if not t or t.staff_id != staff_id(user):
            raise HTTPException(404, "Tip not found")
        t.seen_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        db.commit()
        return {"ok": True}

    @app.post("/api/staff")
    def add_staff(body: StaffIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        if any(auth.verify_password(body.pin, m.pin_hash) for m in db.scalars(select(StaffMember).where(StaffMember.active))):
            raise HTTPException(409, "Someone already uses this PIN")
        m = StaffMember(name=body.name, role=body.role, pin_hash=auth.hash_password(body.pin))
        db.add(m)
        db.commit()
        return {"id": m.id}

    @app.post("/api/shifts")
    def add_shift(body: ShiftIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        if not db.get(StaffMember, body.staff_id):
            raise HTTPException(404, "Staff member not found")
        old = db.scalar(select(Shift).where(Shift.staff_id == body.staff_id, Shift.date == body.date))
        if old:
            db.delete(old)
        db.add(Shift(staff_id=body.staff_id, date=body.date, start=body.start, end=body.end))
        db.commit()
        return {"ok": True}
