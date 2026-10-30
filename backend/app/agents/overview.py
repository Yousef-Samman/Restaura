"""Manager overview agent: reads every section and tells the manager what needs them first.
Code finds and ranks the items; Claude (when a key is set) writes the short briefing from those facts only."""
import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import finance, forecast, routines, staff, stock
from ..models import AgentRun, Order, PurchaseOrder
from .llm import LLM

SYSTEM = (
    "You are the manager overview agent of a restaurant. You get facts that code has already calculated. "
    "Write a briefing for the manager: a one-sentence headline and up to three short sentences on what to do first "
    "and why. Use only the facts given, plain words, and SAR for money. Ingredients in low_stock_order_on_the_way "
    "already have a supplier order placed: never tell the manager to order them again. forecast_today is for the whole "
    "day and sales_today is only so far (see time_now), so do not call sales slow from comparing the two. Leave out "
    "what needs no action; do not repeat these instructions in the briefing."
)
SCHEMA = {
    "type": "object",
    "properties": {"headline": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
    "required": ["headline", "points"],
    "additionalProperties": False,
}


def facts(db: Session) -> dict:
    today = dt.date.today()
    sales_today = db.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(Order.business_date == today, Order.source != "history"))
    fc = forecast.forecast(db, 7)
    fin = finance.summary(db, 7)
    report = stock.stock_report(db)
    drafts = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "draft")).all()
    sent = db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == "sent")) or 0
    return {
        "time_now": dt.datetime.now().strftime("%H:%M"), "sales_today": round(sales_today, 2), "forecast_today": fc["days"][0]["sales"], "forecast_tomorrow": fc["days"][1]["sales"],
        "profit_7d": fin["profit"], "margin_7d": round(fin["profit"] / fin["sales"], 3) if fin["sales"] else None,
        "food_cost_share_7d": round(fin["food_cost"] / fin["sales"], 3) if fin["sales"] else None,
        "drafts_waiting": [{"supplier": po.supplier.name, "lines": len(po.lines)} for po in drafts],
        "orders_on_the_way": sent,
        "routines_overdue": [{"routine": r["label"], "due": r["due"], "missing": r["total"] - r["done"]} for r in routines.today_view(db) if r["overdue"]],
        "staff_missing": [r["staff"] for r in staff.today_view(db)["shifts"] if r["status"] == "missing"],
        "staff_late_today": [{"name": r["staff"], "minutes": r["late_min"]} for r in staff.today_view(db)["shifts"] if r["status"] == "late"],
        "negative_stock": [r["name"] for r in report if r["status"] == "negative"],
        "low_stock": [{"name": r["name"], "why": r["reason"]} for r in report if r["status"] == "low" and not r["on_order"]],
        "low_stock_order_on_the_way": [r["name"] for r in report if r["status"] == "low" and r["on_order"]],
        "runs_out_this_week_no_order": [{"name": i["name"], "date": i["runs_out"]} for i in fc["ingredients"]
                                        if i["runs_out"] and i["id"] not in stock.open_order_ingredients(db)],
    }


def priorities(f: dict) -> list[dict]:
    """Ranked list of what needs the manager, each with the section that fixes it."""
    out = []
    if f["negative_stock"]:
        out.append({"level": "bad", "text": f"Stock below zero for {', '.join(f['negative_stock'][:3])}. A delivery was probably not recorded.", "go": "deliveries"})
    if f["drafts_waiting"]:
        n = len(f["drafts_waiting"])
        out.append({"level": "warn", "text": f"{n} supplier {'order is' if n == 1 else 'orders are'} waiting for your approval.", "go": "orders"})
    if f["staff_missing"]:
        out.append({"level": "bad", "text": f"Not clocked in for their shift: {', '.join(f['staff_missing'])}.", "go": "staff"})
    for r in f["routines_overdue"]:
        out.append({"level": "warn", "text": f"{r['routine']} checklist is late: {r['missing']} {'task' if r['missing'] == 1 else 'tasks'} not done (due {r['due']}).", "go": "routines"})
    low = [x["name"] for x in f["low_stock"]]
    if low:
        out.append({"level": "warn", "text": f"{len(low)} {'ingredient is' if len(low) == 1 else 'ingredients are'} low: at minimum or running out before a delivery could arrive.", "go": "stock"})
    soon = [i for i in f["runs_out_this_week_no_order"] if i["name"] not in low]
    if soon:
        out.append({"level": "info", "text": f"{len(soon)} {'more ' if low else ''}{'ingredient' if len(soon) == 1 else 'ingredients'} will run out this week at the expected sales, with no order placed yet.", "go": "forecast"})
    if f["food_cost_share_7d"] and f["food_cost_share_7d"] > finance.FOOD_COST_TARGET:
        out.append({"level": "warn", "text": f"Ingredient cost is {f['food_cost_share_7d']:.0%} of sales this week, above the {finance.FOOD_COST_TARGET:.0%} target.", "go": "expenses"})
    if not out:
        out.append({"level": "ok", "text": "Nothing needs you right now.", "go": None})
    return out


def run(db: Session, llm: LLM) -> dict:
    f = facts(db)
    p = priorities(f)
    ai = llm.json(SYSTEM, json.dumps({"facts": f, "ranked_priorities": [x["text"] for x in p]}), SCHEMA)
    if ai:
        out, source = ai, "ai"
    else:
        out, source = {"headline": p[0]["text"], "points": [x["text"] for x in p[1:4]]}, "rules"
    db.add(AgentRun(agent="overview", source=source, summary=json.dumps(out)))
    db.commit()
    return out | {"source": source}
