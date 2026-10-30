def test_cashier_ticks_tasks_and_manager_sees_them(ipad, client):
    r = ipad.get("/api/routines").json()
    assert [x["key"] for x in r] == ["opening", "midday", "closing"]
    task = r[0]["tasks"][0]
    assert ipad.post(f"/api/routines/tasks/{task['id']}/toggle", json={"done_by": "Sara"}).json() == {"done": True}
    mine = next(t for t in client.get("/api/routines").json()[0]["tasks"] if t["id"] == task["id"])
    assert mine["done"] and mine["done_by"] == "Sara"
    assert ipad.post(f"/api/routines/tasks/{task['id']}/toggle", json={}).json() == {"done": False}


def test_history_and_task_editing_are_manager_only(ipad, client):
    assert ipad.get("/api/routines/history").status_code == 403
    assert ipad.post("/api/routines/tasks", json={"routine": "opening", "text": "x"}).status_code == 403
    h = client.get("/api/routines/history?days=7").json()
    assert len(h) == 7 and all(0 <= d["opening"] <= 1 for d in h)
    t = client.post("/api/routines/tasks", json={"routine": "closing", "text": "Lock the door"}).json()
    assert any(x["text"] == "Lock the door" for x in client.get("/api/routines").json()[2]["tasks"])
    client.delete(f"/api/routines/tasks/{t['id']}")
    assert not any(x["text"] == "Lock the door" for x in client.get("/api/routines").json()[2]["tasks"])
