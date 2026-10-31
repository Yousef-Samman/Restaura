"""Sales forecast for the next days: the last 7 days' average (the current level) times the weekday's share of a
normal week, learned over the last 8 weeks. It follows a change in level, such as summer or Ramadan, within a week.
Chosen by backtest over the earlier method, a plain average of the same weekday over 4 weeks: see evals/.

The forecast checks itself every day (scorecard()): it replays the last 4 weeks, forecasting each day from only
the days before it, compares with what was sold, and tells the manager when it has been further off than usual,
which usually means something changed (an event, a promotion, a closed day). Two ways of correcting itself were
tried and rejected because they made it worse on both the sample and the real store's sales: switching to
whichever method was closest lately, and correcting a steady lean (see evals/forecast_eval.py).
Special days (learn_lifts()): the manager tags days that are not normal, such as Eid, payday or a promotion. Tagged
days are kept out of the normal pattern, so one busy day doesn't lift the whole next week, and each label's lift
(sales against what a normal day would have been) is learned from its past tagged days and used on the next one.

Item forecasts use the same weekday's item mix, scaled to the forecast, and through the recipes give the
ingredients needed."""
import datetime as dt
import math
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Ingredient, MenuItem, Order, OrderLine, RecipeLine, SpecialDay

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


# ---- checking itself -------------------------------------------------------------------------------------------
CHECK_DAYS = 28  # recent days the forecast replays to judge itself
HORIZON = 7
DRIFT = 1.5  # last week's error this many times its usual error = something changed


def replay(history: dict[dt.date, float], today: dt.date, days: int = CHECK_DAYS, weeks: int = WEEKS, bias: float = 1.0) -> list[tuple[dt.date, float, float]]:
    """(day, forecast, actual) for each of the last `days` days: every forecast made 1 to 7 days ahead from only the
    days before it, exactly as the app would have made it then."""
    out = []
    for back in range(days, 0, -1):
        d = today - dt.timedelta(days=back)
        if d not in history:
            continue
        for h in range(HORIZON):
            origin = d - dt.timedelta(days=h)
            p = level_weekday_forecast({k: v for k, v in history.items() if k < origin}, origin, d, weeks)
            if p:
                out.append((d, p * bias, history[d]))
    return out


def mape(rows) -> float | None:
    return sum(abs(p - a) / a for _, p, a in rows if a) / len(rows) if rows else None


def scorecard(history: dict[dt.date, float], today: dt.date) -> dict:
    """How close the forecast has been, week by week over the last 4 weeks, whether it ran high or low, and whether
    last week was off by much more than usual."""
    rows = replay(history, today)
    weeks = []
    for w in range(CHECK_DAYS // 7, 0, -1):
        lo, hi = today - dt.timedelta(days=7 * w), today - dt.timedelta(days=7 * (w - 1))
        part = [r for r in rows if lo <= r[0] < hi]
        if part:
            weeks.append({"week_of": lo.isoformat(), "error": round(mape(part), 4),
                          "lean": round(sum(a for *_, a in part) / sum(p for _, p, _ in part) - 1, 4)})
    usual = sum(w["error"] for w in weeks[:-1]) / len(weeks[:-1]) if len(weeks) > 1 else None
    drift = bool(usual and weeks[-1]["error"] > DRIFT * usual)
    return {"weeks": weeks, "error": round(mape(rows), 4) if rows else None, "usual": round(usual, 4) if usual else None,
            "drift": drift, "checked_days": len({d for d, *_ in rows})}


# ---- special days -----------------------------------------------------------------------------------------------
def _key(label: str) -> str:
    return " ".join(label.lower().split())


def learn_lifts(history: dict[dt.date, float], special: dict[dt.date, str], today: dt.date) -> dict[str, dict]:
    """Each label's lift, learned from its past tagged days: sales on the day against the normal forecast for it,
    made from the normal days before it. {label: {"lift": 1.4, "days": 2, "examples": [(date, lift), ...]}}"""
    normal = {d: v for d, v in history.items() if d not in special}
    seen: dict[str, list] = {}
    for d, label in sorted(special.items()):
        if d >= today or d not in history:
            continue
        base = level_weekday_forecast({k: v for k, v in normal.items() if k < d}, d, d)
        if base:
            seen.setdefault(_key(label), []).append((d, history[d] / base))
    return {k: {"lift": round(sum(x for _, x in v) / len(v), 3), "days": len(v), "examples": v} for k, v in seen.items()}


def special_forecast(history: dict[dt.date, float], special: dict[dt.date, str], origin: dt.date, day: dt.date,
                     lifts: dict | None = None) -> tuple[float | None, dict | None]:
    """Forecast for `day` made on `origin`: the normal forecast from normal days only, times the learned lift when
    `day` is tagged. Returns (forecast, the lift used or None)."""
    normal = {d: v for d, v in history.items() if d not in special}
    p = level_weekday_forecast(normal, origin, day)
    label = special.get(day)
    if p is None or not label:
        return p, None
    lifts = learn_lifts(history, special, origin) if lifts is None else lifts
    l = lifts.get(_key(label))
    return (p * l["lift"], l) if l else (p, None)


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
    tagged = db.scalars(select(SpecialDay)).all()
    special, ids = {t.date: t.label for t in tagged}, {t.date: t.id for t in tagged}
    lifts = learn_lifts(daily, special, today)
    names = dict(db.execute(select(MenuItem.id, MenuItem.name)).all())
    out_days, item_need = [], defaultdict(float)
    for i in range(days):
        d = today + dt.timedelta(days=i)
        same = [p for p in (d - dt.timedelta(days=7 * k) for k in range(1, WEEKS + 1)) if p in daily and p not in special]
        vals = [daily[p] for p in same]
        n = len(same) or 1
        typical = sum(vals) / n
        sales, lift = special_forecast(daily, special, today, d, lifts)
        sales = typical if sales is None else sales
        scale = sales / typical if typical else 1.0  # the same weekday's orders and item mix, at today's level
        out_days.append({"date": d.isoformat(), "sales": round(sales, 2), "orders": round(sum(orders.get(p, 0) for p in same) / n * scale),
                         "low": round(min(vals) * scale, 2) if vals else 0, "high": round(max(vals) * scale, 2) if vals else 0,
                         "based_on": len(same),
                         "special": {"label": special[d], "lift": lift["lift"] if lift else None, "days": lift["days"] if lift else 0}
                         if d in special else None})
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
            "ingredients": ingredients, "method": f"Last {LEVEL_DAYS} days' average sales, adjusted for the weekday using the last {WEEKS} weeks.",
            "scorecard": scorecard({d: v for d, v in daily.items() if d not in special}, today),
            "special_days": {"upcoming": [{"id": ids[d], "date": d.isoformat(), "label": l} for d, l in sorted(special.items()) if d >= today],
                             "past": [{"id": ids[d], "date": d.isoformat(), "label": l, "sales": round(daily.get(d, 0), 2)} for d, l in sorted(special.items(), reverse=True) if d < today][:8],
                             "learned": [{"label": next(l for l in special.values() if _key(l) == k), "lift": v["lift"], "days": v["days"]} for k, v in lifts.items()]}}
