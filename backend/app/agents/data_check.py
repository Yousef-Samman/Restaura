"""Checks the data before the agents learn from it. One wrong record can teach an agent a wrong lesson: a count
typed as 200 instead of 2000 makes the stock agent think a third of the stock was wasted, and a day imported twice
makes the forecast think sales doubled. So, before learning:

1. Code finds the records that don't fit (screen()): every number in a flag is measured by code.
   - count: a stock count whose difference is more than half of what the recipes used since the last count.
   - edit: a manager's change to an order line of 3x or more (or a third or less).
   - delivery: a delivery that arrived before it was sent, or more than 10 days after.
   - sales_day: a day whose sales are 1.5x the usual for that weekday, or under 0.6x, and that is not tagged.
2. The rules say what they are sure of (an extra or missing zero, a day imported twice, a delivery before it
   was sent, a count that puts back the slip before it). Claude reads the rest with their facts and says whether each looks like a mistake
   or a real event and why, for example "the same orders counted twice" or "20 March is Eid al-Fitr". The evals
   showed this split is better than either alone: Claude asked about everything called some of the rules' sure
   cases wrong (see evals/data_check_eval.py). Without Claude, the rest stays "check this".
3. The manager decides (decide()). Until then the record is held out of learning; a record marked wrong stays out,
   and a real sales day can be tagged as a special day so the forecast learns its lift.

Nothing is changed or deleted: a flag only decides whether learning uses the record."""
import datetime as dt
import json
import statistics

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DataFlag, Ingredient, Order, PurchaseOrder, PurchaseOrderLine, SpecialDay, StockMove, Supplier
from .llm import LLM
from .stock_memory import STORE_UTC_OFFSET, WINDOW_DAYS, _recipe_use

COUNT_LIMIT = 0.5  # a count may differ from the recipes by up to half of what they used
EDIT_LIMIT = 3.0  # an edit up to 3x (or down to a third) is a choice, beyond it worth a look
DELIVERY_MAX_DAYS = 10
REVIEW_BATCH = 8  # records per Claude call, so a long list never runs out of answer space
SALES_HIGH, SALES_LOW = 1.5, 0.6  # against the median of the same weekday
SALES_WEEKS = 8
MIN_SAME_WEEKDAYS = 3
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _local(t: dt.datetime) -> dt.date:
    return (t + STORE_UTC_OFFSET).date()


def _round(x: float) -> float:
    return round(x, 2) if abs(x) < 10 else round(x)


# ---- 1. code finds what doesn't fit ------------------------------------------------------------------------------
def _edits(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    rows = db.execute(select(PurchaseOrderLine, PurchaseOrder.sent_at).join(PurchaseOrder)
                      .where(PurchaseOrderLine.drafted_qty > 0, PurchaseOrder.sent_at >= since)).all()
    for line, sent in rows:
        r = line.qty / line.drafted_qty
        if 1 / EDIT_LIMIT < r < EDIT_LIMIT:
            continue
        ing = line.ingredient
        past = [q for q, in db.execute(select(PurchaseOrderLine.qty).join(PurchaseOrder)
                                       .where(PurchaseOrderLine.ingredient_id == ing.id, PurchaseOrderLine.id != line.id,
                                              PurchaseOrder.status.in_(["sent", "received"]))
                                       .order_by(PurchaseOrder.sent_at.desc()).limit(4))]
        out.append({"kind": "edit", "ref": f"po_line:{line.id}",
                    "title": f"{ing.name}: {line.qty:g} {ing.unit} ordered, the agent drafted {line.drafted_qty:g}",
                    "facts": {"ingredient": ing.name, "unit": ing.unit, "date": _local(sent).isoformat(), "drafted": line.drafted_qty,
                              "entered": line.qty, "times_the_draft": _round(r), "other_recent_orders": past}})
    return out


def _counts(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    for m in db.scalars(select(StockMove).where(StockMove.kind == "count", StockMove.at >= since)):
        prev = db.scalar(select(func.max(StockMove.at)).where(StockMove.ingredient_id == m.ingredient_id, StockMove.at < m.at,
                                                              StockMove.kind.in_(["opening", "count"])))
        if prev is None:
            continue
        use = _recipe_use(db, m.ingredient_id, _local(prev), _local(m.at))
        if use <= 0 or abs(m.qty) <= COUNT_LIMIT * use:
            continue
        ing = db.get(Ingredient, m.ingredient_id)
        others = []
        for o in db.scalars(select(StockMove).where(StockMove.ingredient_id == ing.id, StockMove.kind == "count", StockMove.id != m.id)
                            .order_by(StockMove.at.desc()).limit(4)):
            p = db.scalar(select(func.max(StockMove.at)).where(StockMove.ingredient_id == ing.id, StockMove.at < o.at,
                                                               StockMove.kind.in_(["opening", "count"])))
            u = _recipe_use(db, ing.id, _local(p), _local(o.at)) if p else 0
            if u > 0:
                others.append(f"{o.qty / u:+.0%}")
        missing = -m.qty
        last = db.scalar(select(StockMove).where(StockMove.ingredient_id == ing.id, StockMove.kind == "count", StockMove.at < m.at)
                         .order_by(StockMove.at.desc()).limit(1))
        extra = {"counted": m.counted, "system_expected": round(m.counted - m.qty, 1)} if m.counted is not None else {}
        out.append({"kind": "count", "ref": f"stock_move:{m.id}",
                    "title": f"{ing.name} count: {abs(m.qty):g} {ing.unit} {'missing' if missing > 0 else 'extra'}, "
                             f"the recipes used {use:g}",
                    "facts": {"ingredient": ing.name, "unit": ing.unit, "date": _local(m.at).isoformat(), "since": _local(prev).isoformat(),
                              "difference": m.qty, "recipes_used": round(use, 1), "difference_vs_used": f"{m.qty / use:+.0%}",
                              "previous_count_difference": last.qty if last else None,
                              "other_counts_difference_vs_used": others} | extra})
    return out


def _deliveries(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "received", PurchaseOrder.sent_at >= since,
                                                     PurchaseOrder.received_at.is_not(None))):
        days = (_local(po.received_at) - _local(po.sent_at)).days
        if 0 <= days <= DELIVERY_MAX_DAYS:
            continue
        sup = db.get(Supplier, po.supplier_id)
        out.append({"kind": "delivery", "ref": f"po:{po.id}",
                    "title": f"{sup.name}: delivery recorded {days} days after the order was sent",
                    "facts": {"supplier": sup.name, "sent": _local(po.sent_at).isoformat(), "received": _local(po.received_at).isoformat(),
                              "days": days, "supplier_setting_days": sup.lead_days}})
    return out


def _sales_days(db: Session, today: dt.date) -> list[dict]:
    since = today - dt.timedelta(days=7 * (SALES_WEEKS + 4))
    rows = db.execute(select(Order.business_date, func.sum(Order.total), func.count(Order.id), func.max(Order.created_at))
                      .where(Order.business_date >= since, Order.business_date < today).group_by(Order.business_date)).all()
    last = {d: (t + STORE_UTC_OFFSET).strftime("%H:%M") for d, _, _, t in rows if t}
    same = select(Order.business_date, func.count(Order.id).label("n")).where(Order.business_date >= since, Order.business_date < today) \
        .group_by(Order.business_date, Order.created_at, Order.total).having(func.count(Order.id) > 1).subquery()
    twins = dict(db.execute(select(same.c.business_date, func.sum(same.c.n)).group_by(same.c.business_date)).all())
    return odd_days({d: s for d, s, _, _ in rows}, {d: n for d, _, n, _ in rows}, set(db.scalars(select(SpecialDay.date))), today,
                    last_order=last, twins=twins)


def odd_days(sales: dict[dt.date, float], orders: dict[dt.date, int], tagged: set[dt.date], today: dt.date,
             weeks: int = SALES_WEEKS, last_order: dict[dt.date, str] | None = None,
             twins: dict[dt.date, int] | None = None) -> list[dict]:
    """Untagged days in the last `weeks` weeks whose sales are far from the median of the same weekday. Clues kept
    with each: `last_order` (the time of the day's last order, store time) for an import that stopped early, and
    `twins` (orders with an identical twin: same time to the second and same total) for a day imported twice."""
    last_order, twins = last_order or {}, twins or {}
    out = []
    for d in sorted(sales):
        if d in tagged or d < today - dt.timedelta(days=7 * weeks) or d >= today:
            continue
        same = [p for p in (d - dt.timedelta(days=7 * k) for k in range(1, SALES_WEEKS + 1)) if p in sales and p not in tagged]
        if len(same) < MIN_SAME_WEEKDAYS:
            continue
        usual = statistics.median(sales[p] for p in same)
        r = sales[d] / usual if usual else 1
        if SALES_LOW <= r <= SALES_HIGH:
            continue
        near = {k: round(sales[d + dt.timedelta(days=o)]) for k, o in (("day_before", -1), ("day_after", 1)) if d + dt.timedelta(days=o) in sales}
        out.append({"kind": "sales_day", "ref": f"day:{d.isoformat()}",
                    "title": f"{WEEKDAYS[d.weekday()]} {d.day} {d.strftime('%B')}: sales {r:.1f}x a usual {WEEKDAYS[d.weekday()]}",
                    "facts": {"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "sales": round(sales[d]), "usual_for_weekday": round(usual),
                              "times_usual": round(r, 2), "orders": orders[d], "orders_with_an_identical_twin": twins.get(d, 0),
                              "usual_orders": round(statistics.median(orders[p] for p in same)),
                              "average_order": round(sales[d] / orders[d], 1),
                              "usual_average_order": round(statistics.median(sales[p] / orders[p] for p in same), 1),
                              "same_weekday_before": [round(sales[p]) for p in same[:4]]} | near
                    | ({"last_order": last_order[d], "usual_last_order": sorted(last_order[p] for p in same if p in last_order)[len(same) // 2]}
                       if d in last_order and all(p in last_order for p in same) else {})})
    return out


def screen(db: Session, today: dt.date | None = None) -> list[dict]:
    """Every record in the learning window that doesn't fit, as found by code. Already flagged records are skipped."""
    today = today or _local(dt.datetime.now(dt.UTC).replace(tzinfo=None))
    since = dt.datetime.combine(today, dt.time()) - dt.timedelta(days=WINDOW_DAYS)
    seen = set(db.scalars(select(DataFlag.ref)))
    found = _edits(db, since) + _counts(db, since) + _deliveries(db, since) + _sales_days(db, today)
    return [f for f in found if f["ref"] not in seen]


# ---- 2. is it a mistake or real? -----------------------------------------------------------------------------
def rules_verdict(f: dict) -> dict:
    """What code alone can tell: an extra or missing zero, a delivery before it was sent. The rest needs a person."""
    x = f["facts"]
    if f["kind"] == "edit":
        r = x["times_the_draft"]
        if 8.5 <= r <= 11.5 or 1 / 11.5 <= r <= 1 / 8.5:
            return {"verdict": "mistake", "why": f"{x['entered']:g} is about ten times {'more' if r > 1 else 'less'} than the draft, "
                                                 "which looks like an extra or missing zero.", "label": None}
    if f["kind"] == "count":
        prev = x.get("previous_count_difference") or 0
        if x["difference"] > 0 and prev < 0 and abs(x["difference"] + prev) <= 0.3 * abs(prev):
            return {"verdict": "real", "why": f"It puts back about the {abs(prev):g} {x['unit']} the previous count took off, "
                                              "so the previous count was the slip and this one is right.", "label": None}
        if x.get("system_expected"):
            r = x["counted"] / x["system_expected"]
            if 0.07 <= r <= 0.13 or 7 <= r <= 13:
                return {"verdict": "mistake", "why": f"{x['counted']:g} {x['unit']} counted where about {x['system_expected']:g} was expected: "
                                                     f"about ten times {'less' if r < 1 else 'more'}, which looks like a missing or extra zero.",
                        "label": None}
    if f["kind"] == "sales_day" and x.get("orders_with_an_identical_twin", 0) >= 0.4 * x["orders"]:
        return {"verdict": "mistake", "why": f"{x['orders_with_an_identical_twin']} of the {x['orders']} orders have an identical twin (same time "
                                             "and total), so the day's sales were imported twice.", "label": None}
    if f["kind"] == "delivery" and x["days"] < 0:
        return {"verdict": "mistake", "why": "It was marked received before the order was sent.", "label": None}
    return {"verdict": "unsure", "why": "This doesn't fit the usual pattern. Please check it before the agents learn from it.", "label": None}


SYSTEM = """You check a restaurant's records before its agents learn from them. The store is U Walk, a crepe and
dessert cafe in Riyadh, Saudi Arabia. Code found each record below because it doesn't fit the usual pattern, and
measured every number. For each one, say whether it is most likely a data mistake (a typing slip, a missing or extra
zero, a wrong unit, a day imported twice or only partly) or a real event the agents should learn from (a holiday,
a promotion, a busy weekend, a fridge failure), or unsure.

Rules:
- Use only the facts given and well-known public calendar facts for Saudi Arabia (national holidays, Eid, Ramadan,
  government payday on the 27th, school holidays). Name the event and date when you use one.
- Never invent a number or a reason that isn't in the facts. When the facts don't show which it is, say unsure and
  what the manager should check.
- Clues for a mistake: many orders with an identical twin (the day imported twice; more orders alone is not proof,
  busy days have more orders too), a last order hours before the usual one (the import stopped early), about 10x or
  0.1x of the usual or of what the system expected (an extra or missing zero).
- A count that puts back about what the previous count took off is the correction of a slip: real.
- Clues for a real day: a known holiday or event on that date, more orders with a normal average order.
- For a real sales day, give a short label to tag it with (for example "National Day", "Eid al-Fitr"); otherwise null.
- "why" is one or two plain sentences for a busy manager. No jargon."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["checks"], "properties": {"checks": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "verdict", "why", "label"],
    "properties": {"id": {"type": "integer"}, "verdict": {"type": "string", "enum": ["mistake", "real", "unsure"]},
                   "why": {"type": "string"}, "label": {"type": ["string", "null"]}}}}}}


def review(llm: LLM, flags: list[dict], rules_first: bool = True) -> tuple[list[dict], str]:
    """A verdict for each flag. The rules answer what they are sure of (an extra zero, a delivery before it was sent,
    a count that puts back the slip before it); Claude answers the rest, a few records per call. Whatever Claude doesn't
    answer keeps the rules' "check this". rules_first=False sends every flag to Claude (for the evals)."""
    out = [rules_verdict(f) for f in flags]
    ask = [i for i, v in enumerate(out) if v["verdict"] == "unsure" or not rules_first]
    if not ask or not llm.enabled:
        return out, "rules"
    got = 0
    for part in (ask[i:i + REVIEW_BATCH] for i in range(0, len(ask), REVIEW_BATCH)):
        task = "Records to check:\n" + json.dumps([{"id": i, "kind": flags[i]["kind"], "what": flags[i]["title"], "facts": flags[i]["facts"]}
                                                  for i in part], indent=1, default=str)
        ans = llm.json(SYSTEM, task, SCHEMA, effort="low", max_tokens=8000)
        for c in (ans or {"checks": []})["checks"]:
            if c["id"] in part and c["why"].strip():
                label = (c["label"] or "").strip()[:60] or None
                out[c["id"]] = {"verdict": c["verdict"], "why": c["why"].strip(),
                                "label": label if c["verdict"] == "real" and flags[c["id"]]["kind"] == "sales_day" else None, "ai": True}
                got += 1
    return out, "ai" if got else "rules"


def run(db: Session, llm: LLM, today: dt.date | None = None) -> list[DataFlag]:
    """Finds new records that don't fit, gets a verdict for each, and returns everything waiting for the manager."""
    found = screen(db, today)
    verdicts, _ = review(llm, found)
    for f, v in zip(found, verdicts):
        db.add(DataFlag(kind=f["kind"], ref=f["ref"], title=f["title"], facts=json.dumps(f["facts"], default=str),
                        verdict=v["verdict"], why=v["why"], label=v["label"], source="ai" if v.get("ai") else "rules"))
    db.flush()
    return waiting(db)


def waiting(db: Session) -> list[DataFlag]:
    return list(db.scalars(select(DataFlag).where(DataFlag.status == "waiting").order_by(DataFlag.id)))


# ---- 3. the manager decides -----------------------------------------------------------------------------------
def decide(db: Session, flag: DataFlag, correct: bool, label: str | None = None, at: dt.datetime | None = None) -> None:
    """correct=True keeps the record for learning; a sales day kept with a label is tagged as a special day.
    correct=False keeps it out of learning for good."""
    flag.status, flag.decided_at = ("kept" if correct else "wrong"), at or dt.datetime.now(dt.UTC).replace(tzinfo=None)
    if correct and flag.kind == "sales_day" and (label or "").strip():
        day = dt.date.fromisoformat(flag.ref.partition(":")[2])
        tag = db.scalar(select(SpecialDay).where(SpecialDay.date == day)) or SpecialDay(date=day)
        tag.label = " ".join(label.split())[:60]
        db.add(tag)


def as_dict(f: DataFlag) -> dict:
    return {"id": f.id, "kind": f.kind, "title": f.title, "facts": json.loads(f.facts), "verdict": f.verdict, "why": f.why,
            "label": f.label, "source": f.source, "status": f.status}
