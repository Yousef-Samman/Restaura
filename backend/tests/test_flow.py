"""End-to-end checks of the two agents on sample data, without an AI key (rule-based path)."""


def item_id(client, name):
    return next(i["id"] for i in client.get("/api/menu").json() if i["name"] == name)


def ingredient(client, name):
    return next(i for i in client.get("/api/stock").json() if i["name"] == name)


def test_status_reports_ai_off(client):
    body = client.get("/api/status").json()
    assert body["ai_enabled"] is False and body["email"] == "log only"


def test_sale_consumes_ingredients_by_recipe(client):
    before = ingredient(client, "Hazelnut spread")["on_hand"]
    r = client.post("/api/orders", json={"lines": [{"item_id": item_id(client, "Hazelnut crepe"), "qty": 2}]})
    assert r.status_code == 200 and r.json()["total"] == 76
    assert ingredient(client, "Hazelnut spread")["on_hand"] == before - 120


def test_cashier_suggests_available_items_not_in_cart(client):
    crepe = item_id(client, "Hazelnut crepe")
    body = client.post("/api/cashier/suggest", json={"lines": [{"item_id": crepe}]}).json()
    assert body["source"] == "rules"
    assert 1 <= len(body["suggestions"]) <= 2
    names = {s["name"] for s in body["suggestions"]}
    assert "Hazelnut crepe" not in names
    assert all(s["pitch"] for s in body["suggestions"])


def test_accepted_suggestion_is_tracked(client):
    crepe = item_id(client, "Hazelnut crepe")
    s = client.post("/api/cashier/suggest", json={"lines": [{"item_id": crepe}]}).json()["suggestions"][0]
    client.post("/api/orders", json={"lines": [{"item_id": crepe},
                                               {"item_id": s["item_id"], "suggestion_event_id": s["event_id"]}]})
    ins = client.get("/api/insights/cashier").json()
    assert ins["accepted"] == 1 and ins["added_revenue"] == s["price"]


def test_out_of_stock_item_is_hidden_and_refused(client):
    pist = ingredient(client, "Pistachio cream")
    client.post("/api/stock/count", json=[{"ingredient_id": pist["id"], "counted": 10}])
    menu = {i["name"]: i for i in client.get("/api/menu").json()}
    assert menu["Pistachio kunafa crepe"]["available"] is False
    assert menu["Hazelnut crepe"]["available"] is True
    r = client.post("/api/orders", json={"lines": [{"item_id": menu["Pistachio kunafa crepe"]["id"]}]})
    assert r.status_code == 409
    sugg = client.post("/api/cashier/suggest", json={"lines": [{"item_id": menu["Hazelnut crepe"]["id"]}]}).json()
    assert "Pistachio drizzle" not in {s["name"] for s in sugg["suggestions"]}


def test_full_stock_to_order_loop(client):
    # sell enough pistachio crepes to push pistachio cream under its minimum
    crepe = item_id(client, "Pistachio kunafa crepe")
    client.post("/api/orders", json={"lines": [{"item_id": crepe, "qty": 4}]})
    assert ingredient(client, "Pistachio cream")["status"] == "low"

    run = client.post("/api/agents/stock/run").json()
    assert run["source"] == "rules" and run["order_ids"]
    pos = client.get("/api/purchase-orders").json()
    pantry = next(p for p in pos if p["supplier"] == "Pantry Wholesale")
    line = next(l for l in pantry["lines"] if l["ingredient"] == "Pistachio cream")
    assert line["qty"] >= 3000 - 720  # back to par at least
    assert pantry["status"] == "draft" and pantry["note"]

    # running again does not duplicate open orders
    assert client.post("/api/agents/stock/run").json()["order_ids"] == []

    sent = client.post(f"/api/purchase-orders/{pantry['id']}/approve").json()
    assert sent["status"] == "sent" and sent["email"]["status"] == "logged"
    mail = client.get("/api/outbox").json()[0]
    assert mail["to"] == "orders@pantry-wholesale.example" and "Pistachio cream" in mail["body"]

    before = ingredient(client, "Pistachio cream")["on_hand"]
    client.post(f"/api/purchase-orders/{pantry['id']}/receive",
                json={"lines": [{"ingredient_id": line["ingredient_id"], "qty": line["qty"]}], "invoice_ref": "INV-1"})
    assert ingredient(client, "Pistachio cream")["on_hand"] == before + line["qty"]
    assert ingredient(client, "Pistachio cream")["status"] == "ok"


def test_manager_can_edit_quantities_before_approving(client):
    client.post("/api/orders", json={"lines": [{"item_id": item_id(client, "Pistachio kunafa crepe"), "qty": 4}]})
    po_id = client.post("/api/agents/stock/run").json()["order_ids"][0]
    po = next(p for p in client.get("/api/purchase-orders").json() if p["id"] == po_id)
    first = po["lines"][0]
    sent = client.post(f"/api/purchase-orders/{po_id}/approve", json=[{"line_id": first["id"], "qty": 500}]).json()
    assert next(l for l in sent["lines"] if l["id"] == first["id"])["qty"] == 500


def test_ingredient_running_out_before_delivery_is_urgent(client):
    milk = ingredient(client, "Milk")
    client.post("/api/stock/count", json=[{"ingredient_id": milk["id"], "counted": 0}])
    run = client.post("/api/agents/stock/run").json()
    assert any("Milk" in w and "run out" in w for w in run["warnings"])


def test_pos_import_can_go_negative_and_is_flagged(client):
    csv = "item,qty\nPistachio kunafa crepe,40\nLatte,10\n"
    r = client.post("/api/sales/import", files={"file": ("day.csv", csv, "text/csv")})
    assert r.status_code == 200 and r.json()["lines"] == 2
    assert ingredient(client, "Pistachio cream")["status"] == "negative"
    run = client.post("/api/agents/stock/run").json()
    assert any("Pistachio cream" in w and "not recorded" in w for w in run["warnings"])


def test_pos_import_rejects_unknown_items(client):
    r = client.post("/api/sales/import", files={"file": ("day.csv", "item,qty\nPizza,1\n", "text/csv")})
    assert r.status_code == 400


def test_invoice_reading_needs_key(client):
    r = client.post("/api/invoices/read", files={"file": ("inv.jpg", b"x", "image/jpeg")})
    assert r.status_code == 503


def test_sales_summary(client):
    client.post("/api/orders", json={"lines": [{"item_id": item_id(client, "Latte"), "qty": 2}]})
    s = client.get("/api/sales/summary?days=14").json()
    assert len(s["daily"]) == 14 and s["daily"][-1]["sales"] >= 42
    assert s["top_items"] and s["categories"]
    assert len(s["today_orders"]) == 1
