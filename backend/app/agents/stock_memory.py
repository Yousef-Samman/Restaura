"""What the stock agent learns from what happened after its orders, kept as suggestions for the manager.

Three signals the app already records:
- order_size: the manager's edits to the agent's drafts. If they raise (or cut) the same ingredient on most recent
  orders, the agent suggests ordering that much more (or less) from now on.
- lead_time: when a supplier's orders were sent and when they arrived. If deliveries keep taking a different number
  of days than the supplier's setting, the agent suggests the real number.
- usage: stock counts against what the recipes say was used. If counts keep coming up short (waste, bigger
  portions), the agent suggests ordering that much more.

Code measures every number; nothing changes until the manager applies a suggestion (apply())."""
import datetime as dt
import math
import statistics
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DataFlag, Ingredient, Lesson, Order, OrderLine, PurchaseOrder, PurchaseOrderLine, RecipeLine, StockMove, Supplier

WINDOW_DAYS = 90  # how far back the agent looks
RECENT_ORDERS = 4  # an edit counts as a habit when it happens on most of the last few orders
MIN_EDITS = 3
EDIT_NOISE = 0.05  # edits smaller than 5% are not a habit
MIN_DELIVERIES = 2
MIN_COUNTS = 2
COUNT_NOISE = 0.05  # counts within 5% of the recipes are fine
FACTOR_RANGE = (0.5, 1.5)  # a learned factor never moves an order beyond this, same as the agent's own limit
SNOOZE_DAYS = 30  # a dismissed suggestion comes back only after this, or when the evidence moves a lot
STORE_UTC_OFFSET = dt.timedelta(hours=3)


def _pct(f: float) -> str:
    return f"{abs(f - 1):.0%}"


def _clamp(f: float) -> float:
    return round(max(FACTOR_RANGE[0], min(FACTOR_RANGE[1], f)), 2)


def _since_applied(db: Session, subject: str, since: dt.datetime) -> dt.datetime:
    """Evidence from before the manager last applied a lesson about this subject was measured against the old
    setting, so only what came after counts."""
    last = db.scalar(select(func.max(Lesson.decided_at)).where(Lesson.subject == subject, Lesson.status == "applied"))
    return max(since, last) if last else since


def held(db: Session, prefix: str) -> set[str]:
    """Records the data check is holding out of learning (waiting for the manager, or marked wrong), as refs such
    as "po_line:5"; see data_check.py."""
    return set(db.scalars(select(DataFlag.ref).where(DataFlag.status.in_(["waiting", "wrong"]), DataFlag.ref.like(f"{prefix}:%"))))


def _ids(refs: set[str]) -> set[int]:
    return {int(r.partition(":")[2]) for r in refs}


def _order_size(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    skip = _ids(held(db, "po_line"))
    for ing in db.scalars(select(Ingredient)):
        start = _since_applied(db, f"ingredient:{ing.id}", since)
        lines = db.execute(select(PurchaseOrderLine.qty, PurchaseOrderLine.drafted_qty).join(PurchaseOrder)
                           .where(PurchaseOrderLine.ingredient_id == ing.id, PurchaseOrderLine.drafted_qty > 0,
                                  PurchaseOrder.status.in_(["sent", "received"]), PurchaseOrder.sent_at >= start,
                                  PurchaseOrderLine.id.not_in(skip))
                           .order_by(PurchaseOrder.sent_at.desc()).limit(RECENT_ORDERS)).all()
        ratios = [q / d for q, d in lines]
        ups = [r for r in ratios if r > 1 + EDIT_NOISE]
        downs = [r for r in ratios if r < 1 - EDIT_NOISE]
        habit = ups if len(ups) >= MIN_EDITS else downs if len(downs) >= MIN_EDITS else None
        if not habit:
            continue
        f = statistics.median(habit)
        value = _clamp(ing.order_factor * f)
        if abs(value - ing.order_factor) < EDIT_NOISE:
            continue
        verb = "raised" if f > 1 else "cut"
        out.append({"kind": "order_size", "subject": f"ingredient:{ing.id}", "current": ing.order_factor, "value": value,
                    "evidence": len(lines),
                    "title": f"Order {_pct(f)} {'more' if f > 1 else 'less'} {ing.name.lower()}",
                    "detail": f"You {verb} {ing.name} on {len(habit)} of the last {len(lines)} orders, by {_pct(f)} on average. "
                              f"Apply it and future orders start there, so you edit less."})
    return out


def _lead_time(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    skip = _ids(held(db, "po"))
    for sup in db.scalars(select(Supplier).where(Supplier.active)):
        pos = db.execute(select(PurchaseOrder.sent_at, PurchaseOrder.received_at)
                         .where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status == "received",
                                PurchaseOrder.sent_at >= _since_applied(db, f"supplier:{sup.id}", since), PurchaseOrder.received_at.is_not(None), PurchaseOrder.id.not_in(skip))).all()
        days = [((r + STORE_UTC_OFFSET).date() - (s + STORE_UTC_OFFSET).date()).days for s, r in pos]
        if len(days) < MIN_DELIVERIES:
            continue
        real = max(0, round(statistics.median(days)))
        if real == sup.lead_days:
            continue
        out.append({"kind": "lead_time", "subject": f"supplier:{sup.id}", "current": sup.lead_days, "value": real,
                    "evidence": len(days),
                    "title": f"{sup.name} delivers in {real} {'day' if real == 1 else 'days'}, not {sup.lead_days}",
                    "detail": f"Its last {len(days)} deliveries took {', '.join(str(d) for d in sorted(days))} days from sending to arrival. "
                              + ("Ordering on the right day avoids running out while you wait." if real > sup.lead_days
                                 else "Orders can go a little later, so less stock sits waiting.")})
    return out


def _recipe_use(db: Session, ingredient_id: int, after: dt.date, until: dt.date) -> float:
    return db.scalar(select(func.sum(OrderLine.qty * RecipeLine.qty))
                     .join(RecipeLine, RecipeLine.menu_item_id == OrderLine.menu_item_id)
                     .join(Order, Order.id == OrderLine.order_id)
                     .where(RecipeLine.ingredient_id == ingredient_id, Order.business_date > after,
                            Order.business_date <= until)) or 0.0


def _usage(db: Session, since: dt.datetime) -> list[dict]:
    out = []
    skip = _ids(held(db, "stock_move"))
    counts = defaultdict(list)
    for m in db.scalars(select(StockMove).where(StockMove.kind == "count", StockMove.at >= since).order_by(StockMove.at)):
        if m.at >= _since_applied(db, f"ingredient:{m.ingredient_id}", since):
            counts[m.ingredient_id].append(m)
    for ing_id, moves in counts.items():
        ing = db.get(Ingredient, ing_id)
        anchor = db.scalar(select(func.max(StockMove.at)).where(StockMove.ingredient_id == ing_id, StockMove.at < moves[0].at,
                                                                 StockMove.kind.in_(["opening", "count"])))
        if anchor is None:  # the first count is the starting point
            anchor, moves = moves[0].at, moves[1:]
        gaps, prev, carry = [], (anchor + STORE_UTC_OFFSET).date(), 0.0
        for m in moves:
            if m.id in skip:
                carry += m.qty  # a held count doesn't end a period: the next good count covers both
                continue
            day = (m.at + STORE_UTC_OFFSET).date()
            use = _recipe_use(db, ing_id, prev, day)
            if use > 0:
                gaps.append(-(m.qty + carry) / use)  # a count that comes up short = more used than the recipes say
            prev, carry = day, 0.0
        if len(gaps) < MIN_COUNTS or not all(g > COUNT_NOISE for g in gaps):
            continue  # only steady shortfalls; one odd count is a mistake, not a pattern
        g = sum(gaps) / len(gaps)
        value = _clamp(ing.order_factor * (1 + g))
        if abs(value - ing.order_factor) < COUNT_NOISE:
            continue
        out.append({"kind": "usage", "subject": f"ingredient:{ing.id}", "current": ing.order_factor, "value": value,
                    "evidence": len(gaps),
                    "title": f"{ing.name}: {g:.0%} more used than the recipes say",
                    "detail": f"Your last {len(gaps)} counts came up short by {', '.join(f'{x:.0%}' for x in gaps)} of what the recipes used, "
                              f"so orders based on recipes run short. Usually waste or bigger portions: worth a look at the station too."})
    return out


def refresh(db: Session, today: dt.date | None = None) -> list[Lesson]:
    """Re-learns from the latest orders, deliveries and counts, and returns the suggestions waiting for the manager."""
    now = dt.datetime.combine(today, dt.time()) if today else dt.datetime.now(dt.UTC).replace(tzinfo=None)
    since = now - dt.timedelta(days=WINDOW_DAYS)
    found = _order_size(db, since) + _lead_time(db, since) + _usage(db, since)
    keys = {(f["kind"], f["subject"]) for f in found}
    for old in db.scalars(select(Lesson).where(Lesson.agent == "stock", Lesson.status == "suggested")):
        if (old.kind, old.subject) not in keys:
            db.delete(old)  # the pattern is gone, so the suggestion goes too
    for f in found:
        last = db.scalar(select(Lesson).where(Lesson.agent == "stock", Lesson.kind == f["kind"], Lesson.subject == f["subject"])
                         .order_by(Lesson.id.desc()))
        if last and last.status == "suggested":
            for k in ("title", "detail", "current", "value", "evidence"):
                setattr(last, k, f[k])
            continue
        if last and last.status == "dismissed" and last.decided_at and last.decided_at > now - dt.timedelta(days=SNOOZE_DAYS) \
                and abs(last.value - f["value"]) < 0.1 * max(abs(last.value), 1):
            continue  # the manager said no recently and nothing much has changed
        db.add(Lesson(agent="stock", **f))
    db.flush()
    return pending(db)


def pending(db: Session) -> list[Lesson]:
    return list(db.scalars(select(Lesson).where(Lesson.agent == "stock", Lesson.status == "suggested").order_by(Lesson.id)))


def applied(db: Session) -> list[Lesson]:
    return list(db.scalars(select(Lesson).where(Lesson.agent == "stock", Lesson.status == "applied")
                           .order_by(Lesson.decided_at.desc()).limit(8)))


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def apply(db: Session, lesson: Lesson, at: dt.datetime | None = None) -> None:
    kind, _, sid = lesson.subject.partition(":")
    if kind == "supplier":
        db.get(Supplier, int(sid)).lead_days = int(lesson.value)
    else:
        db.get(Ingredient, int(sid)).order_factor = lesson.value
    lesson.status, lesson.decided_at = "applied", at or _now()


def dismiss(lesson: Lesson, at: dt.datetime | None = None) -> None:
    lesson.status, lesson.decided_at = "dismissed", at or _now()


def line_suggestion(db: Session, ingredient: Ingredient, qty: float) -> dict | None:
    """For a draft order line: the quantity a waiting suggestion about this ingredient would give, for the manager
    to use or ignore. The draft itself is not changed."""
    lesson = db.scalar(select(Lesson).where(Lesson.agent == "stock", Lesson.status == "suggested",
                                            Lesson.subject == f"ingredient:{ingredient.id}").order_by(Lesson.id.desc()))
    if not lesson or not lesson.current:
        return None
    step = 1 if ingredient.unit == "pcs" else 100
    new = math.ceil(qty * lesson.value / lesson.current / step) * step
    if new == qty:
        return None
    return {"lesson_id": lesson.id, "qty": new, "title": lesson.title, "why": lesson.detail}


def as_dict(l: Lesson) -> dict:
    return {"id": l.id, "kind": l.kind, "title": l.title, "detail": l.detail, "current": l.current, "value": l.value,
            "evidence": l.evidence, "status": l.status, "at": (l.decided_at or l.created_at).isoformat() + "Z"}
