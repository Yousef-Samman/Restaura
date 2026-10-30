def test_expenses_summary_and_profit(client):
    e = client.get("/api/expenses?days=30").json()
    assert e["sales"] > 0 and e["food_cost"] > 0
    assert abs(e["profit"] - (e["sales"] - e["costs"])) < 0.05
    assert {c["category"] for c in e["by_category"]} >= {"Ingredients (used)", "Rent", "Salaries"}
    # monthly costs are spread over the period
    rent = next(c["amount"] for c in e["by_category"] if c["category"] == "Rent")
    rent7 = next(c["amount"] for c in client.get("/api/expenses?days=7").json()["by_category"] if c["category"] == "Rent")
    assert abs(rent7 - rent * 7 / 30) < 0.05


def test_add_and_remove_expense(client):
    before = client.get("/api/expenses?days=7").json()["costs"]
    r = client.post("/api/expenses", json={"kind": "one_off", "category": "Maintenance", "amount": 250, "note": "Fridge"})
    assert r.status_code == 200
    assert abs(client.get("/api/expenses?days=7").json()["costs"] - before - 250) < 0.05
    assert client.delete(f"/api/expenses/{r.json()['id']}").status_code == 200
    assert client.post("/api/expenses", json={"kind": "purchase", "category": "X", "amount": 5}).status_code == 422


def test_delivery_is_recorded_as_purchase(client):
    ing = client.get("/api/stock").json()[0]
    client.post("/api/deliveries", json={"lines": [{"ingredient_id": ing["id"], "qty": 1000}], "invoice_ref": "INV-1"})
    e = client.get("/api/expenses?days=7").json()
    assert any(x["kind"] == "purchase" and x["note"] == "INV-1" for x in e["entries"])
    assert e["purchases_paid"] > 0


def test_cashier_cannot_see_expenses(ipad):
    assert ipad.get("/api/expenses").status_code == 403
