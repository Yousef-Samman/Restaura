"""Stock arithmetic. Deterministic code owns the numbers; agents explain and decide around them."""
import datetime as dt
import math
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Ingredient, MenuItem, Order, OrderLine, PurchaseOrder, PurchaseOrderLine, RecipeLine, StockMove


def item_available(item: MenuItem, extra_use: dict[int, float] | None = None) -> bool:
    extra_use = extra_use or {}
    return all(r.ingredient.on_hand - extra_use.get(r.ingredient_id, 0) >= r.qty for r in item.recipe)


def consume(db: Session, lines: list[tuple[MenuItem, int]], ref: str) -> None:
    use: dict[int, float] = defaultdict(float)
    for item, qty in lines:
        for r in item.recipe:
            use[r.ingredient_id] += r.qty * qty
    for ing_id, qty in use.items():
        ing = db.get(Ingredient, ing_id)
        ing.on_hand -= qty
        db.add(StockMove(ingredient_id=ing_id, qty=-qty, kind="sale", ref=ref))


def receive(db: Session, ingredient_id: int, qty: float, ref: str) -> None:
    ing = db.get(Ingredient, ingredient_id)
    ing.on_hand += qty
    db.add(StockMove(ingredient_id=ingredient_id, qty=qty, kind="delivery", ref=ref))


def count(db: Session, ingredient_id: int, counted: float) -> float:
    ing = db.get(Ingredient, ingredient_id)
    diff = counted - ing.on_hand
    ing.on_hand = counted
    db.add(StockMove(ingredient_id=ingredient_id, qty=diff, kind="count", ref="monthly count"))
    return diff


def avg_daily_use(db: Session, days: int = 7) -> dict[int, float]:
    """Average ingredient use per day over the last `days` business days, from sales and recipes."""
    since = dt.date.today() - dt.timedelta(days=days)
    rows = db.execute(
        select(RecipeLine.ingredient_id, func.sum(OrderLine.qty * RecipeLine.qty))
        .join(OrderLine, OrderLine.menu_item_id == RecipeLine.menu_item_id)
        .join(Order, Order.id == OrderLine.order_id)
        .where(Order.business_date >= since)
        .group_by(RecipeLine.ingredient_id)
    ).all()
    return {ing_id: total / days for ing_id, total in rows}


def open_order_ingredients(db: Session) -> set[int]:
    return set(db.scalars(
        select(PurchaseOrderLine.ingredient_id)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(PurchaseOrder.status.in_(["draft", "sent"]))
    ))


def stock_report(db: Session) -> list[dict]:
    use = avg_daily_use(db)
    out = []
    for ing in db.scalars(select(Ingredient).order_by(Ingredient.name)):
        daily = use.get(ing.id, 0.0)
        out.append({
            "id": ing.id, "name": ing.name, "unit": ing.unit, "on_hand": round(ing.on_hand, 1),
            "min_level": ing.min_level, "par_level": ing.par_level, "supplier": ing.supplier.name,
            "avg_daily_use": round(daily, 1),
            "days_left": round(ing.on_hand / daily, 1) if daily > 0 else None,
            "status": "negative" if ing.on_hand < 0 else "low" if ing.on_hand <= ing.min_level else "ok",
        })
    return out


def plan_reorders(db: Session) -> list[dict]:
    """Ingredients at or below minimum with no open order, and how much to order:
    back up to par, plus expected use until the supplier delivers."""
    use = avg_daily_use(db)
    already = open_order_ingredients(db)
    plan = []
    for ing in db.scalars(select(Ingredient)):
        if ing.id in already or ing.on_hand > ing.min_level:
            continue
        daily = use.get(ing.id, 0.0)
        lead = ing.supplier.lead_days
        qty = max(ing.par_level - max(ing.on_hand, 0), 0) + daily * lead
        step = 1 if ing.unit == "pcs" else 100
        qty = math.ceil(qty / step) * step
        plan.append({
            "ingredient": ing, "qty": qty, "daily": daily, "lead": lead,
            "reason": f"On hand {ing.on_hand:.0f} {ing.unit}, minimum {ing.min_level:.0f}. "
                      f"Order brings it to par {ing.par_level:.0f} plus {lead} day(s) of use at {daily:.0f} {ing.unit}/day.",
        })
    return plan
