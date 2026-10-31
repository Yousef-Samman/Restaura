"""Routes: status, insights, the evaluation page and the HTML pages."""
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, evaluation
from ..models import MenuItem, OrderLine, SuggestionEvent


STATIC = Path(__file__).resolve().parent.parent / "static"


def register(app, c):
    settings, llm, get_db, manager_only = c.settings, c.llm, c.get_db, c.manager_only

    # ---- status ------------------------------------------------------------
    @app.get("/api/status")
    def status():
        return {"store": settings.store_name, "ai_enabled": llm.enabled, "model": settings.model if llm.enabled else None,
                "email": "smtp" if settings.smtp_host else "log only", "mail_server": settings.smtp_host}

    # ---- insights --------------------------------------------------------------
    @app.get("/api/insights/cashier")
    def cashier_insights(db: Session = Depends(get_db), _=Depends(manager_only)):
        shown = db.scalar(select(func.count(SuggestionEvent.id))) or 0
        accepted = db.scalar(select(func.count(SuggestionEvent.id)).where(SuggestionEvent.accepted)) or 0
        revenue = db.scalar(select(func.sum(OrderLine.price * OrderLine.qty)).where(OrderLine.from_suggestion)) or 0
        top = db.execute(select(MenuItem.name, func.count(SuggestionEvent.id)).join(MenuItem)
                         .where(SuggestionEvent.accepted).group_by(MenuItem.name)
                         .order_by(func.count(SuggestionEvent.id).desc()).limit(5)).all()
        return {"shown": shown, "accepted": accepted, "acceptance_rate": round(accepted / shown, 3) if shown else None,
                "added_revenue": round(revenue, 2), "top_accepted": [{"name": n, "count": c} for n, c in top]}

    # ---- agent evaluation ------------------------------------------------------
    runner = evaluation.Runner(settings.eval_results)

    @app.get("/api/evaluation")
    def get_evaluation(_=Depends(manager_only)):
        r = evaluation.load(settings.eval_results)
        return {"running": runner.running, "error": runner.error, "results": evaluation.view(r) if r else None}

    @app.post("/api/evaluation/run")
    def run_evaluation(_=Depends(manager_only)):
        if not runner.start():
            raise HTTPException(409, "The checks are already running")
        return {"running": True}

    # ---- web app ---------------------------------------------------------------
    def page(name: str, role: str | None):
        def view(request: Request, db: Session = Depends(get_db)):
            user = auth.current_user(db, request)
            if role and (not user or user.role != role):
                return RedirectResponse("/login")
            return FileResponse(STATIC / name)
        return view

    @app.get("/")
    def index(request: Request, db: Session = Depends(get_db)):
        user = auth.current_user(db, request)
        return RedirectResponse({"cashier": "/cashier", "manager": "/manager"}.get(user.role if user else "", "/login"))

    app.get("/login")(page("login.html", None))
    app.get("/cashier")(page("cashier.html", "cashier"))
    app.get("/manager")(page("manager.html", "manager"))
