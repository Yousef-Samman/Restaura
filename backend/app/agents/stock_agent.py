"""Stock-to-order agent: after close, turns sales into ingredient use, finds what is running low,
drafts supplier orders for the manager, and explains why."""
import json
from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import AgentRun, PurchaseOrder, PurchaseOrderLine
from ..stock import plan_reorders, stock_report
from .llm import LLM

SYSTEM = (
    "You are the stock agent of a restaurant. Code has already calculated stock levels and drafted supplier "
    "orders; the quantities are final and you must not change them. Write a short briefing for the manager: "
    "a one-sentence headline, one plain sentence per draft order saying why it is needed, and warnings for "
    "anything that looks wrong in the data. A negative stock level almost always means a delivery was not "
    "recorded. An ingredient that will run out before its supplier can deliver is urgent. Use plain words, "
    "no jargon, and only the facts given."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "order_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"supplier": {"type": "string"}, "note": {"type": "string"}},
                "required": ["supplier", "note"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "order_notes", "warnings"],
    "additionalProperties": False,
}


def run(db: Session, llm: LLM) -> dict:
    plan = plan_reorders(db)
    by_supplier = defaultdict(list)
    for p in plan:
        by_supplier[p["ingredient"].supplier].append(p)
    orders = []
    for supplier, lines in by_supplier.items():
        po = PurchaseOrder(supplier=supplier, status="draft")
        po.lines = [PurchaseOrderLine(ingredient=p["ingredient"], qty=p["qty"], reason=p["reason"]) for p in lines]
        db.add(po)
        orders.append(po)
    db.flush()

    report = stock_report(db)
    warnings = [f"{r['name']} is below zero ({r['on_hand']} {r['unit']}). A delivery was probably not recorded."
                for r in report if r["status"] == "negative"]
    urgent = [f"{p['ingredient'].name} may run out before {p['ingredient'].supplier.name} can deliver "
              f"({p['lead']}-day lead time)." for p in plan
              if p["daily"] and p["ingredient"].on_hand / p["daily"] < p["lead"]]
    plural = lambda n, w: f"{n} {w}" + ("" if n == 1 else "s")
    headline = (f"{plural(len(orders), 'supplier order')} drafted for {plural(len(plan), 'ingredient')}. Waiting for your approval."
                if orders else "No ingredient is low. No orders needed today.")
    notes = {po.supplier.name: " ".join(f"{l.ingredient.name}: {l.reason}" for l in po.lines) for po in orders}
    source = "rules"
    if llm.enabled:
        facts = {
            "stock": report,
            "draft_orders": [{"supplier": po.supplier.name, "lines": [
                {"ingredient": l.ingredient.name, "qty": l.qty, "unit": l.ingredient.unit, "calculation": l.reason}
                for l in po.lines]} for po in orders],
            "computed_warnings": warnings + urgent,
        }
        out = llm.json(SYSTEM, json.dumps(facts), SCHEMA, effort="medium")
        if out:
            source, headline = "ai", out["headline"]
            notes |= {n["supplier"]: n["note"] for n in out["order_notes"] if n["supplier"] in notes}
            warnings, urgent = out["warnings"], []
    for po in orders:
        po.note = notes[po.supplier.name]
    summary = {"headline": headline, "warnings": warnings + urgent, "order_ids": [po.id for po in orders]}
    db.add(AgentRun(agent="stock", source=source, summary=json.dumps(summary)))
    db.commit()
    return summary | {"source": source}
