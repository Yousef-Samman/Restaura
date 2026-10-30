"""Cashier helper: suggests add-ons that fit the order being taken, using only items that can be made now."""
import datetime as dt
from collections import Counter, defaultdict
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import MenuItem, OrderLine, RecipeLine, SuggestionEvent
from ..stock import item_available
from .llm import LLM

MAINS = {"Crepes", "Waffles", "Pancakes"}

SYSTEM = (
    "You are the cashier helper in a dessert and coffee restaurant. While the cashier takes an order, "
    "you pick at most two add-ons the customer is most likely to accept, and give the cashier one short, "
    "natural line to say for each. Choose only from the candidates given; every candidate can be made right now. "
    "Prefer items that genuinely complete the order (a drink with a dessert, ice cream with a warm crepe) over "
    "the most expensive one. Never pressure the customer. Lines must be under 14 words."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "pitch": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["item_id", "pitch", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}


def pair_counts(db: Session) -> tuple[dict[int, Counter], Counter]:
    by_order: dict[int, set[int]] = defaultdict(set)
    for order_id, item_id in db.execute(select(OrderLine.order_id, OrderLine.menu_item_id)):
        by_order[order_id].add(item_id)
    pairs: dict[int, Counter] = defaultdict(Counter)
    singles: Counter = Counter()
    for items in by_order.values():
        singles.update(items)
        for a, b in combinations(items, 2):
            pairs[a][b] += 1
            pairs[b][a] += 1
    return pairs, singles


def candidates(db: Session, cart: list[tuple[MenuItem, int]], limit: int = 6) -> list[dict]:
    items = db.scalars(select(MenuItem).options(selectinload(MenuItem.recipe).selectinload(RecipeLine.ingredient))).all()
    in_cart = {i.id for i, _ in cart}
    cats = {i.category for i, _ in cart}
    use: dict[int, float] = defaultdict(float)
    for item, qty in cart:
        for r in item.recipe:
            use[r.ingredient_id] += r.qty * qty
    pairs, singles = pair_counts(db)
    scored = []
    for item in items:
        if item.id in in_cart or not item_available(item, use):
            continue
        # how often this item is bought with what is already in the cart, as a share of those orders
        rate = max((pairs[c][item.id] / singles[c] for c in in_cart if singles[c]), default=0.0)
        score = rate
        if cats & MAINS and "Drinks" not in cats and item.category == "Drinks":
            score += 0.3
        if cats & MAINS and item.is_addon:
            score += 0.2
        if cats <= {"Drinks"} and item.category in MAINS:
            score += 0.25
        if item.category in MAINS and cats & MAINS:
            score -= 0.4  # a second dessert is rarely the right suggestion
        scored.append({"item": item, "score": score, "bought_together_rate": round(rate, 2)})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:limit]


def _a(name: str) -> str:
    return ("an " if name[0].lower() in "aeiou" else "a ") + name.lower()


def _rule_pitch(item: MenuItem) -> str:
    if item.is_addon:
        return f"Would you like to add {_a(item.name)} on top?"
    if item.category == "Drinks":
        return f"Would you like {_a(item.name)} with that?"
    return f"Would you like {_a(item.name)} to go with your drink?"


def _distinct(cands: list[dict], n: int = 2) -> list[dict]:
    """Best candidates, at most one per category, so the two suggestions are different kinds of add-on."""
    out, seen = [], set()
    for c in cands:
        if c["item"].category not in seen:
            out.append(c)
            seen.add(c["item"].category)
        if len(out) == n:
            break
    return out


def suggest(db: Session, llm: LLM, cart: list[tuple[MenuItem, int]]) -> dict:
    if not cart:
        return {"source": "rules", "suggestions": []}
    cands = candidates(db, cart)
    by_id = {c["item"].id: c for c in cands}
    picks, source = [], "rules"
    if llm.enabled and cands:
        hour = dt.datetime.now().hour
        prompt = {
            "time_of_day": "morning" if hour < 12 else "afternoon" if hour < 17 else "evening",
            "order_so_far": [{"name": i.name, "category": i.category, "qty": q} for i, q in cart],
            "candidates": [
                {"item_id": c["item"].id, "name": c["item"].name, "category": c["item"].category,
                 "price_sar": c["item"].price, "bought_together_rate": c["bought_together_rate"]}
                for c in cands
            ],
        }
        import json
        out = llm.json(SYSTEM, json.dumps(prompt), SCHEMA, effort="low", max_tokens=2000)
        if out:
            picks = [s for s in out["suggestions"] if s["item_id"] in by_id][:2]
            source = "ai" if picks else "rules"
    if not picks:
        picks = [{"item_id": c["item"].id, "pitch": _rule_pitch(c["item"]),
                  "reason": f"Bought together in {c['bought_together_rate']:.0%} of past orders."
                  if c["bought_together_rate"] else "Completes the order."} for c in _distinct(cands)]
    result = []
    for p in picks:
        item = by_id[p["item_id"]]["item"]
        ev = SuggestionEvent(menu_item_id=item.id, source=source)
        db.add(ev)
        db.flush()
        result.append({"event_id": ev.id, "item_id": item.id, "name": item.name, "price": item.price,
                       "pitch": p["pitch"], "reason": p["reason"]})
    db.commit()
    return {"source": source, "suggestions": result}
