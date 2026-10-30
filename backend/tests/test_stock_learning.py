"""The stock agent learns from the manager's edits, real delivery days and counts, and only suggests: nothing
changes until the manager applies a suggestion."""


def lessons(client):
    return client.get("/api/lessons").json()


def by_kind(client):
    return {l["kind"]: l for l in lessons(client)["waiting"]}


def test_sample_history_gives_three_suggestions_and_changes_nothing(client):
    w = by_kind(client)
    assert set(w) == {"order_size", "lead_time", "usage"}
    assert w["order_size"]["value"] == 1.2 and "3 of the last 4" in w["order_size"]["detail"]
    assert w["lead_time"]["current"] == 1 and w["lead_time"]["value"] == 2
    assert 1.1 <= w["usage"]["value"] <= 1.14
    sups = {s["name"]: s for s in client.get("/api/suppliers").json()["suppliers"]}
    assert sups["Dairy Farms Co."]["lead_days"] == 1  # only a suggestion so far


def test_draft_lines_show_the_suggestion_without_changing_the_draft(client):
    client.post("/api/agents/stock/run")
    drafts = [p for p in client.get("/api/purchase-orders").json() if p["status"] == "draft"]
    milk = next(l for p in drafts for l in p["lines"] if l["ingredient"] == "Milk")
    assert milk["suggestion"] and milk["suggestion"]["qty"] > milk["qty"] == milk["drafted_qty"]


def test_applying_changes_future_orders_and_the_suggestion_goes(client):
    w = by_kind(client)
    assert client.post(f"/api/lessons/{w['lead_time']['id']}/apply").status_code == 200
    assert client.post(f"/api/lessons/{w['order_size']['id']}/apply").status_code == 200
    sups = {s["name"]: s for s in client.get("/api/suppliers").json()["suppliers"]}
    assert sups["Dairy Farms Co."]["lead_days"] == 2
    left = by_kind(client)
    assert "lead_time" not in left and "order_size" not in left  # old edits were against the old setting
    assert {l["kind"] for l in lessons(client)["applied"]} == {"lead_time", "order_size"}
    client.post("/api/agents/stock/run")
    milk = next(l for p in client.get("/api/purchase-orders").json() if p["status"] == "draft" for l in p["lines"] if l["ingredient"] == "Milk")
    assert "20% more, from what the agent learned" in milk["reason"]
    assert client.post(f"/api/lessons/{w['lead_time']['id']}/apply").status_code == 404


def test_dismissed_suggestion_stays_away(client):
    w = by_kind(client)
    assert client.post(f"/api/lessons/{w['usage']['id']}/dismiss").status_code == 200
    assert "usage" not in by_kind(client)


def test_forecast_checks_itself(client):
    c = client.get("/api/forecast").json()["scorecard"]
    assert c["weeks"] and all(0 <= w["error"] < 1 for w in c["weeks"])
    assert c["drift"] in (True, False)


def test_learning_beats_no_learning_in_simulation():
    from evals.stock_eval import learning
    r = learning(weeks=8, stores=6)
    assert r["edits_learning_on"] < 0.6 * r["edits_learning_off"]
    assert r["wrong_lead_weeks_on"] < r["wrong_lead_weeks_off"]
    assert r["wrong_suggestions"] == 0
