import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import auth, nightly
from .agents.llm import LLM
from .config import Settings, get_settings
from .db import Base, make_engine, make_sessionmaker
from .routes import Ctx, register_all
from .routes.web import STATIC
from .seed import seed
from .throttle import Throttle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if not settings.demo_mode and (settings.manager_password == "manager-demo" or settings.cashier_password == "cashier-demo"):
        logging.getLogger("restaura").warning("Demo passwords are in use. Set MANAGER_PASSWORD and CASHIER_PASSWORD before showing the app to anyone.")
    engine = make_engine(settings.database_url)
    Session_ = make_sessionmaker(engine)
    Base.metadata.create_all(engine)
    with Session_() as db:
        auth.seed_users(db, settings.manager_password, settings.cashier_password)
        if settings.seed_demo_data:
            seed(db)
    llm = LLM(settings)
    app = FastAPI(title="Restaura", version="0.1.0")
    if settings.nightly_stock_check:
        stop_nightly = nightly.start(Session_, llm, nightly.parse_time(settings.nightly_stock_check))
        app.add_event_handler("shutdown", stop_nightly.set)

    def get_db():
        with Session_() as db:
            yield db

    def require(*roles: str):
        def dep(request: Request, db: Session = Depends(get_db)):
            user = auth.current_user(db, request)
            if not user:
                raise HTTPException(401, "Please sign in")
            if user.role not in roles:
                raise HTTPException(403, "Your account can't open this")
            return user
        return dep

    staff = require("cashier", "manager")
    manager_only = require("manager")

    def staff_id(user) -> int | None:
        """The staff member behind a cashier account (staff accounts are named staff-<id>)."""
        name = user.username or ""
        return int(name[6:]) if name.startswith("staff-") and name[6:].isdigit() else None
    cookie = dict(httponly=True, samesite="lax", secure=settings.secure_cookies)
    throttle = Throttle()

    def guarded(key: str, attempt):
        """Runs a sign-in or PIN attempt; wrong ones count, and too many lock `key` for a while."""
        throttle.check(key)
        try:
            out = attempt()
        except HTTPException as exc:
            if exc.status_code in (400, 401, 404):
                throttle.fail(key)
            raise
        throttle.clear(key)
        return out

    def who(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    register_all(app, Ctx(settings=settings, llm=llm, Session_=Session_, get_db=get_db, staff=staff, manager_only=manager_only,
                          staff_id=staff_id, cookie=cookie, guarded=guarded, who=who))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
