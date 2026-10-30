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


def test_low_ingredient_with_order_on_the_way_no_longer_needs_the_manager(client):
    def needing():
        o = client.get("/api/overview").json()["facts"]
        return {x["name"] for x in o["low_stock"]}, set(o["low_stock_order_on_the_way"])

    low_before, _ = needing()
    badge_before = client.get("/api/today").json()["low_stock"]
    assert low_before and badge_before
    client.post("/api/agents/stock/run")
    for po in client.get("/api/purchase-orders").json():
        if po["status"] == "draft":
            client.post(f"/api/purchase-orders/{po['id']}/approve")
    low_after, on_the_way = needing()
    assert low_before - low_after <= on_the_way and not (low_after & on_the_way)
    assert all(r["on_order"] for r in client.get("/api/stock").json() if r["name"] in on_the_way)
    assert client.get("/api/today").json()["low_stock"] < badge_before
