"""Suppliers page: add, edit, move ingredients, and remove only when it is safe."""


def sups(client):
    return client.get("/api/suppliers").json()


def test_add_edit_and_remove_a_supplier(client):
    r = client.post("/api/suppliers", json={"name": "Gulf Coffee", "channel": "whatsapp", "phone": "+966 50 000 0001", "lead_days": 2})
    assert r.status_code == 200 and r.json()["phone"] == "966500000001"
    sid = r.json()["id"]
    assert client.post("/api/suppliers", json={"name": "gulf coffee", "channel": "whatsapp", "phone": "1"}).status_code == 409
    assert client.put(f"/api/suppliers/{sid}", json={"name": "Gulf Coffee", "channel": "email"}).status_code == 400  # email needed
    assert client.delete(f"/api/suppliers/{sid}").status_code == 200
    assert all(s["id"] != sid for s in sups(client)["suppliers"])


def test_ticking_an_ingredient_moves_it_and_a_supplier_with_ingredients_cannot_go(client):
    data = sups(client)
    dairy = next(s for s in data["suppliers"] if s["name"] == "Dairy Farms Co.")
    milk = next(i for i in dairy["ingredients"] if i["name"] == "Milk")
    assert client.delete(f"/api/suppliers/{dairy['id']}").status_code == 409
    new = client.post("/api/suppliers", json={"name": "Al Safi", "channel": "email", "email": "orders@alsafi.example",
                                              "ingredient_ids": [milk["id"]]}).json()
    assert [i["name"] for i in new["ingredients"]] == ["Milk"]
    dairy = next(s for s in sups(client)["suppliers"] if s["id"] == dairy["id"])
    assert "Milk" not in [i["name"] for i in dairy["ingredients"]]
    # un-ticking would leave Milk with no supplier
    r = client.put(f"/api/suppliers/{new['id']}", json={"name": "Al Safi", "channel": "email", "email": "orders@alsafi.example"})
    assert r.status_code == 400 and "Milk" in r.json()["detail"]
