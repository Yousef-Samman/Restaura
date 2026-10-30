def test_overview_priorities_link_to_sections(client):
    o = client.get("/api/overview").json()
    assert o["priorities"]
    assert {p["go"] for p in o["priorities"]} <= {"deliveries", "orders", "stock", "forecast", "expenses", "routines", "staff", None}
    assert o["facts"]["forecast_tomorrow"] > 0


def test_overview_agent_rules_mode(client):
    client.post("/api/agents/stock/run")
    r = client.post("/api/agents/overview/run").json()
    assert r["source"] == "rules" and r["headline"]
    assert any(run["agent"] == "overview" for run in client.get("/api/agents/runs").json())
    o = client.get("/api/overview").json()
    has_drafts = any(po["status"] == "draft" for po in client.get("/api/purchase-orders").json())
    assert any(p["go"] == "orders" for p in o["priorities"]) == has_drafts
