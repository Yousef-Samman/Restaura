"""Sales forecast for the next days: the average of the same weekday over the last four weeks.
Item forecasts use the same method and, through the recipes, give the ingredients needed."""
import datetime as dt
import math
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Ingredient, MenuItem, Order, OrderLine, RecipeLine

WEEKS = 4


def _history(db: Session, today: dt.date):
    since = today - dt.timedelta(days=7 * WEEKS)
    daily = dict(db.execute(select(Order.business_date, func.sum(Order.total)).where(Order.business_date >= since, Order.business_date < today)
                            .group_by(Order.business_date)).all())
    orders = dict(db.execute(select(Order.business_date, func.count(Order.id)).where(Order.business_date >= since, Order.business_date < today)
                             .group_by(Order.business_date)).all())
    items = defaultdict(dict)
    for d, item_id, q in db.execute(select(Order.business_date, OrderLine.menu_item_id, func.sum(OrderLine.qty)).join(Order)
                                    .where(Order.business_date >= since, Order.business_date < today)
                                    .group_by(Order.business_date, OrderLine.menu_item_id)).all():
        items[d][item_id] = q
    return since, daily, orders, items


def forecast(db: Session, days: int = 7) -> dict:
    today = dt.date.today()
    since, daily, orders, items = _history(db, today)
    past = [since + dt.timedelta(days=i) for i in range(7 * WEEKS)]
    names = dict(db.execute(select(MenuItem.id, MenuItem.name)).all())
    out_days, item_need = [], defaultdict(float)
    for i in range(days):
        d = today + dt.timedelta(days=i)
        same = [p for p in past if p.weekday() == d.weekday() and p in daily]
        vals = [daily[p] for p in same]
        n = len(same) or 1
        out_days.append({"date": d.isoformat(), "sales": round(sum(vals) / n, 2), "orders": round(sum(orders.get(p, 0) for p in same) / n),
                         "low": round(min(vals), 2) if vals else 0, "high": round(max(vals), 2) if vals else 0, "based_on": len(same)})
        for p in same:
            for item_id, q in items[p].items():
                item_need[(i, item_id)] += q / n
    tomorrow = sorted(((names[item_id], q) for (i, item_id), q in item_need.items() if i == 1), key=lambda x: -x[1])
    recipe = defaultdict(list)
    for r in db.scalars(select(RecipeLine)):
        recipe[r.menu_item_id].append((r.ingredient_id, r.qty))
    need = defaultdict(float)
    for (i, item_id), q in item_need.items():
        for ing_id, per in recipe[item_id]:
            need[ing_id] += q * per
    ingredients = []
    for ing in db.scalars(select(Ingredient).order_by(Ingredient.name)):
        week = need.get(ing.id, 0.0)
        per_day = week / days if days else 0
        left = ing.on_hand / per_day if per_day > 0 else None
        ingredients.append({"id": ing.id, "name": ing.name, "unit": ing.unit, "need": round(week, 1), "on_hand": round(ing.on_hand, 1),
                            "short": round(max(week - ing.on_hand, 0), 1),
                            "runs_out": (today + dt.timedelta(days=math.floor(left))).isoformat() if left is not None and left < days else None})
    ingredients.sort(key=lambda r: (r["runs_out"] is None, r["runs_out"] or "", r["name"]))
    actual = [{"date": (today - dt.timedelta(days=k)).isoformat(), "sales": round(daily.get(today - dt.timedelta(days=k), 0), 2)} for k in range(14, 0, -1)]
    return {"days": out_days, "actual": actual, "tomorrow_items": [{"name": n, "qty": round(q)} for n, q in tomorrow[:8]],
            "ingredients": ingredients, "method": f"Average of the same weekday over the last {WEEKS} weeks."}
