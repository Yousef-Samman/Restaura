"""Routes: sign-in, sign-out and the cashier iPad pairing."""
import datetime as dt

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..models import Device, StaffMember
from ..schemas import Login, StaffLogin, PairStart, PairCode


def register(app, c):
    get_db, manager_only, cookie, guarded, who = c.get_db, c.manager_only, c.cookie, c.guarded, c.who

    # ---- accounts and devices --------------------------------------------------
    @app.post("/api/auth/login")
    def do_login(body: Login, request: Request, response: Response, db: Session = Depends(get_db)):
        token, user = guarded(f"login:{body.username.strip().lower()}:{who(request)}",
                              lambda: auth.login(db, body.username, body.password, request.cookies.get(auth.DEVICE_COOKIE)))
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_HOURS * 3600, **cookie)
        return {"name": user.name, "role": user.role, "home": "/cashier" if user.role == "cashier" else "/manager"}

    @app.get("/api/auth/demo")
    def demo_info():
        """What the sign-in page shows in demo mode: one-tap buttons and the demo logins."""
        s = c.settings
        return {"enabled": s.demo_mode, "manager_password": s.manager_password, "cashier_password": s.cashier_password,
                "staff_pins": "1111 to 5555"} if s.demo_mode else {"enabled": False}

    @app.post("/api/auth/demo/{role}")
    def demo_sign_in(role: str, request: Request, response: Response, db: Session = Depends(get_db)):
        if not c.settings.demo_mode:
            raise HTTPException(404, "Demo mode is off")
        if role not in ("manager", "cashier"):
            raise HTTPException(404, "Unknown role")
        token, user, new_device = auth.demo_login(db, role, request.cookies.get(auth.DEVICE_COOKIE))
        if new_device:
            response.set_cookie(auth.DEVICE_COOKIE, new_device, max_age=5 * 365 * 24 * 3600, **cookie)
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_HOURS * 3600, **cookie)
        return {"name": user.name, "role": user.role, "home": "/cashier" if user.role == "cashier" else "/manager"}

    @app.get("/api/auth/staff")
    def staff_names(request: Request, db: Session = Depends(get_db)):
        """Names for the sign-in screen, only on the paired cashier iPad."""
        if not auth.device_from_cookie(db, request.cookies.get(auth.DEVICE_COOKIE)):
            raise HTTPException(403, "This device is not the store's cashier iPad")
        return [{"id": m.id, "name": m.name, "role": m.role}
                for m in db.scalars(select(StaffMember).where(StaffMember.active).order_by(StaffMember.name))]

    @app.post("/api/auth/staff-login")
    def do_staff_login(body: StaffLogin, request: Request, response: Response, db: Session = Depends(get_db)):
        token, user = guarded(f"staff:{body.staff_id}:{who(request)}",
                              lambda: auth.staff_login(db, body.staff_id, body.pin, request.cookies.get(auth.DEVICE_COOKIE)))
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_HOURS * 3600, **cookie)
        return {"name": user.name, "role": user.role, "home": "/cashier"}

    @app.post("/api/auth/logout")
    def do_logout(request: Request, response: Response, db: Session = Depends(get_db)):
        auth.logout(db, request.cookies.get(auth.SESSION_COOKIE))
        response.delete_cookie(auth.SESSION_COOKIE)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(request: Request, db: Session = Depends(get_db)):
        user = auth.current_user(db, request)
        device = auth.device_from_cookie(db, request.cookies.get(auth.DEVICE_COOKIE))
        return {"user": {"name": user.name, "role": user.role} if user else None,
                "device": {"name": device.name} if device else None}

    @app.get("/api/devices")
    def devices(db: Session = Depends(get_db), _=Depends(manager_only)):
        return [{"id": d.id, "name": d.name, "paired": d.paired_at is not None, "revoked": d.revoked,
                 "paired_at": d.paired_at.isoformat() if d.paired_at else None}
                for d in db.scalars(select(Device).where(Device.revoked.is_(False)).order_by(Device.id.desc()))
                if d.paired_at or (d.pairing_expires and d.pairing_expires > dt.datetime.now(dt.UTC).replace(tzinfo=None))]

    @app.post("/api/devices")
    def pair_start(body: PairStart, db: Session = Depends(get_db), _=Depends(manager_only)):
        dev = auth.start_pairing(db, body.name)
        return {"id": dev.id, "name": dev.name, "code": dev.pairing_code, "minutes": auth.PAIRING_MINUTES}

    @app.post("/api/devices/{device_id}/revoke")
    def revoke(device_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        dev = db.get(Device, device_id)
        if not dev:
            raise HTTPException(404, "Device not found")
        dev.revoked = True
        db.commit()
        return {"ok": True}

    @app.post("/api/devices/pair")
    def pair_complete(body: PairCode, request: Request, response: Response, db: Session = Depends(get_db)):
        token, dev = guarded(f"pair:{who(request)}", lambda: auth.complete_pairing(db, body.code))
        response.set_cookie(auth.DEVICE_COOKIE, token, max_age=5 * 365 * 24 * 3600, **cookie)
        return {"name": dev.name}
