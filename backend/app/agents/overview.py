"""Manager overview agent: reads every section and tells the manager what needs them first.
Code finds and ranks the items. With Claude, the agent looks at each section with its own tools, can hand low stock
to the stock agent (which drafts orders for approval), and writes the briefing from what the tools returned."""
import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import finance, forecast, routines, staff, stock
from ..models import AgentRun, Order, PurchaseOrder
from .llm import LLM

SYSTEM = (
    "You are the manager overview agent of a restaurant. Look at each section with your tools, then call finish with "
    "a briefing for the manager: a one-sentence headline and up to three short sentences on what to do first and why. "
    "If ingredients are low with no order placed and no draft is waiting, call run_stock_check once: the stock agent "
    "then drafts the orders, and the manager only has to approve them; say so in the briefing. Use only facts from the "
    "tools, plain words, no tool or field names, and SAR for money. Ingredients with an order on the way already have "
    "a supplier order placed: never tell the manager to order them again. forecast_today is for the whole day and "
    "sales_today is only so far (see time_now), so do not call sales slow from comparing the two. Leave out what needs "
    "no action. Ingredients that run out this week but are not low yet don't need ordering today: the daily stock "
    "check orders them once they would run out before a delivery, so mention them only if nothing more urgent needs "
    "the manager."
)
_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
TOOLS = [
    {"name": "check_sales", "description": "Sales so far today, the forecast for today and tomorrow, and the time now.", "input_schema": _NONE},
    {"name": "check_stock", "description": "Ingredients below zero, low with no order, low with an order on the way, and "
     "running out this week at the forecast sales.", "input_schema": _NONE},
    {"name": "check_orders", "description": "Supplier orders waiting for the manager's approval, and orders on the way.", "input_schema": _NONE},
    {"name": "check_staff", "description": "Staff who have not clocked in for their shift, and who came in late today.", "input_schema": _NONE},
    {"name": "check_routines", "description": "Checklists (opening, closing...) that are late today.", "input_schema": _NONE},
    {"name": "check_costs", "description": "Profit, margin and ingredient cost share of sales over the last 7 days, and the target.", "input_schema": _NONE},
    {"name": "get_ranked_priorities", "description": "What needs the manager, ranked by code from the same facts.", "input_schema": _NONE},
    {"name": "run_stock_check", "description": "Hand the low stock to the stock agent: it drafts supplier orders for the "
     "manager to approve. Nothing is sent without approval. Use at most once.", "input_schema": _NONE},
    {"name": "finish", "description": "End with the briefing.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["headline", "points"],
        "properties": {"headline": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}, "maxItems": 3}}}},
]


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


def _plural(n: int, w: str) -> str:
    return f"{n} {w}" + ("" if n == 1 else "s")


class _Look:
    """One overview run: the tools read the facts, and the stock check is handed to the stock agent."""

    def __init__(self, db: Session, llm: LLM):
        self.db, self.llm = db, llm
        self.f = facts(db)
        self.finished: dict | None = None
        self.delegated: dict | None = None
        self.trace: list[dict] = []

    def step(self, label: str, detail: str, ok: bool = True) -> None:
        self.trace.append({"label": label, "detail": detail, "ok": ok})

    def call(self, name: str, args: dict):
        f = self.f
        if name == "check_sales":
            self.step("Checked today's sales", f"{f['sales_today']:g} SAR so far, {f['forecast_today']:g} SAR expected today")
            return {k: f[k] for k in ("time_now", "sales_today", "forecast_today", "forecast_tomorrow")}, True
        if name == "check_stock":
            n = len(f["negative_stock"]) + len(f["low_stock"])
            self.step("Checked stock", f"{_plural(n, 'ingredient')} low or below zero with no order" if n else "Nothing low without an order")
            return {k: f[k] for k in ("negative_stock", "low_stock", "low_stock_order_on_the_way", "runs_out_this_week_no_order")}, True
        if name == "check_orders":
            n = len(f["drafts_waiting"])
            self.step("Checked supplier orders", f"{_plural(n, 'draft')} waiting, {f['orders_on_the_way']} on the way")
            return {k: f[k] for k in ("drafts_waiting", "orders_on_the_way")}, True
        if name == "check_staff":
            self.step("Checked staff", f"{len(f['staff_missing'])} not clocked in, {len(f['staff_late_today'])} late")
            return {k: f[k] for k in ("staff_missing", "staff_late_today")}, True
        if name == "check_routines":
            self.step("Checked checklists", f"{_plural(len(f['routines_overdue']), 'checklist')} late" if f["routines_overdue"] else "No checklist late")
            return {"routines_overdue": f["routines_overdue"]}, True
        if name == "check_costs":
            share = f["food_cost_share_7d"]
            self.step("Checked costs", f"Ingredient cost {share:.0%} of sales this week" if share else "No sales this week")
            return {k: f[k] for k in ("profit_7d", "margin_7d", "food_cost_share_7d")} | {"food_cost_target": finance.FOOD_COST_TARGET}, True
        if name == "get_ranked_priorities":
            p = priorities(f)
            self.step("Ranked what needs you", _plural(len([x for x in p if x["level"] != "ok"]), "item"))
            return [x["text"] for x in p], True
        if name == "run_stock_check":
            if self.delegated is not None:
                return "The stock check already ran in this overview.", False
            from . import stock_agent
            self.delegated = stock_agent.run(self.db, self.llm)
            n = len(self.delegated["order_ids"])
            self.step("Asked the stock agent to check stock", self.delegated["headline"])
            self.f = facts(self.db)  # the new drafts are now waiting for approval
            return {"orders_drafted": n, "stock_agent_said": self.delegated["headline"], "warnings": self.delegated["warnings"]}, True
        if name == "finish":
            self.finished = {"headline": args["headline"], "points": args["points"][:3]}
            self.step("Wrote the briefing", args["headline"])
            return "Done.", True
        return f"There is no tool called {name}.", False


def run(db: Session, llm: LLM) -> dict:
    look = _Look(db, llm)
    if llm.enabled and llm.run_tools(SYSTEM, "Tell the manager what needs them first today.", TOOLS, look.call,
                                     lambda: look.finished is not None):
        out, source = look.finished, "ai"
    else:
        if llm.enabled:
            look.step("Claude didn't finish, so the rules wrote the briefing", "", ok=False)
        for tool in ("check_sales", "check_stock", "check_orders", "check_staff", "check_routines", "check_costs"):
            look.call(tool, {})
        p = priorities(look.f)
        out, source = {"headline": p[0]["text"], "points": [x["text"] for x in p[1:4]]}, "rules"
        look.step("Ranked what needs you", out["headline"])
    out = out | {"steps": look.trace}
    if look.delegated is not None:
        out["order_ids"] = look.delegated["order_ids"]
    db.add(AgentRun(agent="overview", source=source, summary=json.dumps(out)))
    db.commit()
    return out | {"source": source}
