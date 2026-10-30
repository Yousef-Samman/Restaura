"""Stock-to-order agent: after close, it checks stock, sales forecast, open orders and recipes with its own tools,
drafts supplier orders for the manager, and explains why. Code calculates every quantity; the agent decides what to
look at, what to warn about, and may change a quantity by up to half (for example for a busy week in the forecast),
with a reason the manager sees. Without Claude, the same tools run in a fixed order (the rules)."""
import json
import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import forecast
from ..models import AgentRun, PurchaseOrder, PurchaseOrderLine
from ..stock import items_without_recipe, plan_reorders, stock_report
from . import stock_memory
from .llm import LLM

SYSTEM = (
    "You are the stock agent of a restaurant. After the branch closes you check stock and draft supplier orders "
    "for the manager to approve. Use the tools: look at stock, the sales forecast, open orders and recipes, then "
    "get the reorder plan. Code has calculated every order quantity from the last 7 days' use. If the forecast "
    "(by_day) shows that what arrives, plus what is left, won't last through the busy days after the delivery, raise "
    "the quantity with adjust_quantity; if the coming days are clearly quieter, you may lower it. Changes are at "
    "most half up or down and need a reason that quotes the forecast; otherwise keep the code's quantity. Draft one order per supplier for the ingredients in the plan, each with one plain sentence saying why it is "
    "needed. Then call finish with a one-sentence headline and warnings for anything that looks wrong: a negative "
    "stock level almost always means a delivery was not recorded; an ingredient that will run out before its "
    "supplier can deliver is urgent; a menu item with no recipe never reduces stock; the forecast may show an "
    "ingredient running short this week that is not low yet. Use plain words, no jargon and no tool or field names, and only facts from the "
    "tools. Also check what you learned from earlier orders; suggestions waiting for the manager are theirs to apply, "
    "so mention them in the headline but never act on them. Copy numbers exactly as the tools give them; never do your own arithmetic, because a number the manager "
    "can't find on the order makes the briefing harder to trust."
)

TASK = "The branch has closed for the day. Check the stock and draft today's supplier orders."

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
TOOLS = [
    {"name": "check_stock", "description": "Every ingredient: on hand, minimum, par level, average daily use over the last "
     "7 days, days left, supplier lead time, status (ok, low, negative) and whether an order is already open.",
     "input_schema": _NONE},
    {"name": "check_sales_forecast", "description": "Sales forecast for the next 7 days (today first) and, through the "
     "recipes, how much of each ingredient those sales need each day (by_day) and in total, how much is short and the "
     "day it runs out. Compare by_day with the 7-day average use the order is based on.", "input_schema": _NONE},
    {"name": "check_open_orders", "description": "Supplier orders that are drafted or sent but not received yet.",
     "input_schema": _NONE},
    {"name": "check_what_i_learned", "description": "What you learned from earlier orders: the manager's edits to your "
     "drafts, how many days each supplier really takes to deliver, and stock counts against the recipes. Lessons the "
     "manager applied are already in the plan's quantities. Suggestions still waiting are for the manager to decide: "
     "never change a quantity because of one; mention them in the briefing instead.", "input_schema": _NONE},
    {"name": "check_recipes", "description": "Menu items that have no recipe, so their sales don't reduce any stock.",
     "input_schema": _NONE},
    {"name": "get_reorder_plan", "description": "The ingredients that need ordering today, with the quantity code "
     "calculated and how, grouped by supplier. Ingredients with an open order are left out.", "input_schema": _NONE},
    {"name": "adjust_quantity", "description": "Change one planned quantity before drafting its order. Allowed range: "
     "half to one and a half times the code's quantity, and never less than what is used until the delivery arrives. "
     "Rounded up to 100 g or ml, or 1 piece.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["ingredient", "qty", "reason"],
        "properties": {"ingredient": {"type": "string"}, "qty": {"type": "number"},
                       "reason": {"type": "string", "description": "Why, citing the forecast numbers, for the manager."}}}},
    {"name": "draft_order", "description": "Draft one supplier order for the manager to approve. Quantities come from the "
     "reorder plan.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["supplier", "ingredients", "note"],
        "properties": {"supplier": {"type": "string"},
                       "ingredients": {"type": "array", "items": {"type": "string"}},
                       "note": {"type": "string", "description": "Why this order is needed, for the manager."}}}},
    {"name": "finish", "description": "End the check once every order in the plan is drafted.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["headline", "warnings"],
        "properties": {"headline": {"type": "string"}, "warnings": {"type": "array", "items": {"type": "string"}}}}},
]


CHANGE_MARK = " The agent changed "


def split_change(reason: str | None) -> tuple[str, dict | None]:
    """An order line's reason, split into the code's reasoning and the agent's change to it, if any:
    ('...', {'from': 7300.0, 'to': 10900.0, 'reason': '...'})."""
    base, mark, rest = (reason or "").partition(CHANGE_MARK)
    if not mark:
        return base, None
    try:
        nums, _, why = rest.partition(": ")
        old, _, new = nums.partition(" to ")
        return base, {"from": float(old), "to": float(new.split(" ")[0]), "reason": why.strip()}
    except ValueError:
        return base, None


def _plural(n: int, w: str) -> str:
    return f"{n} {w}" + ("" if n == 1 else "s")


class _Check:
    """One stock check. Each tool reads the database or stages an order; nothing is written until the check ends."""

    def __init__(self, db: Session):
        self.db = db
        self.plan = plan_reorders(db)
        for p in self.plan:
            p["code_qty"] = p["qty"]
        self.by_supplier = defaultdict(list)
        for p in self.plan:
            self.by_supplier[p["ingredient"].supplier.name].append(p)
        self.staged: dict[str, dict] = {}  # supplier -> {"lines": [plan rows], "note": str}
        self.finished: dict | None = None
        self.trace: list[dict] = []
        self.waiting: list = []

    def step(self, label: str, detail: str, ok: bool = True) -> None:
        self.trace.append({"label": label, "detail": detail, "ok": ok})

    def computed_warnings(self) -> list[str]:
        warnings = [f"{r['name']} is below zero ({r['on_hand']} {r['unit']}). A delivery was probably not recorded."
                    for r in stock_report(self.db) if r["status"] == "negative"]
        warnings += [f"{name} has no recipe, so its sales don't reduce stock. Add its recipe to keep stock right."
                     for name in items_without_recipe(self.db)]
        warnings += [f"{p['ingredient'].name} may run out before {p['ingredient'].supplier.name} can deliver "
                     f"({p['lead']}-day lead time)." for p in self.plan
                     if p["daily"] and p["ingredient"].on_hand / p["daily"] < p["lead"]]
        return warnings

    def call(self, name: str, args: dict):
        """Runs one tool. Returns (result, ok)."""
        if name == "check_stock":
            rows = stock_report(self.db)
            low = [r["name"] for r in rows if r["status"] != "ok"]
            self.step("Checked stock levels", f"{_plural(len(rows), 'ingredient')}, {len(low)} low or below zero"
                      + (f": {', '.join(low[:4])}{'…' if len(low) > 4 else ''}" if low else ""))
            return [{k: r[k] for k in ("name", "unit", "on_hand", "min_level", "par_level", "avg_daily_use", "days_left",
                                       "lead_days", "status", "on_order")} for r in rows], True
        if name == "check_sales_forecast":
            f = forecast.forecast(self.db)
            short = [i for i in f["ingredients"] if i["runs_out"]]
            self.step("Read the 7-day sales forecast", f"{_plural(len(short), 'ingredient')} would run out this week"
                      + (f": {', '.join(i['name'] for i in short[:4])}" if short else ""))
            return {"days": [{"date": d["date"], "sales": d["sales"]} for d in f["days"]],
                    "ingredients": [{k: i[k] for k in ("name", "unit", "need", "by_day", "on_hand", "short", "runs_out")}
                                    for i in f["ingredients"] if i["need"]]}, True
        if name == "check_open_orders":
            pos = list(self.db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(["draft", "sent"]))))
            self.step("Checked open orders", f"{_plural(len(pos), 'order')} already open" if pos else "No open orders")
            return [{"supplier": po.supplier.name, "status": po.status,
                     "lines": [{"ingredient": l.ingredient.name, "qty": l.qty, "unit": l.ingredient.unit} for l in po.lines]}
                    for po in pos], True
        if name == "check_what_i_learned":
            waiting, used = stock_memory.refresh(self.db), stock_memory.applied(self.db)
            self.waiting = waiting
            self.step("Checked what it has learned", f"{_plural(len(waiting), 'new suggestion')} for you"
                      + (f": {'; '.join(l.title for l in waiting[:3])}" if waiting else "") + (f"; {len(used)} already applied" if used else ""))
            return {"waiting_for_the_manager": [{"title": l.title, "detail": l.detail} for l in waiting],
                    "applied": [{"title": l.title} for l in used]}, True
        if name == "check_recipes":
            missing = items_without_recipe(self.db)
            self.step("Checked recipes", f"{_plural(len(missing), 'menu item')} without a recipe" if missing
                      else "Every menu item has a recipe")
            return {"items_without_recipe": missing}, True
        if name == "get_reorder_plan":
            self.step("Worked out what to order", f"{_plural(len(self.plan), 'ingredient')} from "
                      f"{_plural(len(self.by_supplier), 'supplier')}" if self.plan else "Nothing needs ordering")
            return [{"supplier": s, "lead_days": lines[0]["lead"], "lines": [
                {"ingredient": p["ingredient"].name, "qty": p["qty"], "unit": p["ingredient"].unit, "calculation": p["reason"],
                 "allowed_range": list(self.limits(p))} for p in lines]} for s, lines in self.by_supplier.items()], True
        if name == "adjust_quantity":
            return self._adjust(args["ingredient"], args["qty"], args["reason"])
        if name == "draft_order":
            return self._draft(args["supplier"], args["ingredients"], args["note"])
        if name == "finish":
            missing = [s for s in self.by_supplier if s not in self.staged]
            if missing:
                return f"Not finished: draft the orders for {', '.join(missing)} first.", False
            self.finished = args
            self.step("Wrote the briefing", args["headline"])
            return "Done.", True
        return f"There is no tool called {name}.", False

    def limits(self, p: dict) -> tuple[float, float]:
        """The range an agent may move a planned quantity to: half to 1.5x the code's quantity, never below the use
        expected until the delivery arrives."""
        step = 1 if p["ingredient"].unit == "pcs" else 100
        until_delivery = max(p["daily"] * p["lead"] - max(p["ingredient"].on_hand, 0), 0)
        low = math.ceil(max(p["code_qty"] * 0.5, until_delivery) / step) * step
        return low, math.floor(p["code_qty"] * 1.5 / step) * step

    def _adjust(self, ingredient: str, qty: float, reason: str):
        p = next((p for p in self.plan if p["ingredient"].name == ingredient), None)
        if not p:
            return f"{ingredient} is not in the reorder plan.", False
        if p["ingredient"].supplier.name in self.staged:
            return f"The order for {p['ingredient'].supplier.name} is already drafted; adjust before drafting.", False
        if not reason.strip():
            return "Give a reason for the change.", False
        step = 1 if p["ingredient"].unit == "pcs" else 100
        qty = math.ceil(qty / step) * step
        low, high = self.limits(p)
        unit = p["ingredient"].unit
        if not low <= qty <= high:
            return f"{qty:g} {unit} is outside the allowed range for {ingredient}: {low:g} to {high:g} {unit}.", False
        p["qty"], p["adjust_reason"] = qty, reason.strip()
        self.step(f"Changed {ingredient}", f"{p['code_qty']:g} → {qty:g} {unit}: {p['adjust_reason']}")
        return {"ingredient": ingredient, "qty": qty, "unit": unit, "code_qty": p["code_qty"]}, True

    def _draft(self, supplier: str, ingredients: list[str], note: str):
        lines = self.by_supplier.get(supplier)
        if not lines:
            return f"{supplier} has nothing in the reorder plan.", False
        if supplier in self.staged:
            return f"The order for {supplier} is already drafted.", False
        names = {p["ingredient"].name: p for p in lines}
        unknown = [n for n in ingredients if n not in names]
        if unknown:
            return f"Not in {supplier}'s plan: {', '.join(unknown)}. Use the names from get_reorder_plan.", False
        if set(ingredients) != set(names):
            return f"{supplier}'s order must have every planned ingredient: {', '.join(names)}.", False
        self.staged[supplier] = {"lines": lines, "note": note}
        self.step(f"Drafted the order for {supplier}",
                  ", ".join(f"{p['ingredient'].name} {p['qty']:g} {p['ingredient'].unit}" for p in lines))
        return {"drafted": [{"ingredient": p["ingredient"].name, "qty": p["qty"], "unit": p["ingredient"].unit} for p in lines]}, True

    def rules(self) -> None:
        """The same tools in a fixed order, with notes and warnings written by code."""
        for tool in ("check_stock", "check_open_orders", "check_what_i_learned", "check_recipes", "get_reorder_plan"):
            self.call(tool, {})
        for supplier, lines in self.by_supplier.items():
            self._draft(supplier, [p["ingredient"].name for p in lines], " ".join(f"{p['ingredient'].name}: {p['reason']}" for p in lines))
        headline = (f"{_plural(len(self.staged), 'supplier order')} drafted for {_plural(len(self.plan), 'ingredient')}. "
                    "Waiting for your approval." if self.plan else "No ingredient is low. No orders needed today.")
        if self.waiting:
            headline += f" {_plural(len(self.waiting), 'thing')} I learned from past orders {'is' if len(self.waiting) == 1 else 'are'} waiting for you on Stock."
        self.call("finish", {"headline": headline, "warnings": self.computed_warnings()})


def run(db: Session, llm: LLM) -> dict:
    check, source = _Check(db), "rules"
    if llm.enabled and llm.run_tools(SYSTEM, TASK, TOOLS, check.call, lambda: check.finished is not None):
        source = "ai"
        # every warning code found stays in the briefing, even if Claude worded it differently or left it out
        said = " ".join(check.finished["warnings"]).lower()
        check.finished["warnings"] += [w for w in check.computed_warnings() if w.split(" ")[0].lower() not in said]
    else:
        if llm.enabled:
            check.trace.append({"label": "Claude didn't finish, so the rules ran the check", "detail": "", "ok": False})
            trace = check.trace
            check = _Check(db)
            check.trace = trace
        check.rules()
    orders = []
    for supplier, staged in check.staged.items():
        po = PurchaseOrder(supplier=staged["lines"][0]["ingredient"].supplier, status="draft", note=staged["note"])
        po.lines = [PurchaseOrderLine(ingredient=p["ingredient"], qty=p["qty"], drafted_qty=p["qty"], reason=p["reason"] + (
            f"{CHANGE_MARK}{p['code_qty']:g} to {p['qty']:g} {p['ingredient'].unit}: {p['adjust_reason']}"
            if p["qty"] != p["code_qty"] else "")) for p in staged["lines"]]
        db.add(po)
        orders.append(po)
    db.flush()
    summary = {"headline": check.finished["headline"], "warnings": check.finished["warnings"],
               "order_ids": [po.id for po in orders], "steps": check.trace}
    db.add(AgentRun(agent="stock", source=source, summary=json.dumps(summary)))
    db.commit()
    return summary | {"source": source}
