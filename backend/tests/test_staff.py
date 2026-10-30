def test_clock_in_and_out_with_pin(ipad, client):
    client.post("/api/staff", json={"name": "Rami", "role": "Cashier", "pin": "7777"})
    assert ipad.post("/api/staff/clock", json={"pin": "9999"}).status_code == 404
    r = ipad.post("/api/staff/clock", json={"pin": "7777"}).json()
    assert r["name"] == "Rami" and r["action"] == "in"
    assert "Rami" in ipad.get("/api/staff/on-shift").json()
    assert ipad.post("/api/staff/clock", json={"pin": "7777"}).json()["action"] == "out"
    assert "Rami" not in ipad.get("/api/staff/on-shift").json()


def test_manager_views_and_permissions(ipad, client):
    assert ipad.get("/api/staff/week").status_code == 403
    w = client.get("/api/staff/week").json()
    assert len(w["days"]) == 7 and len(w["staff"]) == 5
    assert all(len(m["shifts"]) == 7 for m in w["staff"])
    assert any(m["hours_7d"] > 0 for m in w["staff"])
    t = client.get("/api/staff/today").json()
    assert len(t["shifts"]) == 4  # one person off each day
    assert {s["status"] for s in t["shifts"]} <= {"upcoming", "missing", "on_time", "late", "done"}


def test_add_staff_rejects_duplicate_pin(client):
    assert client.post("/api/staff", json={"name": "Nora", "role": "Cashier", "pin": "1111"}).status_code == 409
    new = client.post("/api/staff", json={"name": "Nora", "role": "Cashier", "pin": "6666"}).json()
    w = client.get("/api/staff/week").json()
    r = client.post("/api/shifts", json={"staff_id": new["id"], "date": w["days"][0], "start": "10:00", "end": "17:00"})
    assert r.status_code == 200
    nora = next(m for m in client.get("/api/staff/week").json()["staff"] if m["name"] == "Nora")
    assert nora["shifts"][0] == "10:00–17:00"
