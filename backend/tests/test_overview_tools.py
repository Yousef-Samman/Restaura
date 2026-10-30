"""The overview agent with a scripted Claude: it reads sections with its tools and hands low stock to the stock agent."""
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
        yield c


def _use(name, args=None, n=[0]):
    n[0] += 1
    return types.SimpleNamespace(type="tool_use", id=f"o{n[0]}", name=name, input=args or {})


def test_overview_delegates_to_the_stock_agent_once(ai_client, monkeypatch):
    seen = []

    def create(self, **kw):
        tools = {t["name"] for t in kw["tools"]}
        if "get_ranked_priorities" not in tools:  # the stock agent's own loop: let it fail so its rules run
            raise anthropic.APIConnectionError(request=None)
        last = kw["messages"][-1]["content"]
        seen.append(last if isinstance(last, list) else [])
        turn = len(seen) - 1
        if turn == 0:
            return types.SimpleNamespace(stop_reason="tool_use", content=[_use("check_stock"), _use("run_stock_check")])
        if turn == 1:
            return types.SimpleNamespace(stop_reason="tool_use", content=[_use("run_stock_check"), _use("check_orders")])
        return types.SimpleNamespace(stop_reason="tool_use", content=[_use("finish", {"headline": "Approve the drafts.", "points": []})])
    monkeypatch.setattr(anthropic.resources.beta.messages.Messages, "create", create)

    assert not any(po["status"] == "draft" for po in ai_client.get("/api/purchase-orders").json())
    r = ai_client.post("/api/agents/overview/run").json()
    assert r["source"] == "ai" and r["headline"] == "Approve the drafts."
    assert r["order_ids"] and all(po["status"] == "draft" for po in ai_client.get("/api/purchase-orders").json())
    second, orders = seen[2][0], json.loads(seen[2][1]["content"])
    assert second["is_error"] and "already ran" in second["content"]
    assert len(orders["drafts_waiting"]) == len(r["order_ids"])
    assert [s["label"] for s in r["steps"]][:2] == ["Checked stock", "Asked the stock agent to check stock"]
