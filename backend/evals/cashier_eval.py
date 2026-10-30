"""Cashier helper, held out by date.

The helper learns what sells together from past orders. We train it on all orders before the last 7 days, then
replay each held-out order: the cashier has rung up part of it, and we check whether the helper's two suggestions
include an item the customer really added next (hit@2). Baseline: suggest the two best-selling items.

Two data sets:
- "app sample data": the history the app ships with.
- "changed habits": a different store where customers pair items differently. Hand-written rules can't know this;
  the helper has to learn it from the orders. This is the adaptation test.
"""
import datetime as dt
import random
from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.agents import cashier
from app.models import MenuItem, Order, OrderLine, RecipeLine
from app.seed import seed

from .common import fresh_db, rate

HOLDOUT_DAYS = 7
MAINS = cashier.MAINS


# ---- data -------------------------------------------------------------------------------------------------------
def _changed_habits_history(db, items: list[MenuItem], days: int, seed_: int = 21) -> None:
    """Orders from a store whose customers pair things differently from the app's sample data:
    waffles come with hot chocolate and whipped cream, crepes with an Americano and pistachio drizzle,
    pancakes with an iced latte and ice cream. Some noise on top."""
    rng = random.Random(seed_)
    by = {i.name: i for i in items}
    habits = {
        "Waffles": (["Hot chocolate"], ["Extra whipped cream"]),
        "Crepes": (["Americano"], ["Pistachio drizzle"]),
        "Pancakes": (["Iced latte"], ["Scoop of vanilla ice cream"]),
    }
    mains = [i for i in items if i.category in MAINS]
    drinks = [i for i in items if i.category == "Drinks"]
    addons = [i for i in items if i.is_addon]
    today = dt.date.today()
    for d in range(days, 0, -1):
        day = today - dt.timedelta(days=d)
        for _ in range(rng.randint(35, 55)):
            main = rng.choice(mains)
            fav_drinks, fav_addons = habits[main.category]
            lines = [main]
            if rng.random() < 0.6:
                lines.append(by[rng.choice(fav_drinks)] if rng.random() < 0.8 else rng.choice(drinks))
            if rng.random() < 0.35:
                lines.append(by[rng.choice(fav_addons)] if rng.random() < 0.8 else rng.choice(addons))
            lines = list(dict.fromkeys(lines))
            order = Order(business_date=day, source="history", total=sum(i.price for i in lines))
            order.lines = [OrderLine(menu_item_id=i.id, qty=1, price=i.price) for i in lines]
            db.add(order)
    db.commit()


def _build(db, scenario: str) -> None:
    if scenario == "app sample data":
        seed(db, history_days=35)
    else:
        seed(db, history_days=0)
        items = db.scalars(select(MenuItem).order_by(MenuItem.id)).all()
        _changed_habits_history(db, items, 35)


def _holdout(db) -> list[list[int]]:
    """Removes the last HOLDOUT_DAYS days of orders from the database and returns them as lists of item ids,
    in the order they were rung up."""
    cutoff = dt.date.today() - dt.timedelta(days=HOLDOUT_DAYS)
    orders = db.scalars(select(Order).where(Order.business_date >= cutoff).options(selectinload(Order.lines))).all()
    held = [[l.menu_item_id for l in sorted(o.lines, key=lambda l: l.id)] for o in orders]
    ids = [o.id for o in orders]
    db.execute(delete(OrderLine).where(OrderLine.order_id.in_(ids)))
    db.execute(delete(Order).where(Order.id.in_(ids)))
    db.commit()
    return held


def cases(held: list[list[int]]) -> list[tuple[tuple[int, ...], frozenset[int]]]:
    """(cart so far, items the customer added after it). One case per point in the order where more was added."""
    out = []
    for lines in held:
        for k in range(1, len(lines)):
            out.append((tuple(lines[:k]), frozenset(lines[k:])))
    return out


# ---- methods ----------------------------------------------------------------------------------------------------
def _cart(db, ids):
    return [(db.get(MenuItem, i), 1) for i in ids]


def _popular(db, ids, best_sellers):
    cart = _cart(db, ids)
    avail = {c["item"].id for c in cashier.candidates(db, cart, limit=100)}
    return [i for i in best_sellers if i in avail][:2]


def _rules(db, ids, **switches):
    return [c["item"].id for c in cashier._distinct(cashier.candidates(db, _cart(db, ids), **switches))]


def _ai(db, ids, llm):
    out = cashier.suggest(db, llm, _cart(db, ids))
    return [s["item_id"] for s in out["suggestions"]], out["source"]


def score(preds: dict, cs) -> dict:
    hits = sum(bool(set(preds[c]) & t) for c, t in cs)
    shown = sum(len(preds[c]) for c, _ in cs)
    accepted = sum(len(set(preds[c]) & t) for c, t in cs)
    return {"cases": len(cs), "hit_at_2": rate(hits, len(cs)), "precision": rate(accepted, shown)}


def run(llm=None, log=print) -> dict:
    results = {}
    for scenario in ("app sample data", "changed habits"):
        with fresh_db() as db:
            _build(db, scenario)
            cs = cases(_holdout(db))
            carts = sorted({c for c, _ in cs})
            sold = Counter()
            for item_id, qty in db.execute(select(OrderLine.menu_item_id, OrderLine.qty)):
                sold[item_id] += qty
            best = [i for i, _ in sold.most_common()]
            methods = {
                "Best sellers (baseline)": {c: _popular(db, c, best) for c in carts},
                "Restaura rules (app)": {c: _rules(db, c) for c in carts},
                "Ablation: order history only": {c: _rules(db, c, use_pairing_rules=False) for c in carts},
                "Ablation: pairing rules only": {c: _rules(db, c, use_history=False) for c in carts},
            }
            row = {name: score(p, cs) for name, p in methods.items()}
            if llm:
                preds, fell_back = {}, 0
                for c in carts:
                    preds[c], src = _ai(db, c, llm)
                    fell_back += src != "ai"
                row["Restaura with Claude"] = score(preds, cs) | {"carts": len(carts), "fell_back_to_rules": fell_back}
            results[scenario] = {"held_out_orders_days": HOLDOUT_DAYS, "distinct_carts": len(carts), "methods": row}
            log(f"  cashier / {scenario}: " + ", ".join(f"{k} {v['hit_at_2']:.1%}" for k, v in row.items()))
    return results
