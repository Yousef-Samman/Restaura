"""Sales forecast for the next days: the last 7 days' average (the current level) times the weekday's share of a
normal week, learned over the last 8 weeks. It follows a change in level, such as summer or Ramadan, within a week.
Chosen by backtest over the earlier method, a plain average of the same weekday over 4 weeks: see evals/.
Item forecasts use the same weekday's item mix, scaled to the forecast, and through the recipes give the
ingredients needed."""
import datetime as dt
import math
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Ingredient, MenuItem, Order, OrderLine, RecipeLine

WEEKS = 8  # weeks of history that set each weekday's share of the week
LEVEL_DAYS = 7  # recent days that set the current level


def same_weekday_days(history: dict[dt.date, float], day: dt.date, weeks: int = WEEKS) -> list[dt.date]:
    """The days with sales on the same weekday as `day` in the `weeks` weeks before it."""
    return [p for p in (day - dt.timedelta(days=7 * k) for k in range(1, weeks + 1)) if p in history]


def same_weekday_average(history: dict[dt.date, float], day: dt.date, weeks: int = WEEKS) -> float | None:
    """Forecast for `day`: the average of the same weekday in the `weeks` weeks before it, or None without history."""
    same = same_weekday_days(history, day, weeks)
    return sum(history[p] for p in same) / len(same) if same else None


def weekday_index(history: dict[dt.date, float], origin: dt.date, day: dt.date, weeks: int = WEEKS) -> float | None:
    """How `day`'s weekday compares with an average day, over the `weeks` weeks before `origin` (1.2 = 20% busier)."""
    window = [p for p in (origin - dt.timedelta(days=k) for k in range(1, 7 * weeks + 1)) if p in history]
    same = [p for p in window if p.weekday() == day.weekday()]
    if not same:
        return None
    avg = sum(history[p] for p in window) / len(window)
    return (sum(history[p] for p in same) / len(same)) / avg if avg else None


def level_weekday_forecast(history: dict[dt.date, float], origin: dt.date, day: dt.date, weeks: int = WEEKS) -> float | None:
    """Forecast for `day` made on `origin` from the days before it: recent level x weekday index, or None without history."""
    recent = [history[p] for p in (origin - dt.timedelta(days=k) for k in range(1, LEVEL_DAYS + 1)) if p in history]
    index = weekday_index(history, origin, day, weeks)
    if not recent or index is None:
        return None
    return sum(recent) / len(recent) * index


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
    names = dict(db.execute(select(MenuItem.id, MenuItem.name)).all())
    out_days, item_need = [], defaultdict(float)
    for i in range(days):
        d = today + dt.timedelta(days=i)
        same = [p for p in (d - dt.timedelta(days=7 * k) for k in range(1, WEEKS + 1)) if p in daily]
        vals = [daily[p] for p in same]
        n = len(same) or 1
        typical = sum(vals) / n
        sales = level_weekday_forecast(daily, today, d)
        sales = typical if sales is None else sales
        scale = sales / typical if typical else 1.0  # the same weekday's orders and item mix, at today's level
        out_days.append({"date": d.isoformat(), "sales": round(sales, 2), "orders": round(sum(orders.get(p, 0) for p in same) / n * scale),
                         "low": round(min(vals) * scale, 2) if vals else 0, "high": round(max(vals) * scale, 2) if vals else 0,
                         "based_on": len(same)})
        for p in same:
            for item_id, q in items[p].items():
                item_need[(i, item_id)] += q / n * scale
    tomorrow = sorted(((names[item_id], q) for (i, item_id), q in item_need.items() if i == 1), key=lambda x: -x[1])
    recipe = defaultdict(list)
    for r in db.scalars(select(RecipeLine)):
        recipe[r.menu_item_id].append((r.ingredient_id, r.qty))
    need, by_day = defaultdict(float), defaultdict(lambda: [0.0] * days)
    for (i, item_id), q in item_need.items():
        for ing_id, per in recipe[item_id]:
            need[ing_id] += q * per
            by_day[ing_id][i] += q * per
    ingredients = []
    for ing in db.scalars(select(Ingredient).order_by(Ingredient.name)):
        week = need.get(ing.id, 0.0)
        per_day = week / days if days else 0
        left = ing.on_hand / per_day if per_day > 0 else None
        ingredients.append({"id": ing.id, "name": ing.name, "unit": ing.unit, "need": round(week, 1), "on_hand": round(ing.on_hand, 1),
                            "short": round(max(week - ing.on_hand, 0), 1),
                            "by_day": [round(x, 1) for x in by_day[ing.id]],
                            "runs_out": (today + dt.timedelta(days=math.floor(left))).isoformat() if left is not None and left < days else None})
    ingredients.sort(key=lambda r: (r["runs_out"] is None, r["runs_out"] or "", r["name"]))
    actual = [{"date": (today - dt.timedelta(days=k)).isoformat(), "sales": round(daily.get(today - dt.timedelta(days=k), 0), 2)} for k in range(14, 0, -1)]
    return {"days": out_days, "actual": actual, "tomorrow_items": [{"name": n, "qty": round(q)} for n, q in tomorrow[:8]],
            "ingredients": ingredients, "method": f"Last {LEVEL_DAYS} days' average sales, adjusted for the weekday using the last {WEEKS} weeks."}
