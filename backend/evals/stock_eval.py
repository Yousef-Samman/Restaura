"""Stock-to-order agent: scenarios with known correct orders, plus randomised property checks.

1. Hand-worked scenarios. Each ingredient's correct order was worked out by hand from the rule the manager sees:
   order when stock is below zero, at or below the minimum, or will run out before the supplier can deliver an
   order placed tomorrow (days left <= lead time + 1). Quantity: refill to par, plus the use expected until the
   delivery arrives, rounded up to 100 g/ml or 1 piece.
2. 300 random stores: the agent must order every ingredient that needs it (recall), nothing that doesn't
   (precision), and enough that stock is back at par when the delivery arrives (sufficiency).
3. Learning on vs off (learning()): simulated managers with editing habits and suppliers slower than their
   setting; counts the edits and wrong lead-time weeks left with and without what the agent learns.
4. With Claude (a tool-using agent): every quantity Claude didn't change is the code's, every change stays within
   half to 1.5x the code's quantity and carries a reason, every computed warning is still in the briefing, and every
   number Claude writes is one from the facts its tools returned (no made-up numbers).
"""
import datetime as dt
import json
import random
import re

from sqlalchemy import select

from app.agents import stock_agent
from app.models import Ingredient, MenuItem, Order, OrderLine, PurchaseOrder, PurchaseOrderLine, RecipeLine, Supplier

from .common import fresh_db, no_llm, rate

# name, unit, on_hand, min, par, daily use, supplier
SCENARIO = [
    ("Flour", "g", 10000, 2000, 12000, 500, "Supplier B"),     # healthy: 20 days left
    ("Milk", "ml", 1500, 2000, 10000, 400, "Supplier A"),      # below minimum
    ("Sugar", "g", 3000, 1000, 8000, 1100, "Supplier B"),      # above minimum, but 2.7 days left and 2-day lead time
    ("Butter", "g", 3000, 500, 4000, 700, "Supplier B"),       # 4.3 days left: safe
    ("Cocoa", "g", 2100, 500, 4000, 700, "Supplier B"),        # exactly 3.0 days left = lead + 1: order
    ("Eggs", "pcs", -12, 30, 120, 14, "Supplier A"),           # below zero: a delivery was not recorded
    ("Cream", "ml", 100, 500, 3000, 0, "Supplier A"),          # low, but an order is already on the way
    ("Vanilla", "g", 200, 300, 1000, 0, "Supplier C"),         # no sales, below minimum
    ("Honey", "g", 450, 500, 1234, 33, "Supplier A"),          # rounding up to the next 100 g
]
LEAD = {"Supplier A": 1, "Supplier B": 2, "Supplier C": 3}
# worked by hand, see the comments above
EXPECTED = {
    ("Supplier A", "Milk"): 8900,      # (10000 - 1500) + 400 x 1
    ("Supplier A", "Eggs"): 134,       # (120 - 0) + 14 x 1, stock below zero counts as 0
    ("Supplier A", "Honey"): 900,      # (1234 - 450) + 33 x 1 = 817, up to 900
    ("Supplier B", "Sugar"): 7200,     # (8000 - 3000) + 1100 x 2
    ("Supplier B", "Cocoa"): 3300,     # (4000 - 2100) + 700 x 2
    ("Supplier C", "Vanilla"): 800,    # (1000 - 200) + 0
}
EXPECTED_WARNINGS = ["Eggs", "Chef's special"]  # stock below zero; a menu item with no recipe


def _store(db, rows, leads, open_order=(), no_recipe_item=False):
    suppliers = {n: Supplier(name=n, email=f"{n.lower().replace(' ', '-')}@example.com", lead_days=l) for n, l in leads.items()}
    db.add_all(suppliers.values())
    yesterday = dt.date.today() - dt.timedelta(days=1)
    for name, unit, on_hand, mn, par, daily, sup in rows:
        ing = Ingredient(name=name, unit=unit, unit_cost=0.01, min_level=mn, par_level=par, on_hand=on_hand, supplier=suppliers[sup])
        item = MenuItem(name=f"{name} test item", category="Test", price=1)
        item.recipe = [RecipeLine(ingredient=ing, qty=1)]
        db.add_all([ing, item])
        db.flush()
        if daily:  # one week of sales in a single day gives exactly `daily` per day on the 7-day average
            order = Order(business_date=yesterday, source="history", total=0)
            order.lines = [OrderLine(menu_item_id=item.id, qty=round(daily * 7), price=1)]
            db.add(order)
        if name in open_order:
            po = PurchaseOrder(supplier=suppliers[sup], status="sent")
            po.lines = [PurchaseOrderLine(ingredient=ing, qty=par)]
            db.add(po)
    if no_recipe_item:
        db.add(MenuItem(name="Chef's special", category="Test", price=30))
    db.commit()


def _drafts(db):
    out = {}
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")):
        for l in po.lines:
            out[(po.supplier.name, l.ingredient.name)] = l.qty
    return out


def scenarios(llm) -> dict:
    with fresh_db() as db:
        _store(db, SCENARIO, LEAD, open_order={"Cream"}, no_recipe_item=True)
        summary = stock_agent.run(db, llm)
        got = _drafts(db)
        changed = _changed(db)
        right = sum(got.get(k) == v or (k in changed and _within(v, got[k])) for k, v in EXPECTED.items())
        wrong_qty = [f"{k[1]}: expected {v}, got {got[k]}" for k, v in EXPECTED.items()
                     if k in got and got[k] != v and not (k in changed and _within(v, got[k]))]
        missed = [k[1] for k in EXPECTED if k not in got]
        extra = [k[1] for k in got if k not in EXPECTED]
        text = " ".join(summary["warnings"])
        warned = [w for w in EXPECTED_WARNINGS if w.lower() in text.lower()]
        again = stock_agent.run(db, llm)
        duplicates = len(again["order_ids"])
        out = {"source": summary["source"], "expected_lines": len(EXPECTED), "correct_lines": right,
               "accuracy": rate(right, len(EXPECTED)), "wrong_qty": wrong_qty, "missed": missed, "unneeded": extra,
               "warnings_expected": len(EXPECTED_WARNINGS), "warnings_found": len(warned),
               "duplicate_orders_on_second_run": duplicates,
               "adjusted_by_agent": [f"{k[1]}: {EXPECTED.get(k)} -> {got[k]}" for k in changed if k in got],
               "steps": [s["label"] for s in summary.get("steps", [])]}
        if summary["source"] == "ai":
            out["ungrounded_numbers"] = _ungrounded(db, summary)
        return out


def _changed(db) -> set[tuple[str, str]]:
    """Order lines the agent changed, with the reason it gave (the reason is on the line the manager sees)."""
    return {(po.supplier.name, l.ingredient.name) for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft"))
            for l in po.lines if "The agent changed" in (l.reason or "") and l.reason.split(":")[-1].strip()}


def _within(code_qty: float, qty: float) -> bool:
    return code_qty * 0.5 - 1e-6 <= qty <= code_qty * 1.5 + 1e-6


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def _ungrounded(db, summary) -> list[str]:
    """Numbers in Claude's briefing that are not in the facts it was given (small counts up to 10 are allowed,
    as are 7, used in 'the last 7 days')."""
    lines = [l for po in db.scalars(select(PurchaseOrder)) for l in po.lines]
    code_part = [(l.reason or "").split(" The agent changed")[0] for l in lines]
    agent_part = [(l.reason or "").split(" The agent changed")[1].split(":", 1)[-1] for l in lines if " The agent changed" in (l.reason or "")]
    facts = (json.dumps(stock_agent.stock_report(db)) + json.dumps(stock_agent.forecast.forecast(db), default=str)
             + " ".join(f"{l.qty} {c}" for l, c in zip(lines, code_part)))
    allowed = _numbers(facts)
    allowed |= {round(x, 1) for x in allowed} | {float(round(x)) for x in allowed}
    notes = " ".join(po.note or "" for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")))
    text = " ".join([summary["headline"], notes, *summary["warnings"], *agent_part])
    return sorted({str(n) for n in _numbers(text) if n > 10 and n not in allowed})


def busy_days_ahead(llm, runs: int = 3) -> dict:
    """Adaptation: three days a week sell three times a normal day, and they are the three days right after the
    delivery arrives. The code's quantity uses the plain 7-day average, so what arrives (about 7,900 g with what is
    left) does not cover the 9,000 g those three days need, and flour runs out before a next order could arrive.
    Claude may raise it (within limits, with a reason) and must never lower it. Several runs, since Claude varies."""
    today = dt.date.today()
    busy = {(today + dt.timedelta(days=k)).weekday() for k in (2, 3, 4)}
    raised = lowered = out_of_range = 0
    for _ in range(runs):
        with fresh_db() as db:
            sup = Supplier(name="Bakery Supply", email="bakery@example.com", lead_days=2)
            ing = Ingredient(name="Flour", unit="g", unit_cost=0.01, min_level=2000, par_level=6000, on_hand=2500, supplier=sup)
            item = MenuItem(name="Crepe", category="Test", price=20)
            item.recipe = [RecipeLine(ingredient=ing, qty=100)]
            db.add_all([sup, ing, item])
            db.flush()
            for k in range(1, 57):
                d = today - dt.timedelta(days=k)
                order = Order(business_date=d, source="history", total=0)
                order.lines = [OrderLine(menu_item_id=item.id, qty=30 if d.weekday() in busy else 10, price=20)]
                db.add(order)
            db.commit()
            code_qty = next(p["qty"] for p in stock_agent.plan_reorders(db))
            stock_agent.run(db, llm)
            qty = _drafts(db).get(("Bakery Supply", "Flour"))
            raised += qty is not None and qty > code_qty
            lowered += qty is not None and qty < code_qty
            out_of_range += qty is None or not _within(code_qty, qty)
    return {"runs": runs, "code_qty": code_qty, "raised": raised, "lowered": lowered, "out_of_range_or_missing": out_of_range}


def properties(n: int = 300, seed: int = 9) -> dict:
    """Random stores; checks the agent's orders against the ordering rule's intent, not its code."""
    rng = random.Random(seed)
    need = hit = ordered = unneeded = short = over = 0
    with fresh_db() as db:
        for k in range(n):
            lead = rng.randint(1, 4)
            unit = rng.choice(["g", "ml", "pcs"])
            par = rng.choice([100, 500, 2000, 10000])
            mn = round(par * rng.uniform(0.1, 0.4))
            daily = rng.choice([0, round(par * rng.uniform(0.01, 0.5))])
            on_hand = round(par * rng.uniform(-0.2, 1.1))
            name = f"Ing {k}"
            _store(db, [(name, unit, on_hand, mn, par, daily, f"Sup {k}")], {f"Sup {k}": lead})
            days_left = on_hand / daily if daily else None
            needs = on_hand < 0 or on_hand <= mn or (days_left is not None and days_left <= lead + 1)
            stock_agent.run(db, no_llm())
            qty = _drafts(db).get((f"Sup {k}", name))
            need += needs
            ordered += qty is not None
            if needs and qty is not None:
                hit += 1
                # what's left when the delivery arrives, plus the order, must be back at par, without
                # ordering more than one rounding step over it
                at_delivery = max(on_hand, 0) - daily * lead + qty
                short += at_delivery < par - 1e-6
                over += at_delivery >= max(par, on_hand) + (1 if unit == "pcs" else 100)
            if not needs and qty is not None:
                unneeded += 1
            for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")):
                po.status = "sent"  # keep each store's order from blocking the next check
            db.commit()
    return {"stores": n, "needed_an_order": need, "recall": rate(hit, need), "precision": rate(hit, ordered),
            "unneeded_orders": unneeded, "orders_too_small": short, "orders_too_large": over}


def run(llm=None, log=print) -> dict:
    out = {"rules": scenarios(no_llm()), "random_stores": properties(), "learning": learning()}
    if llm:
        out["with Claude"] = scenarios(llm)
        out["busy_days_ahead"] = busy_days_ahead(llm)
    for k in ("rules", "with Claude"):
        if k in out:
            r = out[k]
            log(f"  stock / scenarios ({k}, source {r['source']}): {r['correct_lines']}/{r['expected_lines']} order lines right, "
                f"{r['warnings_found']}/{r['warnings_expected']} warnings, {r['duplicate_orders_on_second_run']} duplicates"
                + (f", ungrounded numbers: {r['ungrounded_numbers'] or 'none'}" if "ungrounded_numbers" in r else ""))
    if "busy_days_ahead" in out:
        b = out["busy_days_ahead"]
        log(f"  stock / busy days ahead (Claude): raised {b['raised']}/{b['runs']}, lowered {b['lowered']}, "
            f"out of range or missing {b['out_of_range_or_missing']}")
    lr = out["learning"]
    log(f"  stock / learning on vs off ({lr['stores']} stores x {lr['weeks']} weeks): manager edits {lr['edits_learning_off']} -> "
        f"{lr['edits_learning_on']}, weeks with a wrong lead time {lr['wrong_lead_weeks_off']} -> {lr['wrong_lead_weeks_on']}, "
        f"{lr['wrong_suggestions']}/{lr['suggestions']} suggestions wrong")
    p = out["random_stores"]
    log(f"  stock / {p['stores']} random stores: recall {p['recall']:.1%}, precision {p['precision']:.1%}, "
        f"too small {p['orders_too_small']}, too large {p['orders_too_large']}")
    return out


def learning(weeks: int = 10, stores: int = 30, seed: int = 11) -> dict:
    """Learning on vs off. Simulated stores where the manager has habits the agent doesn't know: some ingredients
    always get raised or cut by a fixed share (others not), and some suppliers really deliver later than their
    setting. Each week the agent drafts an order (the code's quantity times what was applied), the manager edits it
    to what they want, and the delivery arrives after the real number of days. With learning on, a manager applies a
    suggestion when it is within 10% of their habit and dismisses it otherwise; with learning off, nothing changes.
    Measured: how many lines the manager still had to edit, and how many weeks a supplier's lead time was wrong."""
    from app.agents import stock_memory
    from app.models import Lesson
    rng = random.Random(seed)
    totals = {"on": {"edits": 0, "wrong_lead_weeks": 0}, "off": {"edits": 0, "wrong_lead_weeks": 0}}
    wrong_suggestions, suggestions = 0, 0
    for s in range(stores):
        n_ing = 6
        habits = [rng.choice([1.0, 1.0, 1.2, 0.8, 1.3, 1.1]) for _ in range(n_ing)]
        true_lead = [rng.choice([1, 2, 2, 3]) for _ in range(2)]
        for mode in ("on", "off"):
            with fresh_db() as db:
                sups = [Supplier(name=f"S{i}", email="s@example.com", lead_days=1) for i in range(2)]
                ings = [Ingredient(name=f"I{i}", unit="g", unit_cost=0.01, min_level=100, par_level=1000, on_hand=0,
                                   supplier=sups[i % 2]) for i in range(n_ing)]
                db.add_all(sups + ings)
                db.flush()
                start = dt.datetime(2026, 1, 4, 18)
                for w in range(weeks):
                    sent = start + dt.timedelta(days=7 * w)
                    today = (sent + dt.timedelta(days=1)).date()
                    for i, sup in enumerate(sups):
                        totals[mode]["wrong_lead_weeks"] += sup.lead_days != true_lead[i]
                        po = PurchaseOrder(supplier=sup, status="received", sent_at=sent, created_at=sent,
                                           received_at=sent + dt.timedelta(days=true_lead[i]))
                        for j, ing in enumerate(ings):
                            if j % 2 != i:
                                continue
                            drafted = round(5000 * ing.order_factor, -2)
                            wanted = round(5000 * habits[j] * rng.gauss(1, 0.02), -2)
                            totals[mode]["edits"] += abs(wanted / drafted - 1) > stock_memory.EDIT_NOISE
                            po.lines.append(PurchaseOrderLine(ingredient=ing, drafted_qty=drafted, qty=wanted))
                        db.add(po)
                    db.flush()
                    if mode == "off":
                        continue
                    for l in stock_memory.refresh(db, today):
                        suggestions += 1
                        kind, _, sid = l.subject.partition(":")
                        truth = true_lead[int(sid) - 1] if kind == "supplier" else habits[int(sid) - 1]
                        if abs(l.value - truth) <= 0.1 * truth:
                            stock_memory.apply(db, l, sent + dt.timedelta(hours=12))
                        else:
                            wrong_suggestions += 1
                            stock_memory.dismiss(l, sent + dt.timedelta(hours=12))
                    db.flush()
    lines = stores * weeks * 6
    return {"stores": stores, "weeks": weeks, "order_lines": lines,
            "edits_learning_off": totals["off"]["edits"], "edits_learning_on": totals["on"]["edits"],
            "wrong_lead_weeks_off": totals["off"]["wrong_lead_weeks"], "wrong_lead_weeks_on": totals["on"]["wrong_lead_weeks"],
            "suggestions": suggestions, "wrong_suggestions": wrong_suggestions}
