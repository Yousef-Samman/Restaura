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


def runs_out_before_delivery(on_hand: float, daily: float, lead_days: int | None) -> bool:
    """True when today's stock won't last until an order placed tomorrow arrives:
    days left <= lead time + 1. A supplier without a lead time counts as 1 day, so the cut-off is 2 days."""
    return daily > 0 and on_hand / daily <= (lead_days or 1) + 1


def stock_status(on_hand: float, min_level: float, daily: float, lead_days: int | None) -> tuple[str, str | None]:
    """(status, reason). status is negative | low | ok. Only for planning: cashier availability uses item_available."""
    if on_hand < 0:
        return "negative", "below zero"
    if on_hand <= min_level:
        return "low", "at or below minimum"
    if runs_out_before_delivery(on_hand, daily, lead_days):
        return "low", "runs out before a delivery could arrive"
    return "ok", None


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
        status, reason = stock_status(ing.on_hand, ing.min_level, daily, ing.supplier.lead_days)
        out.append({
            "id": ing.id, "name": ing.name, "unit": ing.unit, "on_hand": round(ing.on_hand, 1),
            "min_level": ing.min_level, "par_level": ing.par_level, "supplier": ing.supplier.name,
            "avg_daily_use": round(daily, 1),
            "days_left": round(ing.on_hand / daily, 1) if daily > 0 else None,
            "lead_days": ing.supplier.lead_days, "status": status, "reason": reason,
        })
    return out


def plan_reorders(db: Session) -> list[dict]:
    """Ingredients with no open order that are at or below minimum, or that will run out before
    the supplier could deliver an order placed tomorrow. Quantity: back up to par, plus expected use
    until the supplier delivers."""
    use = avg_daily_use(db)
    already = open_order_ingredients(db)
    plan = []
    for ing in db.scalars(select(Ingredient)):
        daily = use.get(ing.id, 0.0)
        lead = ing.supplier.lead_days
        if ing.id in already or stock_status(ing.on_hand, ing.min_level, daily, lead)[0] == "ok":
            continue
        qty = max(ing.par_level - max(ing.on_hand, 0), 0) + daily * lead
        step = 1 if ing.unit == "pcs" else 100
        qty = math.ceil(qty / step) * step
        plan.append({
            "ingredient": ing, "qty": qty, "daily": daily, "lead": lead,
            "reason": (f"On hand {ing.on_hand:.0f} {ing.unit}, minimum {ing.min_level:.0f}. " if ing.on_hand <= ing.min_level else
                       f"On hand {ing.on_hand:.0f} {ing.unit} lasts about {ing.on_hand / daily:.1f} days at {daily:.0f} {ing.unit}/day, "
                       f"and {ing.supplier.name} needs {lead} {'day' if lead == 1 else 'days'} to deliver. ")
                      + f"Ordering enough to refill to {ing.par_level:.0f} {ing.unit}, plus {lead} {'day' if lead == 1 else 'days'} of use "
                      f"({daily:.0f} {ing.unit}/day) until the delivery arrives.",
        })
    return plan
