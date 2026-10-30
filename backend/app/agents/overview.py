"""Manager overview agent: reads every section and tells the manager what needs them first.
Code finds and ranks the items; Claude (when a key is set) writes the short briefing from those facts only."""
import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import finance, forecast, stock
from ..models import AgentRun, Order, PurchaseOrder
from .llm import LLM

SYSTEM = (
    "You are the manager overview agent of a restaurant. You get facts that code has already calculated. "
    "Write a briefing for the manager: a one-sentence headline and up to three short sentences on what to do first "
    "and why. Use only the facts given, plain words, and SAR for money."
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
        "sales_today": round(sales_today, 2), "forecast_today": fc["days"][0]["sales"], "forecast_tomorrow": fc["days"][1]["sales"],
        "profit_7d": fin["profit"], "margin_7d": round(fin["profit"] / fin["sales"], 3) if fin["sales"] else None,
        "food_cost_share_7d": round(fin["food_cost"] / fin["sales"], 3) if fin["sales"] else None,
        "drafts_waiting": [{"supplier": po.supplier.name, "lines": len(po.lines)} for po in drafts],
        "orders_on_the_way": sent,
        "negative_stock": [r["name"] for r in report if r["status"] == "negative"],
        "below_minimum": [r["name"] for r in report if r["status"] == "low"],
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
    if f["below_minimum"]:
        out.append({"level": "warn", "text": f"{len(f['below_minimum'])} ingredients are at or below their minimum.", "go": "stock"})
    soon = [i for i in f["runs_out_this_week_no_order"] if i["name"] not in f["below_minimum"]]
    if soon:
        out.append({"level": "info", "text": f"{len(soon)} {'more ' if f['below_minimum'] else ''}{'ingredient' if len(soon) == 1 else 'ingredients'} will run out this week at the expected sales, with no order placed yet.", "go": "forecast"})
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
