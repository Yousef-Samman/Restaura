"""Staff agent: once a week it looks at how each person worked and gives each one tip for their next shifts.

Everyone is judged on what fits their job. People who take orders on the iPad are measured on how they sell and
close bills (offers customers accept, bill size, time to pay, items taken off). Everyone, crepe makers included, is
measured on the manager's weekly review and on facts the app already has (on time, hours, checklist tasks). Code
measures; the agent decides what each person should work on and words the tip. The next week, code checks whether
the number the tip targeted moved. Without Claude, the same tools run in a fixed order (the rules)."""
import datetime as dt
import json
import re
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (AgentRun, Attendance, MenuItem, Order, OrderLine, RoutineCheck, Shift, StaffMember, StaffReview,
                      StaffTip, SuggestionEvent)
from ..routines import local_now
from .llm import LLM

LATE_AFTER = dt.timedelta(minutes=10)
MIN_ORDERS = 10  # fewer orders than this in a week and the sales numbers say too little to coach on
MIN_OFFERS = 5
REVIEW = ("quality", "speed", "cleanliness", "teamwork")

# what a tip can target; each has a measure code can read for any week, and whether higher is better
FOCUS = {
    "offers": ("share of suggested add-ons the customer said yes to", True),
    "time_to_pay": ("average seconds from first item to paid", False),
    "removed": ("share of items taken off the bill before paying", False),
    "on_time": ("share of shifts started on time", True),
    "checklists": ("checklist tasks ticked", True),
    **{f"review_{k}": (f"manager's {k} rating (1-5)", True) for k in REVIEW},
}


def week_start(day: dt.date) -> dt.date:
    """Saudi work week: Sunday to Saturday."""
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


def percent_words(text: str) -> str:
    """Claude sometimes quotes a share as the tool gives it (0.118); the manager reads percentages (12%)."""
    return re.sub(r"(?<![\d./])0\.\d{1,3}(?![\d/])", lambda m: f"{round(float(m.group()) * 100)}%", text)


def _pct(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


class Week:
    """Every measure for one person over one 7-day window [start, end)."""

    def __init__(self, db: Session, member: StaffMember, start: dt.date, end: dt.date):
        self.db, self.m, self.start, self.end = db, member, start, end

    def sales(self) -> dict:
        db, m = self.db, self.m
        orders = db.scalars(select(Order).where(Order.staff_id == m.id, Order.business_date >= self.start,
                                                Order.business_date < self.end)).all()
        n = len(orders)
        items = sum(l.qty for o in orders for l in o.lines)
        timed = [o.seconds_to_pay for o in orders if o.seconds_to_pay]
        events = db.execute(select(SuggestionEvent.menu_item_id, SuggestionEvent.accepted).join(Order, SuggestionEvent.order_id == Order.id, isouter=True)
                            .where(SuggestionEvent.staff_id == m.id,
                                   SuggestionEvent.created_at >= dt.datetime.combine(self.start, dt.time()) - dt.timedelta(hours=3),
                                   SuggestionEvent.created_at < dt.datetime.combine(self.end, dt.time()) - dt.timedelta(hours=3))).all()
        shown, yes = Counter(), Counter()
        for item_id, accepted in events:
            shown[item_id] += 1
            yes[item_id] += bool(accepted)
        names = dict(db.execute(select(MenuItem.id, MenuItem.name).where(MenuItem.id.in_(list(shown) or [0]))).all())
        return {
            "orders": n,
            "takes_orders": n >= MIN_ORDERS,
            "avg_bill": round(sum(o.total for o in orders) / n, 1) if n else None,
            "offers_shown": sum(shown.values()), "offers_accepted": sum(yes.values()),
            "offers": _pct(sum(yes.values()), sum(shown.values())),
            "time_to_pay": round(sum(timed) / len(timed)) if timed else None,
            "removed": _pct(sum(o.removed_items for o in orders), items + sum(o.removed_items for o in orders)),
            "by_offer": sorted(({"item": names.get(i, "?"), "shown": shown[i], "accepted": yes[i], "rate": _pct(yes[i], shown[i])}
                                for i in shown if shown[i] >= MIN_OFFERS), key=lambda x: -x["rate"]),
            "card_share": _pct(sum(o.payment in ("card", "split") for o in orders), sum(o.payment is not None for o in orders)),
        }

    def facts(self) -> dict:
        db, m = self.db, self.m
        shifts = {s.date: s for s in db.scalars(select(Shift).where(Shift.staff_id == m.id, Shift.date >= self.start, Shift.date < self.end))}
        att = db.scalars(select(Attendance).where(Attendance.staff_id == m.id, Attendance.date >= self.start, Attendance.date < self.end)).all()
        on_time, late_min, hours = 0, 0, 0.0
        for a in att:
            s = shifts.get(a.date)
            if s:
                late = (a.clock_in - dt.datetime.combine(a.date, s.start)).total_seconds() / 60
                on_time += late <= LATE_AFTER.total_seconds() / 60
                late_min += max(0, round(late)) if late > LATE_AFTER.total_seconds() / 60 else 0
            if a.clock_out:
                hours += (a.clock_out - a.clock_in).total_seconds() / 3600
        ticks = db.scalar(select(func.count(RoutineCheck.id)).where(RoutineCheck.done_by == m.name, RoutineCheck.date >= self.start,
                                                                   RoutineCheck.date < self.end)) or 0
        return {"shifts": len(shifts), "came_in": len(att), "on_time_shifts": on_time,
                "on_time": _pct(on_time, len(shifts)), "late_minutes": late_min, "hours": round(hours, 1), "checklists": ticks}

    def review(self) -> dict | None:
        # the latest review done in a work week that overlaps this window
        r = self.db.scalar(select(StaffReview).where(StaffReview.staff_id == self.m.id,
                                                     StaffReview.week_start > self.start - dt.timedelta(days=7),
                                                     StaffReview.week_start < self.end).order_by(StaffReview.week_start.desc(), StaffReview.id.desc()))
        if not r:
            return None
        return {k: getattr(r, k) for k in REVIEW} | {"note": r.note, "average": round(sum(getattr(r, k) for k in REVIEW) / 4, 1)}

    def measure(self, focus: str) -> float | None:
        if focus.startswith("review_"):
            r = self.review()
            return r[focus.removeprefix("review_")] if r else None
        if focus in ("on_time", "checklists"):
            return self.facts()[focus]
        return self.sales()[focus]


def _windows(today: dt.date) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]]:
    """The last 7 full days, and the 7 days before them."""
    return (today - dt.timedelta(days=7), today), (today - dt.timedelta(days=14), today - dt.timedelta(days=7))


def tip_result(db: Session, tip: StaffTip, today: dt.date | None = None) -> dict | None:
    """Did the tip move its number? Compares the baseline saved with the tip to the week since it was given."""
    today = today or local_now().date()
    given = (tip.created_at + dt.timedelta(hours=3)).date()
    if (today - given).days < 5 or tip.baseline is None:
        return None
    now = Week(db, tip.staff, given, min(today, given + dt.timedelta(days=7))).measure(tip.focus)
    if now is None:
        return None
    _, higher = FOCUS[tip.focus]
    change = now - tip.baseline
    # a small wobble is not a result: 2 points for shares, 3 seconds, a quarter star
    noise = 3 if tip.focus == "time_to_pay" else 0.25 if tip.focus.startswith("review_") else 1 if tip.focus == "checklists" else 0.02
    verdict = "worked" if (change > noise if higher else change < -noise) else "worse" if (change < -noise if higher else change > noise) else "no change"
    return {"focus": tip.focus, "before": tip.baseline, "after": now, "verdict": verdict}


SYSTEM = (
    "You are the staff agent of a dessert and coffee restaurant. Once a week you look at how each staff member "
    "worked and give each one tip for their next shifts. Judge people only on what fits their job: sales numbers "
    "(offers accepted, bill size, time to pay, items taken off) only for people who take orders, and for everyone the "
    "manager's review and the facts the app has (on time, hours, checklist tasks). A crepe maker never gets a sales tip. "
    "Start with check_team, then check_person for each person, then set_tip once per person, then finish. "
    "A tip is one concrete action for the next shift, under 22 words, addressed to the person by first name, kind and "
    "practical, never blaming. It may only use that person's own numbers, never anyone else's, because they see it on "
    "the iPad. Pick the focus the tip should move. Learn from each person's history: build on the kinds of tip that "
    "work for them, and don't repeat a focus that has not worked twice; try another angle instead. If last week's tip "
    "worked, say so in the why. The why is one "
    "sentence for the manager and quotes the numbers as the tools give them; never do your own arithmetic. Shares "
    "(offers accepted, items taken off, on time) are fractions in the tools: always write them as whole percents "
    "(0.118 is 12%), never as decimals. "
    "Finish with a one-sentence headline for the manager."
)
TASK = "It's the end of the week. Check how each person worked and set each one's tip for next week."

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}
TOOLS = [
    {"name": "check_team", "description": "Everyone on the team this week: role, whether they take orders, and team "
     "averages to compare with.", "input_schema": _NONE},
    {"name": "check_person", "description": "One person's week: sales (only if they take orders) with the offers "
     "customers accept and turn down, attendance and checklist facts, the manager's review if done, the same numbers "
     "for the week before, whether last week's tip worked, and their history: every past tip with its result, which "
     "kinds of tip work for them and their review averages over the weeks.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["name"], "properties": {"name": {"type": "string"}}}},
    {"name": "set_tip", "description": "Set one person's tip for next week. focus is the measure it should move.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["name", "tip", "why", "focus"],
                      "properties": {"name": {"type": "string"}, "tip": {"type": "string"}, "why": {"type": "string"},
                                     "focus": {"type": "string", "enum": list(FOCUS)}}}},
    {"name": "finish", "description": "End the check once every person has a tip.", "input_schema": {
        "type": "object", "additionalProperties": False, "required": ["headline"], "properties": {"headline": {"type": "string"}}}},
]


class _Check:
    def __init__(self, db: Session, today: dt.date | None = None):
        self.db = db
        self.today = today or local_now().date()
        (a, b), (c, d) = _windows(self.today)
        self.members = db.scalars(select(StaffMember).where(StaffMember.active).order_by(StaffMember.name)).all()
        self.now = {m.id: Week(db, m, a, b) for m in self.members}
        self.before = {m.id: Week(db, m, c, d) for m in self.members}
        self.sales = {m.id: self.now[m.id].sales() for m in self.members}
        self.tips: dict[int, dict] = {}
        self.finished: dict | None = None
        self.trace: list[dict] = []

    def step(self, label: str, detail: str, ok: bool = True) -> None:
        self.trace.append({"label": label, "detail": detail, "ok": ok})

    def by_name(self, name: str) -> StaffMember | None:
        return next((m for m in self.members if m.name.lower() == name.strip().lower()), None)

    def team_avg(self) -> dict:
        takers = [s for s in self.sales.values() if s["takes_orders"]]
        avg = lambda k: round(sum(s[k] for s in takers if s[k] is not None) / max(1, sum(s[k] is not None for s in takers)), 3) if takers else None
        return {k: avg(k) for k in ("offers", "avg_bill", "time_to_pay", "removed")}

    def last_tip(self, m: StaffMember) -> StaffTip | None:
        return self.db.scalar(select(StaffTip).where(StaffTip.staff_id == m.id).order_by(StaffTip.id.desc()))

    def person(self, m: StaffMember) -> dict:
        s, w, b = self.sales[m.id], self.now[m.id], self.before[m.id]
        out = {"name": m.name, "role": m.role, "takes_orders": s["takes_orders"], "facts": w.facts(), "review": w.review(),
               "week_before": {"facts": b.facts(), "review": b.review()}}
        if s["takes_orders"]:
            out["sales"] = s
            out["week_before"]["sales"] = {k: v for k, v in b.sales().items() if k != "by_offer"}
        tip = self.last_tip(m)
        if tip:
            out["last_tip"] = {"tip": tip.tip, "focus": tip.focus, "result": tip_result(self.db, tip, self.today)}
        out["history"] = self.history(m)
        return out

    def history(self, m: StaffMember) -> dict:
        """What the agent has learned about this person over the weeks: every past tip and whether it moved its
        number, which kinds of tip work for them, and how their weekly reviews have moved."""
        tips = self.db.scalars(select(StaffTip).where(StaffTip.staff_id == m.id).order_by(StaffTip.id.desc()).limit(8)).all()
        past = [{"week_of": (t.created_at + dt.timedelta(hours=3)).date().isoformat(), "focus": t.focus, "tip": t.tip,
                 "verdict": (r or {}).get("verdict", "too early")} for t in tips for r in [tip_result(self.db, t, self.today)]]
        by_focus: dict[str, Counter] = defaultdict(Counter)
        for t in past:
            by_focus[t["focus"]][t["verdict"]] += 1
        reviews = self.db.scalars(select(StaffReview).where(StaffReview.staff_id == m.id)
                                  .order_by(StaffReview.week_start.desc()).limit(6)).all()
        return {"past_tips": past,
                "works_for_them": sorted(f for f, c in by_focus.items() if c["worked"] and c["worked"] >= c["no change"] + c["worse"]),
                "did_not_work": sorted(f for f, c in by_focus.items() if c["no change"] + c["worse"] >= 2 and not c["worked"]),
                "review_averages_newest_first": [round(sum(getattr(r, k) for k in REVIEW) / 4, 2) for r in reviews]}

    def call(self, name: str, args: dict):
        if name == "check_team":
            team = [{"name": m.name, "role": m.role, "takes_orders": self.sales[m.id]["takes_orders"],
                     "orders_this_week": self.sales[m.id]["orders"]} for m in self.members]
            self.step("Looked at the team", f"{len(team)} people, {sum(t['takes_orders'] for t in team)} take orders")
            return {"team": team, "averages_for_people_who_take_orders": self.team_avg()}, True
        if name == "check_person":
            m = self.by_name(args["name"])
            if not m:
                return f"No staff member called {args['name']}.", False
            p = self.person(m)
            self.step(f"Checked {m.name}'s week", self._summary(p))
            return p, True
        if name == "set_tip":
            m = self.by_name(args["name"])
            if not m:
                return f"No staff member called {args['name']}.", False
            focus = args["focus"]
            if focus not in FOCUS:
                return f"Unknown focus {focus}.", False
            if focus in ("offers", "time_to_pay", "removed") and not self.sales[m.id]["takes_orders"]:
                return f"{m.name} doesn't take orders, so pick a focus from the review, attendance or checklists.", False
            if len(args["tip"].split()) > 30:
                return "Keep the tip under 22 words.", False
            others = [o.name for o in self.members if o is not m and o.name.lower() in args["tip"].lower()]
            if others:
                return f"The tip names {', '.join(others)}. It may only talk about {m.name}'s own work.", False
            self.tips[m.id] = {"member": m, "tip": percent_words(args["tip"].strip()), "why": percent_words(args["why"].strip()), "focus": focus,
                               "baseline": self.now[m.id].measure(focus)}
            self.step(f"Set {m.name}'s tip", self.tips[m.id]["tip"])
            return "Saved.", True
        if name == "finish":
            missing = [m.name for m in self.members if m.id not in self.tips]
            if missing:
                return f"Not finished: set a tip for {', '.join(missing)} first.", False
            self.finished = {**args, "headline": percent_words(args["headline"])}
            self.step("Wrote the summary", self.finished["headline"])
            return "Done.", True
        return f"There is no tool called {name}.", False

    def _summary(self, p: dict) -> str:
        bits = []
        if p.get("sales"):
            s = p["sales"]
            bits.append(f"{s['orders']} orders, offers accepted {round((s['offers'] or 0) * 100)}%, {s['time_to_pay'] or '–'} s to pay")
        f = p["facts"]
        bits.append(f"on time {f['on_time_shifts']} of {f['shifts']} shifts, {f['checklists']} checklist tasks")
        bits.append(f"review {p['review']['average']}/5" if p["review"] else "no review yet")
        return "; ".join(bits)

    # ---- rules: the same tools, with the weakest measure picked and the tip written by code -----------------------
    def rules(self) -> None:
        self.call("check_team", {})
        avg = self.team_avg()
        for m in self.members:
            self.call("check_person", {"name": m.name})
            p = self.person(m)
            self.call("set_tip", {"name": m.name, **self._rule_tip(m, p, avg)})
        worked = [m.name for m in self.members if (lt := self.person(m).get("last_tip")) and lt["result"] and lt["result"]["verdict"] == "worked"]
        reviews = sum(self.now[m.id].review() is not None for m in self.members)
        headline = (f"Tips set for {len(self.members)} people." + (f" Last week's tip worked for {', '.join(worked)}." if worked else "")
                    + ("" if reviews == len(self.members) else f" {len(self.members) - reviews} weekly reviews still to do."))
        self.call("finish", {"headline": headline})

    def _rule_tip(self, m: StaffMember, p: dict, avg: dict) -> dict:
        first = m.name.split()[0]
        s = p.get("sales")
        if s:
            gaps = []
            if s["offers"] is not None and avg["offers"]:
                gaps.append((avg["offers"] - s["offers"], "offers"))
            if s["time_to_pay"] and avg["time_to_pay"]:
                gaps.append(((s["time_to_pay"] - avg["time_to_pay"]) / avg["time_to_pay"], "time_to_pay"))
            if s["removed"] is not None and avg["removed"]:
                gaps.append((s["removed"] - avg["removed"], "removed"))
            failed = set(p["history"]["did_not_work"])
            gap, focus = max((g for g in gaps if g[1] not in failed), default=(0, "offers"))
            if gap < 0.03:  # at or above the team on everything: build on what already works
                focus = "offers"
            if focus == "offers":
                best = s["by_offer"][0] if s["by_offer"] else None
                tip = (f"{first}, offer the {best['item'].lower()} with every order this week; customers say yes to it most often with you."
                       if best else f"{first}, read out one add-on with every order before you take payment.")
                why = (f"{first}'s offers were accepted {round(s['offers'] * 100)}% of the time (team {round(avg['offers'] * 100)}%)"
                       + (f"; {best['item']} lands best at {round(best['rate'] * 100)}%." if best else "."))
            elif focus == "time_to_pay":
                tip = f"{first}, ask 'card or cash?' while the order is still on screen, to close bills faster at the rush."
                why = f"{first} takes {s['time_to_pay']} s from first item to paid (team {round(avg['time_to_pay'])} s)."
            else:
                tip = f"{first}, read the order back to the customer before payment, so nothing has to come off the bill."
                why = f"{round(s['removed'] * 100)}% of {first}'s items were taken off before paying (team {round(avg['removed'] * 100)}%)."
            return {"tip": tip, "why": why, "focus": focus}
        f, r = p["facts"], p["review"]
        if f["shifts"] and f["on_time"] is not None and f["on_time"] < 0.85:
            return {"tip": f"{first}, aim to clock in five minutes before each shift this week.",
                    "why": f"{first} started on time on {f['on_time_shifts']} of {f['shifts']} shifts.", "focus": "on_time"}
        if r:
            k = min(REVIEW, key=lambda k: r[k])
            words = {"quality": "check each plate against the recipe photo before it goes out",
                     "speed": "prep toppings before the evening rush so orders flow at peak time",
                     "cleanliness": "wipe down your station after every rush, not only at closing",
                     "teamwork": "jump in to help the till when a queue builds"}
            return {"tip": f"{first}, {words[k]}.", "why": f"Your weekly review gave {first} {r[k]}/5 for {k}"
                    + (f" (note: {r['note']})." if r.get("note") else "."), "focus": f"review_{k}"}
        return {"tip": f"{first}, keep ticking the checklist tasks you finish, so the team can see what's done.",
                "why": f"{first} ticked {f['checklists']} checklist tasks this week; no review yet.", "focus": "checklists"}


def run(db: Session, llm: LLM, today: dt.date | None = None) -> dict:
    check, source = _Check(db, today), "rules"
    if llm.enabled and llm.run_tools(SYSTEM, TASK, TOOLS, check.call, lambda: check.finished is not None, max_turns=16):
        source = "ai"
    else:
        if llm.enabled:
            trace = check.trace + [{"label": "Claude didn't finish, so the rules ran the check", "detail": "", "ok": False}]
            check = _Check(db, today)
            check.trace = trace
        check.rules()
    for t in check.tips.values():
        db.add(StaffTip(staff_id=t["member"].id, tip=t["tip"], why=t["why"], focus=t["focus"], baseline=t["baseline"], source=source))
    summary = {"headline": check.finished["headline"], "steps": check.trace,
               "tips": [{"name": t["member"].name, "tip": t["tip"], "why": t["why"], "focus": t["focus"]} for t in check.tips.values()]}
    db.add(AgentRun(agent="staff", source=source, summary=json.dumps(summary)))
    db.commit()
    return summary | {"source": source}


def overview(db: Session, today: dt.date | None = None) -> dict:
    """What the Staff tab shows: each person this week, their review status, current tip and whether the last one worked."""
    check = _Check(db, today)
    avg = check.team_avg()
    people = []
    for m in check.members:
        p = check.person(m)
        tips = db.scalars(select(StaffTip).where(StaffTip.staff_id == m.id).order_by(StaffTip.id.desc()).limit(2)).all()
        current = tips[0] if tips else None
        prev = tips[1] if len(tips) > 1 else None
        b = check.before[m.id].sales() if p["takes_orders"] else None
        people.append(p | {
            "id": m.id,
            "trend": round((p["sales"]["offers"] - b["offers"]) * 100) if b and p["sales"]["offers"] is not None and b["offers"] is not None else None,
            "tip": {"tip": current.tip, "why": current.why, "focus": current.focus, "at": current.created_at.isoformat()} if current else None,
            "previous_tip": ({"tip": prev.tip, "focus": prev.focus, "label": FOCUS[prev.focus][0], "result": tip_result(db, prev, check.today)}
                             if prev else None),
            "review_done": db.scalar(select(StaffReview.id).where(StaffReview.staff_id == m.id,
                                                                  StaffReview.week_start == week_start(check.today))) is not None,
        })
    return {"week_start": week_start(check.today).isoformat(), "averages": avg, "people": people,
            "reviews_done": sum(p["review_done"] for p in people)}
