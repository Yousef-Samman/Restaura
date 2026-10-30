import datetime as dt
import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import mailer, stock
from .agents import cashier, invoice, stock_agent
from .agents.llm import LLM
from .config import Settings, get_settings
from .db import Base, make_engine, make_sessionmaker
from .models import (AgentRun, Ingredient, MenuItem, Order, OrderLine, Outbox, PurchaseOrder,
                     PurchaseOrderLine, RecipeLine, SuggestionEvent)
from .seed import seed

STATIC = Path(__file__).parent / "static"


class CartLine(BaseModel):
    item_id: int
    qty: int = Field(1, ge=1)
    suggestion_event_id: int | None = None


class Cart(BaseModel):
    lines: list[CartLine]


class ReceiveLine(BaseModel):
    ingredient_id: int
    qty: float = Field(gt=0)


class Receive(BaseModel):
    lines: list[ReceiveLine]
    invoice_ref: str | None = None


class CountLine(BaseModel):
    ingredient_id: int
    counted: float = Field(ge=0)


class EditLine(BaseModel):
    line_id: int
    qty: float = Field(ge=0)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Session_ = make_sessionmaker(engine)
    Base.metadata.create_all(engine)
    if settings.seed_demo_data:
        with Session_() as db:
            seed(db)
    llm = LLM(settings)
    app = FastAPI(title="Restaura", version="0.1.0")

    def get_db():
        with Session_() as db:
            yield db

    def load_cart(db: Session, lines: list[CartLine]) -> list[tuple[MenuItem, int]]:
        cart = []
        for line in lines:
            item = db.get(MenuItem, line.item_id)
            if not item:
                raise HTTPException(404, f"Menu item {line.item_id} not found")
            cart.append((item, line.qty))
        return cart

    # ---- status ------------------------------------------------------------
    @app.get("/api/status")
    def status():
        return {"store": settings.store_name, "ai_enabled": llm.enabled, "model": settings.model if llm.enabled else None,
                "email": "smtp" if settings.smtp_host else "log only"}

    # ---- cashier -----------------------------------------------------------
    @app.get("/api/menu")
    def menu(db: Session = Depends(get_db)):
        items = db.scalars(select(MenuItem).options(selectinload(MenuItem.recipe).selectinload(RecipeLine.ingredient))
                           .order_by(MenuItem.id)).all()
        since = dt.date.today() - dt.timedelta(days=14)
        sold = dict(db.execute(select(OrderLine.menu_item_id, func.sum(OrderLine.qty)).join(Order)
                               .where(Order.business_date >= since).group_by(OrderLine.menu_item_id)).all())
        popular = {i for i, _ in sorted(sold.items(), key=lambda kv: kv[1], reverse=True)[:3]}
        return [{"id": i.id, "name": i.name, "category": i.category, "price": i.price, "is_addon": i.is_addon,
                 "available": stock.item_available(i), "popular": i.id in popular} for i in items]

    @app.get("/api/today")
    def today(db: Session = Depends(get_db)):
        d = dt.date.today()
        orders, sales = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                                   .where(Order.business_date == d, Order.source != "history")).one()
        start = dt.datetime.combine(d, dt.time())
        shown = db.scalar(select(func.count(SuggestionEvent.id)).where(SuggestionEvent.created_at >= start)) or 0
        accepted = db.scalar(select(func.count(SuggestionEvent.id))
                             .where(SuggestionEvent.created_at >= start, SuggestionEvent.accepted)) or 0
        addon_sales = db.scalar(select(func.coalesce(func.sum(OrderLine.price * OrderLine.qty), 0)).join(Order)
                                .where(Order.business_date == d, OrderLine.from_suggestion)) or 0
        report = stock.stock_report(db)
        return {"date": d.isoformat(), "orders": orders, "sales": round(sales, 2),
                "avg_ticket": round(sales / orders, 2) if orders else 0,
                "suggestions_shown": shown, "suggestions_accepted": accepted, "suggested_sales": round(addon_sales, 2),
                "low_stock": sum(r["status"] != "ok" for r in report),
                "drafts": db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "draft")) or 0}

    @app.post("/api/cashier/suggest")
    def suggest(cart: Cart, db: Session = Depends(get_db)):
        return cashier.suggest(db, llm, load_cart(db, cart.lines))

    @app.post("/api/orders")
    def place_order(cart: Cart, db: Session = Depends(get_db)):
        if not cart.lines:
            raise HTTPException(400, "Order is empty")
        items = load_cart(db, cart.lines)
        use: dict[int, float] = {}
        for item, qty in items:
            for r in item.recipe:
                use[r.ingredient_id] = use.get(r.ingredient_id, 0) + r.qty * qty
        short = [db.get(Ingredient, i).name for i, q in use.items() if db.get(Ingredient, i).on_hand < q]
        if short:
            raise HTTPException(409, f"Not enough stock for this order: {', '.join(short)}")
        order = Order(business_date=dt.date.today(), source="cashier", total=sum(i.price * q for i, q in items))
        order.lines = [OrderLine(menu_item_id=i.id, qty=q, price=i.price, from_suggestion=l.suggestion_event_id is not None)
                       for (i, q), l in zip(items, cart.lines)]
        db.add(order)
        db.flush()
        stock.consume(db, items, ref=f"order {order.id}")
        for l in cart.lines:
            if l.suggestion_event_id and (ev := db.get(SuggestionEvent, l.suggestion_event_id)):
                ev.accepted, ev.order_id = True, order.id
        db.commit()
        return {"order_id": order.id, "total": order.total}

    @app.post("/api/sales/import")
    async def import_sales(file: UploadFile, business_date: dt.date | None = None, db: Session = Depends(get_db)):
        """Daily sales report from the POS as CSV with columns item,qty. Sales already happened,
        so stock may go below zero; the stock agent then flags a missing delivery."""
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig"))))
        by_name = {i.name.lower(): i for i in db.scalars(select(MenuItem))}
        unknown = [r.get("item", "") for r in rows if r.get("item", "").strip().lower() not in by_name]
        if unknown:
            raise HTTPException(400, f"Items not on the menu: {', '.join(unknown)}")
        items = [(by_name[r["item"].strip().lower()], int(r["qty"])) for r in rows]
        order = Order(business_date=business_date or dt.date.today(), source="import",
                      total=sum(i.price * q for i, q in items))
        order.lines = [OrderLine(menu_item_id=i.id, qty=q, price=i.price) for i, q in items]
        db.add(order)
        db.flush()
        stock.consume(db, items, ref=f"POS import {order.business_date}")
        db.commit()
        return {"order_id": order.id, "lines": len(items), "total": order.total}

    # ---- stock and the stock-to-order agent ----------------------------------
    @app.get("/api/stock")
    def get_stock(db: Session = Depends(get_db)):
        return stock.stock_report(db)

    @app.post("/api/stock/count")
    def stock_count(lines: list[CountLine], db: Session = Depends(get_db)):
        diffs = {db.get(Ingredient, l.ingredient_id).name: round(stock.count(db, l.ingredient_id, l.counted), 1) for l in lines}
        db.commit()
        return {"adjustments": diffs}

    @app.post("/api/agents/stock/run")
    def run_stock_agent(db: Session = Depends(get_db)):
        return stock_agent.run(db, llm)

    @app.get("/api/agents/runs")
    def agent_runs(db: Session = Depends(get_db)):
        runs = db.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(20))
        return [{"id": r.id, "at": r.created_at.isoformat(), "agent": r.agent, "source": r.source,
                 **json.loads(r.summary)} for r in runs]

    # ---- purchase orders -------------------------------------------------------
    def po_dict(po: PurchaseOrder) -> dict:
        return {"id": po.id, "supplier": po.supplier.name, "status": po.status, "note": po.note,
                "created_at": po.created_at.isoformat(), "sent_at": po.sent_at.isoformat() if po.sent_at else None,
                "lines": [{"id": l.id, "ingredient_id": l.ingredient_id, "ingredient": l.ingredient.name,
                           "unit": l.ingredient.unit, "qty": l.qty, "reason": l.reason,
                           "est_cost": round(l.qty * l.ingredient.unit_cost, 2)} for l in po.lines]}

    def get_po(db: Session, po_id: int) -> PurchaseOrder:
        po = db.get(PurchaseOrder, po_id)
        if not po:
            raise HTTPException(404, "Purchase order not found")
        return po

    @app.get("/api/purchase-orders")
    def list_pos(db: Session = Depends(get_db)):
        return [po_dict(po) for po in db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()))]

    @app.post("/api/purchase-orders/{po_id}/approve")
    def approve(po_id: int, edits: list[EditLine] | None = None, db: Session = Depends(get_db)):
        po = get_po(db, po_id)
        if po.status != "draft":
            raise HTTPException(409, f"Order is already {po.status}")
        for e in edits or []:
            line = db.get(PurchaseOrderLine, e.line_id)
            if not line or line.purchase_order_id != po.id:
                raise HTTPException(400, f"Line {e.line_id} is not on this order")
            if e.qty == 0:
                db.delete(line)
            else:
                line.qty = e.qty
        db.flush()
        db.refresh(po)
        if not po.lines:
            raise HTTPException(400, "Order has no lines left")
        body = "\n".join([f"Hello {po.supplier.name},", "", f"Please deliver the following to {settings.store_name}:", ""]
                         + [f"- {l.ingredient.name}: {l.qty:g} {l.ingredient.unit}" for l in po.lines]
                         + ["", f"Purchase order #{po.id}. Thank you.", settings.store_name])
        mail = mailer.send(db, settings, po.supplier.email or "", f"Purchase order #{po.id} from {settings.store_name}", body)
        po.status, po.sent_at = "sent", dt.datetime.now(dt.UTC).replace(tzinfo=None)
        db.commit()
        return po_dict(po) | {"email": {"to": mail.to, "status": mail.status, "error": mail.error}}

    @app.post("/api/purchase-orders/{po_id}/reject")
    def reject(po_id: int, db: Session = Depends(get_db)):
        po = get_po(db, po_id)
        if po.status != "draft":
            raise HTTPException(409, f"Order is already {po.status}")
        po.status = "rejected"
        db.commit()
        return po_dict(po)

    @app.post("/api/purchase-orders/{po_id}/receive")
    def receive_po(po_id: int, body: Receive, db: Session = Depends(get_db)):
        po = get_po(db, po_id)
        if po.status != "sent":
            raise HTTPException(409, "Only sent orders can be received")
        for l in body.lines:
            stock.receive(db, l.ingredient_id, l.qty, ref=body.invoice_ref or f"PO {po.id}")
        po.status = "received"
        db.commit()
        return po_dict(po)

    @app.post("/api/deliveries")
    def manual_delivery(body: Receive, db: Session = Depends(get_db)):
        for l in body.lines:
            if not db.get(Ingredient, l.ingredient_id):
                raise HTTPException(404, f"Ingredient {l.ingredient_id} not found")
            stock.receive(db, l.ingredient_id, l.qty, ref=body.invoice_ref or "manual delivery")
        db.commit()
        return {"received": len(body.lines)}

    @app.post("/api/invoices/read")
    async def read_invoice(file: UploadFile, db: Session = Depends(get_db)):
        if not llm.enabled:
            raise HTTPException(503, "Reading invoice photos needs the AI key. Enter the delivery manually instead.")
        if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise HTTPException(415, "Upload a JPEG, PNG, WebP or GIF photo")
        out = invoice.read(db, llm, await file.read(), file.content_type)
        if out is None:
            raise HTTPException(502, "The invoice could not be read. Enter the delivery manually instead.")
        return out

    @app.get("/api/outbox")
    def outbox(db: Session = Depends(get_db)):
        return [{"id": m.id, "at": m.created_at.isoformat(), "to": m.to, "subject": m.subject, "body": m.body,
                 "status": m.status, "error": m.error} for m in db.scalars(select(Outbox).order_by(Outbox.id.desc()))]

    # ---- insights --------------------------------------------------------------
    @app.get("/api/insights/cashier")
    def cashier_insights(db: Session = Depends(get_db)):
        shown = db.scalar(select(func.count(SuggestionEvent.id))) or 0
        accepted = db.scalar(select(func.count(SuggestionEvent.id)).where(SuggestionEvent.accepted)) or 0
        revenue = db.scalar(select(func.sum(OrderLine.price * OrderLine.qty)).where(OrderLine.from_suggestion)) or 0
        top = db.execute(select(MenuItem.name, func.count(SuggestionEvent.id)).join(MenuItem)
                         .where(SuggestionEvent.accepted).group_by(MenuItem.name)
                         .order_by(func.count(SuggestionEvent.id).desc()).limit(5)).all()
        return {"shown": shown, "accepted": accepted, "acceptance_rate": round(accepted / shown, 3) if shown else None,
                "added_revenue": round(revenue, 2), "top_accepted": [{"name": n, "count": c} for n, c in top]}

    # ---- web app ---------------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC / "cashier.html")

    @app.get("/manager")
    def manager():
        return FileResponse(STATIC / "manager.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app

