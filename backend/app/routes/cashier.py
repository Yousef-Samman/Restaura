"""Routes: the menu, suggestions, orders and payment at the cashier."""
import datetime as dt

from fastapi import Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import sales_report, stock
from ..agents import cashier
from ..agents.stock_agent import split_change
from ..models import Ingredient, MenuItem, Order, OrderLine, PurchaseOrder, RecipeLine, SuggestionEvent
from ..seed import STORE_UTC_OFFSET
from ..schemas import CartLine, Cart


def register(app, c):
    llm, get_db, staff, manager_only, staff_id = c.llm, c.get_db, c.staff, c.manager_only, c.staff_id

    def load_cart(db: Session, lines: list[CartLine]) -> list[tuple[MenuItem, int]]:
        cart = []
        for line in lines:
            item = db.get(MenuItem, line.item_id)
            if not item:
                raise HTTPException(404, f"Menu item {line.item_id} not found")
            cart.append((item, line.qty))
        return cart

    # ---- cashier -----------------------------------------------------------
    @app.get("/api/menu")
    def menu(db: Session = Depends(get_db), _=Depends(staff)):
        items = db.scalars(select(MenuItem).options(selectinload(MenuItem.recipe).selectinload(RecipeLine.ingredient))
                           .order_by(MenuItem.id)).all()
        since = dt.date.today() - dt.timedelta(days=14)
        sold = dict(db.execute(select(OrderLine.menu_item_id, func.sum(OrderLine.qty)).join(Order)
                               .where(Order.business_date >= since).group_by(OrderLine.menu_item_id)).all())
        popular = {i for i, _ in sorted(sold.items(), key=lambda kv: kv[1], reverse=True)[:3]}
        return [{"id": i.id, "name": i.name, "category": i.category, "price": i.price, "is_addon": i.is_addon,
                 "available": stock.item_available(i), "popular": i.id in popular} for i in items]

    @app.get("/api/today")
    def today(db: Session = Depends(get_db), _=Depends(staff)):
        d = dt.date.today()
        orders, sales = db.execute(select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
                                   .where(Order.business_date == d, Order.source != "history")).one()
        # timestamps are stored in UTC, so the store's day starts at local midnight minus the offset
        start = dt.datetime.combine(d, dt.time()) - STORE_UTC_OFFSET
        shown = db.scalar(select(func.count(SuggestionEvent.id)).where(SuggestionEvent.created_at >= start)) or 0
        # count and value come from the same sold lines, so they always agree
        accepted, addon_sales = db.execute(select(func.coalesce(func.sum(OrderLine.qty), 0),
                                                  func.coalesce(func.sum(OrderLine.price * OrderLine.qty), 0)).join(Order)
                                           .where(Order.business_date == d, OrderLine.from_suggestion)).one()
        report = stock.stock_report(db)
        return {"date": d.isoformat(), "orders": orders, "sales": round(sales, 2),
                "avg_ticket": round(sales / orders, 2) if orders else 0,
                "suggestions_shown": shown, "suggestions_accepted": accepted, "suggested_sales": round(addon_sales, 2),
                # what still needs the manager: an ingredient with an order on the way is handled, unless it is below zero
                "low_stock": sum(r["status"] == "negative" or (r["status"] == "low" and not r["on_order"]) for r in report),
                "drafts": db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "draft")) or 0,
                # drafts where the stock agent changed a quantity: the manager should look at these first
                "changed_drafts": sum(any(split_change(l.reason)[1] for l in po.lines)
                                      for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")))}

    @app.post("/api/cashier/suggest")
    def suggest(cart: Cart, db: Session = Depends(get_db), user=Depends(staff)):
        return cashier.suggest(db, llm, load_cart(db, cart.lines), staff_id=staff_id(user))

    @app.post("/api/orders")
    def place_order(cart: Cart, db: Session = Depends(get_db), user=Depends(staff)):
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
        order = Order(business_date=dt.date.today(), source="cashier", total=sum(i.price * q for i, q in items),
                      staff_id=staff_id(user), seconds_to_pay=cart.seconds_to_pay, removed_items=cart.removed_items,
                      payment=cart.payment)
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
    async def import_sales(file: UploadFile, business_date: dt.date | None = None, db: Session = Depends(get_db), _=Depends(manager_only)):
        """Daily sales report from the POS as CSV with columns item,qty. Sales already happened,
        so stock may go below zero; the stock agent then flags a missing delivery."""
        by_name = {i.name.lower(): i for i in db.scalars(select(MenuItem))}
        try:
            items = sales_report.parse(await file.read(), by_name)
        except sales_report.ReportError as exc:
            raise HTTPException(400, str(exc))
        order = Order(business_date=business_date or dt.date.today(), source="import",
                      total=sum(i.price * q for i, q in items))
        order.lines = [OrderLine(menu_item_id=i.id, qty=q, price=i.price) for i, q in items]
        db.add(order)
        db.flush()
        stock.consume(db, items, ref=f"POS import {order.business_date}")
        db.commit()
        return {"order_id": order.id, "lines": len(items), "total": order.total}

    @app.get("/api/sales/summary")
    def sales_summary(days: int = 14, db: Session = Depends(get_db), _=Depends(manager_only)):
        days = max(1, min(days, 90))
        today_d = dt.date.today()
        since = today_d - dt.timedelta(days=days - 1)
        daily = dict(db.execute(select(Order.business_date, func.sum(Order.total)).where(Order.business_date >= since)
                                .group_by(Order.business_date)).all())
        counts = dict(db.execute(select(Order.business_date, func.count(Order.id)).where(Order.business_date >= since)
                                 .group_by(Order.business_date)).all())
        helper = dict(db.execute(select(Order.business_date, func.sum(OrderLine.price * OrderLine.qty)).join(Order)
                                 .where(Order.business_date >= since, OrderLine.from_suggestion)
                                 .group_by(Order.business_date)).all())
        dates = [since + dt.timedelta(days=i) for i in range(days)]
        top = db.execute(select(MenuItem.name, func.sum(OrderLine.qty), func.sum(OrderLine.qty * OrderLine.price))
                         .join(OrderLine).join(Order).where(Order.business_date >= since)
                         .group_by(MenuItem.name).order_by(func.sum(OrderLine.qty * OrderLine.price).desc()).limit(6)).all()
        cats = db.execute(select(MenuItem.category, func.sum(OrderLine.qty * OrderLine.price)).join(OrderLine).join(Order)
                          .where(Order.business_date >= since).group_by(MenuItem.category)
                          .order_by(func.sum(OrderLine.qty * OrderLine.price).desc())).all()
        today_orders = db.execute(select(Order.created_at, Order.total)
                                  .where(Order.business_date == today_d, Order.source == "cashier")).all()
        # imported POS reports have no time of day, so they are left out of the hourly view
        timed = db.execute(select(Order.created_at, Order.total)
                           .where(Order.business_date >= since, Order.source != "import")).all()
        return {
            "daily": [{"date": d.isoformat(), "sales": round(daily.get(d, 0), 2), "orders": counts.get(d, 0),
                       "helper_sales": round(helper.get(d, 0), 2)} for d in dates],
            "top_items": [{"name": n, "qty": q, "sales": round(v, 2)} for n, q, v in top],
            "categories": [{"category": c, "sales": round(v, 2)} for c, v in cats],
            "today_orders": [{"at": a.isoformat() + "Z", "total": t} for a, t in today_orders],
            # hour of day in store time, so the chart is right whatever the viewer's time zone
            "period_orders": [{"at": a.isoformat() + "Z", "hour": (a + STORE_UTC_OFFSET).hour, "total": t} for a, t in timed],
        }
