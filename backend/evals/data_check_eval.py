"""The data check: does checking the records before the agents learn make the results better? Mistakes are put into
the data on purpose, and each agent learns twice from the same data: without the check, and with it (records that
don't fit are held out, and the manager's decision is the truth). A third test asks who should say whether a
flagged record is a mistake: the rules alone, or Claude.

- counts: the stock agent's usage learning, on simulated stores where some counts are typed with a missing zero.
- sales: the forecast, on the synthetic store's sales with days imported twice or only partly, next to real
  holidays (Founding Day, Eid) and promotions nobody tagged.
- verdicts: every record the check flagged in the two tests above, plus manager order edits with an extra or missing
  zero and real big edits. Scored against the truth: right, unsure (the manager has to look), or wrong (the
  harmful case: a mistake called real, or a real event called a mistake)."""
import datetime as dt
import json
import random

from app.agents import data_check, stock_memory
from app.forecast import special_forecast
from app.models import DataFlag, Ingredient, MenuItem, Order, OrderLine, PurchaseOrder, PurchaseOrderLine, RecipeLine, StockMove, Supplier

from .common import fresh_db, no_llm
from .forecast_eval import HORIZON, TEST_DAYS, synthetic_history

# Saudi public holidays in the synthetic store's half year (2026), with how much busier the cafe is (illustrative)
HOLIDAYS = {dt.date(2026, 2, 22): ("Founding Day", 1.6), dt.date(2026, 3, 20): ("Eid al-Fitr", 1.7),
            dt.date(2026, 3, 21): ("Eid al-Fitr", 1.6), dt.date(2026, 5, 27): ("Eid al-Adha", 1.6),
            dt.date(2026, 5, 28): ("Eid al-Adha", 1.5)}


# ---- counts: usage learning with typing slips ----------------------------------------------------------------------
def counts(stores: int = 30, weeks: int = 8, slip_rate: float = 0.15, seed: int = 21) -> dict:
    """Each store counts one ingredient weekly. The real use is the recipes' use times (1 + waste); a count is typed
    with a missing zero with probability `slip_rate`, and the next count puts the stock right again. Scored at the
    end: did the agent suggest the right extra (within 10%), a wrong one, or nothing when there was waste?"""
    rng = random.Random(seed)
    out = {"off": {"right": 0, "wrong": 0, "missed": 0}, "on": {"right": 0, "wrong": 0, "missed": 0}}
    flags, slips = [], 0
    for s in range(stores):
        waste = rng.choice([0.0, 0.0, 0.1, 0.15, 0.2])
        daily = [rng.randint(15, 25) for _ in range(7 * weeks)]
        noise = [rng.gauss(1, 0.02) for _ in range(weeks)]
        slip = [rng.random() < slip_rate for _ in range(weeks)]
        slips += sum(slip)
        for mode in ("off", "on"):
            with fresh_db() as db:
                sup = Supplier(name="S", email="s@example.com", lead_days=1)
                ing = Ingredient(name="Hazelnut spread", unit="g", unit_cost=0.06, min_level=1000, par_level=30000, on_hand=0, supplier=sup)
                item = MenuItem(name="Hazelnut crepe", category="Crepes", price=38)
                item.recipe = [RecipeLine(ingredient=ing, qty=100)]
                db.add_all([sup, ing, item])
                db.flush()
                start = dt.date(2026, 3, 1)
                at = lambda d: dt.datetime.combine(d, dt.time(6))  # 09:00 store time
                db.add(StockMove(ingredient_id=ing.id, qty=0, kind="count", ref="first count", at=at(start)))
                true, system, truth = 30000.0, 30000.0, {}
                for w in range(weeks):
                    use = 0
                    for k in range(7):
                        d = start + dt.timedelta(days=7 * w + k)
                        o = Order(business_date=d, source="history", total=38 * daily[7 * w + k], created_at=at(d))
                        o.lines = [OrderLine(menu_item_id=item.id, qty=daily[7 * w + k], price=38)]
                        db.add(o)
                        use += 100 * daily[7 * w + k]
                    true -= use * (1 + waste) * noise[w]
                    system -= use
                    counted = round(true * (0.1 if slip[w] else 1), -1)
                    m = StockMove(ingredient_id=ing.id, qty=counted - system, kind="count", ref="weekly count", counted=counted,
                                  at=at(start + dt.timedelta(days=7 * (w + 1))))
                    db.add(m)
                    db.flush()
                    truth[m.id] = "mistake" if slip[w] else "real"
                    true, system = true + 20000, counted + 20000  # the weekly delivery
                db.flush()
                today = start + dt.timedelta(days=7 * weeks + 1)
                if mode == "on":
                    for f in data_check.run(db, no_llm(), today):
                        if f.kind != "count":  # a busy or quiet day in this tiny simulated store: real, and not what is tested here
                            data_check.decide(db, f, correct=True)
                            continue
                        verdict = truth[int(f.ref.partition(":")[2])]
                        flags.append({"kind": f.kind, "title": f.title, "facts": json.loads(f.facts), "truth": verdict, "store": f"count{s}"})
                        data_check.decide(db, f, correct=verdict == "real")
                    db.flush()
                lesson = next((l for l in stock_memory.refresh(db, today) if l.kind == "usage"), None)
                r = out[mode]
                if lesson is None:
                    r["missed"] += waste > 0
                elif waste > 0 and abs(lesson.value - (1 + waste)) <= 0.1 * (1 + waste):
                    r["right"] += 1
                else:
                    r["wrong"] += 1
    return {"stores": stores, "weeks": weeks, "slips": slips, "results": out, "flags": flags}


# ---- sales: the forecast with import mistakes ----------------------------------------------------------------------
def sales_history(seed: int = 8) -> tuple[dict, dict, dict, dict, dict]:
    """(true sales, recorded sales, true orders, recorded orders, truth per odd day). Recorded = true with 5 days
    imported twice and 3 imported only partly, next to the holidays and the store's 2 untagged promotions."""
    rng = random.Random(seed)
    true = synthetic_history()
    start = min(true)
    real = {d: lift for d, (_, lift) in HOLIDAYS.items() if d in true}
    for d, lift in real.items():
        true[d] = round(true[d] * lift, 2)
    promos = {start + dt.timedelta(days=60), start + dt.timedelta(days=130)}  # already 1.6x in synthetic_history()
    avg = {d: rng.gauss(60, 2.5) * (1.05 if d in real or d in promos else 1) for d in true}
    orders = {d: max(1, round(true[d] / avg[d])) for d in true}
    normal = [d for d in sorted(true) if d not in real and d not in promos and d > start + dt.timedelta(days=28)]
    picks = rng.sample(normal, 8)
    rec, rec_orders, truth = dict(true), dict(orders), {}
    for i, d in enumerate(picks):
        share = 2.0 if i < 5 else rng.uniform(0.25, 0.4)
        rec[d], rec_orders[d] = round(true[d] * share, 2), max(1, round(orders[d] * share))
        truth[d] = "mistake"
    for d in list(real) + list(promos):
        truth[d] = "real"
    return true, rec, orders, rec_orders, truth


def sales() -> dict:
    """Forecast error against the true sales on the last TEST_DAYS days, made from: the recorded data as it is
    (no check); with every flagged day held out (the manager hasn't decided yet); and after the manager's decisions
    (mistakes left out, real days tagged with their name, so they are kept out of the normal pattern)."""
    true, rec, orders, rec_orders, truth = sales_history()
    end = max(rec) + dt.timedelta(days=1)
    twins = {d: rec_orders[d] for d, t in truth.items() if t == "mistake" and rec[d] > true[d]}  # a day imported twice: every order has a twin
    found = data_check.odd_days(rec, rec_orders, set(), end, weeks=40, twins=twins)
    flagged = {dt.date.fromisoformat(f["facts"]["date"]): f for f in found}
    names = {d: HOLIDAYS[d][0] if d in HOLIDAYS else "Promotion" for d, t in truth.items() if t == "real"}
    held = {d: v for d, v in rec.items() if d not in flagged}
    decided = {d: v for d, v in rec.items() if truth.get(d) != "mistake" or d not in flagged}
    tags = {d: names[d] for d in flagged if truth.get(d) == "real"}
    arms = {"no check": (rec, {}), "flagged days held out": (held, {}), "after the manager decides": (decided, tags)}
    days = sorted(rec)
    origins = days[-TEST_DAYS - HORIZON + 1:-HORIZON + 1]
    err = {}
    for name, (h, special) in arms.items():
        e = []
        for o in origins:
            past = {d: v for d, v in h.items() if d < o}
            for k in range(HORIZON):
                t = o + dt.timedelta(days=k)
                if t in true and t not in truth:  # normal days: what the forecast is for
                    p, _ = special_forecast(past, special, o, t)
                    if p:
                        e.append(abs(p - true[t]) / true[t])
        err[name] = sum(e) / len(e)
    caught = sum(1 for d in flagged if truth.get(d) == "mistake")
    return {"mistakes": sum(1 for t in truth.values() if t == "mistake"), "real_odd_days": sum(1 for t in truth.values() if t == "real"),
            "flagged": len(flagged), "mistakes_caught": caught, "real_flagged": sum(1 for d in flagged if truth.get(d) == "real"),
            "normal_flagged": sum(1 for d in flagged if d not in truth), "error": err,
            "flags": [f | {"truth": truth.get(d, "real"), "store": "sales"} for d, f in flagged.items()]}


# ---- edits: order lines with an extra zero, and real big changes ---------------------------------------------------
def edits() -> list[dict]:
    cases = [("Milk", "ml", 12000, 120000, "mistake"), ("Whipped cream", "ml", 2000, 20000, "mistake"),
             ("Strawberries", "g", 3000, 300, "mistake"), ("Crepe batter", "g", 8000, 800, "mistake"),
             ("Bananas", "pcs", 40, 140, "real"), ("Vanilla ice cream", "ml", 4000, 13000, "real"),
             ("Chocolate sauce", "ml", 3000, 900, "real")]
    out = []
    with fresh_db() as db:
        sup = Supplier(name="Dairy Farms Co.", email="s@example.com", lead_days=1)
        db.add(sup)
        truth = {}
        for i, (name, unit, drafted, entered, t) in enumerate(cases):
            ing = Ingredient(name=name, unit=unit, unit_cost=0.01, min_level=1, par_level=1, on_hand=0, supplier=sup)
            for w in range(3):  # usual orders before
                sent = dt.datetime(2026, 3, 1 + 7 * w, 18)
                db.add(PurchaseOrder(supplier=sup, status="received", sent_at=sent, created_at=sent, received_at=sent + dt.timedelta(days=1),
                                     lines=[PurchaseOrderLine(ingredient=ing, drafted_qty=drafted, qty=drafted)]))
            sent = dt.datetime(2026, 3, 22, 18)
            line = PurchaseOrderLine(ingredient=ing, drafted_qty=drafted, qty=entered)
            db.add(PurchaseOrder(supplier=sup, status="sent", sent_at=sent, created_at=sent, lines=[line]))
            db.flush()
            truth[f"po_line:{line.id}"] = t
        for f in data_check.screen(db, dt.date(2026, 3, 25)):
            out.append(f | {"truth": truth[f["ref"]], "store": "edits"})
    return out


# ---- verdicts: rules vs Claude ---------------------------------------------------------------------------------
def verdicts(flags: list[dict], llm) -> dict:
    """Scores the rules alone, Claude alone (asked about every flag) and the app's split (the rules where they are
    sure, Claude for the rest) on every flagged record. Claude sees one store's flags at a time, as in the app."""
    def score(vs):
        s = {"right": 0, "unsure": 0, "wrong": 0}
        for f, v in zip(flags, vs):
            s["unsure" if v["verdict"] == "unsure" else "right" if v["verdict"] == f["truth"] else "wrong"] += 1
        return s
    res = {"flags": len(flags), "by_kind": {k: sum(f["kind"] == k for f in flags) for k in ("count", "edit", "sales_day")},
           "rules": score([data_check.rules_verdict(f) for f in flags])}
    if not llm:
        return res
    stores = {}
    for i, f in enumerate(flags):
        stores.setdefault(f["store"], []).append(i)
    for arm, rules_first in (("claude", False), ("rules_then_claude", True)):
        vs = [None] * len(flags)
        for idx in stores.values():
            part, _ = data_check.review(llm, [flags[i] for i in idx], rules_first=rules_first)
            for i, v in zip(idx, part):
                vs[i] = v
        res[arm] = score(vs) | {"asked_claude": sum(1 for v in vs if v.get("ai"))}
        res[arm]["holidays_named"] = sum(1 for f, v in zip(flags, vs) if f["kind"] == "sales_day" and v["label"] and any(
            w in v["label"].lower() for w in ("eid", "founding", "promo")))
        res[arm]["wrong_examples"] = [{"what": f["title"], "truth": f["truth"], "verdict": v["verdict"], "why": v["why"]}
                                      for f, v in zip(flags, vs) if v["verdict"] not in ("unsure", f["truth"])]
        res[arm]["claude_examples"] = [{"what": f["title"], "truth": f["truth"], "verdict": v["verdict"], "why": v["why"], "label": v["label"]}
                                       for f, v in zip(flags, vs) if v.get("ai")][:12]
    return res


def run(llm=None, log=print) -> dict:
    c = counts()
    s = sales()
    e = edits()
    v = verdicts(c.pop("flags") + s.pop("flags") + e, llm)
    co, cn = c["results"]["off"], c["results"]["on"]
    log(f"  data check / counts ({c['stores']} stores, {c['slips']} slipped counts): right waste lessons {co['right']} -> {cn['right']}, "
        f"wrong {co['wrong']} -> {cn['wrong']}, missed {co['missed']} -> {cn['missed']}")
    log(f"  data check / sales ({s['mistakes']} import mistakes, caught {s['mistakes_caught']}; {s['real_flagged']} real days and "
        f"{s['normal_flagged']} normal days also flagged): forecast error " + ", ".join(f"{k} {x:.1%}" for k, x in s["error"].items()))
    line = f"  data check / verdicts on {v['flags']} flags: rules {v['rules']}"
    for arm in ("claude", "rules_then_claude"):
        if arm in v:
            line += f", {arm} { {k: v[arm][k] for k in ('right', 'unsure', 'wrong')} }"
    log(line)
    return {"counts": c, "sales": s, "verdicts": v}
