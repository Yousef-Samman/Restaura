"""The stock agent as a tool-using agent, with a scripted Claude: it calls the tools, may change a quantity within
limits with a reason, and the rules take over when it never finishes."""
import json
import types

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def ai_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/ai.db", anthropic_api_key="test-key", smtp_host=None,
                              demo_supplier_email=None, manager_password="m", cashier_password="c"))
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "manager", "password": "m"}).status_code == 200
        c.post("/api/sales/import", files={"file": ("s.csv", b"item,qty\nPistachio kunafa crepe,15\n", "text/csv")})
        yield c


def _use(name, args, n=[0]):
    n[0] += 1
    return types.SimpleNamespace(type="tool_use", id=f"t{n[0]}", name=name, input=args)


def _reply(*uses):
    return types.SimpleNamespace(stop_reason="tool_use", content=list(uses))


def _results(kw) -> list[tuple[dict, bool]]:
    last = kw["messages"][-1]["content"]
    return [(json.loads(r["content"]), not r["is_error"]) for r in last] if isinstance(last, list) else []


def _scripted(monkeypatch, script):
    state = {"turn": 0, "seen": []}

    def create(self, **kw):
        state["seen"].append(_results(kw))
        reply = script(state["turn"], state["seen"])
        state["turn"] += 1
        return reply
    monkeypatch.setattr(anthropic.resources.beta.messages.Messages, "create", create)
    return state


def test_agent_adjusts_within_limits_and_explains(ai_client, monkeypatch):
    plan = {}

    def script(turn, seen):
        if turn == 0:
            return _reply(_use("check_stock", {}), _use("check_sales_forecast", {}), _use("get_reorder_plan", {}))
        if turn == 1:
            plan["orders"] = seen[-1][2][0]
            first = plan["orders"][0]["lines"][0]
            plan["first"] = first
            low, high = first["allowed_range"]
            return _reply(_use("adjust_quantity", {"ingredient": first["ingredient"], "qty": high * 3, "reason": "busy week"}),
                          _use("adjust_quantity", {"ingredient": first["ingredient"], "qty": high, "reason": "Forecast shows a busy weekend."}))
        if turn == 2:
            plan["too_much"], plan["ok"] = seen[-1]
            return _reply(*[_use("draft_order", {"supplier": o["supplier"], "ingredients": [l["ingredient"] for l in o["lines"]],
                                                 "note": "Needed for the week."}) for o in plan["orders"]])
        return _reply(_use("finish", {"headline": "Orders drafted.", "warnings": []}))

    _scripted(monkeypatch, script)
    run = ai_client.post("/api/agents/stock/run").json()
    assert run["source"] == "ai"
    assert plan["too_much"][1] is False and "outside the allowed range" in plan["too_much"][0]
    assert plan["ok"][1] is True
    first = plan["first"]
    line = next(l for po in ai_client.get("/api/purchase-orders").json() for l in po["lines"] if l["ingredient"] == first["ingredient"])
    assert line["qty"] == first["allowed_range"][1] and line["qty"] != first["qty"]
    assert "The agent changed" not in line["reason"]
    assert line["change"]["from"] == first["qty"] and line["change"]["to"] == line["qty"] and "busy weekend" in line["change"]["reason"]
    po = next(po for po in ai_client.get("/api/purchase-orders").json() if any(l["change"] for l in po["lines"]))
    assert po["changed"] and ai_client.get("/api/today").json()["changed_drafts"] == 1
    labels = [s["label"] for s in run["steps"]]
    assert labels[0] == "Checked stock levels" and f"Changed {first['ingredient']}" in labels and labels[-1] == "Wrote the briefing"
    assert ai_client.get("/api/agents/runs").json()[0]["steps"] == run["steps"]


def test_finish_is_refused_until_every_order_is_drafted_and_rules_take_over(ai_client, monkeypatch):
    state = _scripted(monkeypatch, lambda turn, seen: _reply(_use("finish", {"headline": "All good.", "warnings": []})))
    run = ai_client.post("/api/agents/stock/run").json()
    assert all(ok is False for r in state["seen"][1:] for _, ok in r)
    assert run["source"] == "rules" and run["order_ids"]
    assert any("rules ran the check" in s["label"] for s in run["steps"])


def test_wrong_tool_input_is_refused_not_crashed(ai_client, monkeypatch):
    calls = []

    def script(turn, seen):
        calls.append(seen[-1])
        return _reply(_use("draft_order", {"supplier": 42})) if turn == 0 else types.SimpleNamespace(stop_reason="end_turn", content=[])
    _scripted(monkeypatch, script)
    run = ai_client.post("/api/agents/stock/run").json()
    assert calls[1][0][1] is False
    assert run["source"] == "rules" and run["order_ids"]
