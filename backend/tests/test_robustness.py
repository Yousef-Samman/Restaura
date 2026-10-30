"""Robustness: bad input files, gaps in the data, and Claude being down or answering badly.
In every case the app must keep working, explain the problem, and never change stock halfway."""
import types

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents import stock_agent
from app.config import Settings
from app.main import create_app
from app.models import MenuItem
from app.seed import seed
from evals.common import fresh_db, no_llm


def stock_of(client):
    return {i["name"]: i["on_hand"] for i in client.get("/api/stock").json()}


def upload(client, text: str | bytes):
    data = text.encode() if isinstance(text, str) else text
    return client.post("/api/sales/import", files={"file": ("sales.csv", data, "text/csv")})


# ---- POS sales report ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("csv, says", [
    ("item,qty\nHazelnut crepe,two\n", "not a number"),
    ("item,qty\nHazelnut crepe,-3\n", "whole number"),
    ("item,qty\nHazelnut crepe,1.5\n", "whole number"),
    ("item,qty\nHazelnut crepe,999999\n", "whole number"),
    ("name,amount\nHazelnut crepe,2\n", "columns named item and qty"),
    ("", "columns named item and qty"),
    ("item,qty\n", "no sales lines"),
    ("item,qty\nHazelnut crepe,2\nUnicorn cake,1\n", "Unicorn cake"),
    (b"item,qty\n\xff\xfeHazelnut crepe,2\n", "UTF-8"),
])
def test_bad_sales_report_is_refused_and_stock_unchanged(client, csv, says):
    before = stock_of(client)
    r = upload(client, csv)
    assert r.status_code == 400 and says in r.json()["detail"]
    assert stock_of(client) == before


def test_messy_but_valid_report_is_read(client):
    """A BOM, header and name case, spaces, blank lines, zero lines and a repeated item are all normal in exports."""
    before = stock_of(client)
    csv = "﻿Item , QTY\n hazelnut CREPE ,2\n\nLatte,0\nHazelnut crepe,1\n"
    r = upload(client, csv)
    assert r.status_code == 200 and r.json()["lines"] == 1 and r.json()["total"] == 3 * 38
    assert stock_of(client)["Hazelnut spread"] == before["Hazelnut spread"] - 3 * 60


def test_selling_more_than_stock_goes_negative_and_is_flagged(client):
    """Imported sales already happened, so stock may go below zero. The agent must say a delivery is probably
    missing and order back to par from zero, not from the negative number."""
    upload(client, "item,qty\nPistachio kunafa crepe,30\n")
    pist = next(i for i in client.get("/api/stock").json() if i["name"] == "Pistachio cream")
    assert pist["on_hand"] < 0 and pist["status"] == "negative"
    run = client.post("/api/agents/stock/run").json()
    assert any("Pistachio cream" in w and "below zero" in w for w in run["warnings"])
    line = next(l for po in client.get("/api/purchase-orders").json() for l in po["lines"] if l["ingredient"] == "Pistachio cream")
    assert line["qty"] >= pist["par_level"]


# ---- gaps in the data ---------------------------------------------------------------------------------------------
def test_menu_item_without_recipe_is_warned_about():
    with fresh_db() as db:
        seed(db, history_days=0)
        db.add(MenuItem(name="Chef's special", category="Crepes", price=55))
        db.commit()
        run = stock_agent.run(db, no_llm())
    assert any("Chef's special" in w and "no recipe" in w for w in run["warnings"])


def test_new_store_with_no_data_works(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/empty.db", anthropic_api_key=None, seed_demo_data=False,
                              manager_password="m", cashier_password="c"))
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "manager", "password": "m"}).status_code == 200
        for path in ("/api/today", "/api/stock", "/api/forecast", "/api/expenses", "/api/sales/summary", "/api/overview",
                     "/api/purchase-orders", "/api/insights/cashier", "/api/staff/today", "/api/routines"):
            assert c.get(path).status_code == 200, path
        assert c.post("/api/agents/stock/run").json()["order_ids"] == []
        assert c.post("/api/agents/overview/run").status_code == 200


def test_nothing_in_stock_means_no_suggestions(client):
    for i in client.get("/api/stock").json():
        client.post("/api/stock/count", json=[{"ingredient_id": i["id"], "counted": 0}])
    menu = client.get("/api/menu").json()
    assert not any(i["available"] for i in menu)
    r = client.post("/api/cashier/suggest", json={"lines": [{"item_id": menu[0]["id"]}]})
    assert r.status_code == 200 and r.json()["suggestions"] == []


# ---- Claude down or misbehaving -------------------------------------------------------------------------------------
@pytest.fixture
def ai_client(tmp_path):
    """The app with a (fake) key, so every agent tries Claude first."""
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/ai.db", anthropic_api_key="test-key", smtp_host=None,
                              demo_supplier_email=None, manager_password="m", cashier_password="c"))
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "manager", "password": "m"}).status_code == 200
        yield c


def _claude_answers(monkeypatch, fn):
    monkeypatch.setattr(anthropic.resources.beta.messages.Messages, "create", lambda self, **kw: fn(**kw))


def _down(**kw):
    raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def _overloaded(**kw):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    raise anthropic.InternalServerError("overloaded", response=httpx.Response(529, request=req), body=None)


def _text(text):
    return lambda **kw: types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])


@pytest.mark.parametrize("claude", [_down, _overloaded, _text("Sorry, I can't help with that."), _text("[1, 2, 3]"),
                                    _text('{"suggestions": [{"item_id": 99999, "pitch": "Buy this", "reason": "x"}]}')],
                         ids=["unreachable", "overloaded", "not JSON", "wrong JSON shape", "items not on the menu"])
def test_agents_fall_back_to_rules(ai_client, monkeypatch, claude):
    _claude_answers(monkeypatch, claude)
    assert ai_client.get("/api/status").json()["ai_enabled"] is True
    crepe = next(i["id"] for i in ai_client.get("/api/menu").json() if i["name"] == "Hazelnut crepe")
    s = ai_client.post("/api/cashier/suggest", json={"lines": [{"item_id": crepe}]}).json()
    assert s["source"] == "rules" and s["suggestions"]
    upload(ai_client, "item,qty\nPistachio kunafa crepe,15\n")
    run = ai_client.post("/api/agents/stock/run").json()
    assert run["source"] == "rules" and run["order_ids"]
    assert ai_client.post("/api/agents/overview/run").json()["source"] == "rules"


def test_invoice_photo_when_claude_is_down_points_to_manual_entry(ai_client, monkeypatch):
    _claude_answers(monkeypatch, _down)
    r = ai_client.post("/api/invoices/read", files={"file": ("inv.png", b"\x89PNG fake", "image/png")})
    assert r.status_code == 502 and "manually" in r.json()["detail"]


def test_claude_calls_have_a_short_timeout():
    from app.agents.llm import LLM
    llm = LLM(Settings(anthropic_api_key="test-key", llm_timeout=12))
    assert llm.client.timeout == 12 and llm.client.max_retries == 1
