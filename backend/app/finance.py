"""Expenses and estimated profit for a period. Profit = sales - ingredient cost of what was sold
(from recipes) - fixed monthly costs spread over the period - one-off expenses in the period.
Supplier purchases are shown as money paid out, but not subtracted again: the ingredient cost covers them."""
import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Expense, Ingredient, MenuItem, Order, OrderLine, RecipeLine

FOOD_COST_TARGET = 0.30  # share of sales; a common rule of thumb for cafes, the manager can change it later
CATEGORIES = ["Rent", "Salaries", "Utilities", "Packaging", "Cleaning", "Maintenance", "Marketing", "Other"]


def record_purchase(db: Session, lines: list[tuple[int, float]], ref: str) -> float:
    cost = sum(qty * db.get(Ingredient, ing_id).unit_cost for ing_id, qty in lines)
    if cost > 0:
        db.add(Expense(date=dt.date.today(), kind="purchase", category="Ingredients", amount=round(cost, 2), note=ref))
    return cost


def food_cost(db: Session, since: dt.date) -> float:
    unit = dict(db.execute(select(RecipeLine.menu_item_id, func.sum(RecipeLine.qty * Ingredient.unit_cost))
                           .join(Ingredient).group_by(RecipeLine.menu_item_id)).all())
    sold = db.execute(select(OrderLine.menu_item_id, func.sum(OrderLine.qty)).join(Order)
                      .where(Order.business_date >= since).group_by(OrderLine.menu_item_id)).all()
    return sum(unit.get(i, 0) * q for i, q in sold)


def summary(db: Session, days: int) -> dict:
    today = dt.date.today()
    since = today - dt.timedelta(days=days - 1)
    sales = db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.business_date >= since))
    food = food_cost(db, since)
    fixed = db.scalars(select(Expense).where(Expense.kind == "fixed")).all()
    one_off = db.scalars(select(Expense).where(Expense.kind == "one_off", Expense.date >= since)).all()
    purchases = db.scalars(select(Expense).where(Expense.kind == "purchase", Expense.date >= since)).all()
    by_cat: dict[str, float] = {"Ingredients (used)": food}
    for e in fixed:
        by_cat[e.category] = by_cat.get(e.category, 0) + e.amount * days / 30
    for e in one_off:
        by_cat[e.category] = by_cat.get(e.category, 0) + e.amount
    costs = sum(by_cat.values())
    profit = sales - costs
    notes = []
    if sales:
        fc = food / sales
        notes.append(f"Ingredient cost is {fc:.0%} of sales" + (f", above the {FOOD_COST_TARGET:.0%} target. Check portions and waste." if fc > FOOD_COST_TARGET else f", within the {FOOD_COST_TARGET:.0%} target."))
        top = max((k for k in by_cat if k != "Ingredients (used)"), key=by_cat.get, default=None)
        if top:
            notes.append(f"{top} is the biggest operating cost: {by_cat[top] / sales:.0%} of sales.")
        notes.append(f"Estimated profit margin: {profit / sales:.0%}." if profit >= 0 else "Costs are higher than sales in this period.")
    row = lambda e: {"id": e.id, "date": e.date.isoformat(), "kind": e.kind, "category": e.category, "amount": e.amount, "note": e.note}
    return {
        "days": days, "sales": round(sales, 2), "food_cost": round(food, 2), "costs": round(costs, 2), "profit": round(profit, 2),
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]) if v > 0],
        "purchases_paid": round(sum(e.amount for e in purchases), 2),
        "fixed": [row(e) for e in fixed], "entries": [row(e) for e in sorted(one_off + purchases, key=lambda e: e.date, reverse=True)],
        "notes": notes, "categories": CATEGORIES,
    }
