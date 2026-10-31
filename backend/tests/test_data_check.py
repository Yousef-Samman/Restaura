"""The data check holds records that don't fit out of learning until the manager decides, and the rules say what
they are sure of."""
from app.agents import data_check


def checks(client):
    """The waiting checks by kind; the sample has two sales days, the one imported twice comes first."""
    out = {}
    for f in client.get("/api/data-checks").json()["waiting"]:
        out.setdefault(f["kind"], f)
    return out


def test_sample_mistakes_are_found_and_explained(client):
    w = checks(client)
    assert set(w) == {"edit", "count", "sales_day"}
    assert w["edit"]["verdict"] == "mistake" and "zero" in w["edit"]["why"]
    assert w["count"]["verdict"] == "mistake" and w["count"]["facts"]["counted"] == 240
    assert w["sales_day"]["verdict"] == "mistake" and "imported twice" in w["sales_day"]["why"]
    assert w["sales_day"]["facts"]["orders_with_an_identical_twin"] == w["sales_day"]["facts"]["orders"]
    assert all(f["source"] == "rules" for f in w.values())
    late = client.get("/api/data-checks").json()["waiting"][-1]
    assert late["facts"]["last_order"] < "16:00" and late["verdict"] == "unsure"  # the import that stopped early: Claude or the manager
    assert len(client.get("/api/data-checks").json()["waiting"]) == 4  # found once, not again


def test_held_day_is_left_out_of_the_forecast(client):
    before = client.get("/api/forecast").json()["days"][0]["sales"]
    checks(client)
    after = client.get("/api/forecast").json()["days"][0]["sales"]
    assert after < before  # the day imported twice no longer lifts the level


def test_manager_decides(client):
    w = checks(client)
    r = client.post(f"/api/data-checks/{w['edit']['id']}", json={"correct": False})
    assert r.status_code == 200 and r.json()["status"] == "wrong"
    assert client.post(f"/api/data-checks/{w['edit']['id']}", json={"correct": True}).status_code == 404
    r = client.post(f"/api/data-checks/{w['sales_day']['id']}", json={"correct": True, "label": "Family day"})
    assert r.json()["status"] == "kept"
    past = client.get("/api/forecast").json()["special_days"]["past"]
    assert any(p["label"] == "Family day" and p["date"] == w["sales_day"]["facts"]["date"] for p in past)
    assert set(checks(client)) == {"count", "sales_day"}  # the day that stopped early is still waiting


def test_rules_know_a_correction_from_a_slip():
    f = {"kind": "count", "facts": {"unit": "g", "difference": 9000, "previous_count_difference": -9500, "recipes_used": 14000}}
    assert data_check.rules_verdict(f)["verdict"] == "real"
    f["facts"] |= {"difference": -9000, "previous_count_difference": 0, "counted": 1000, "system_expected": 10000}
    assert data_check.rules_verdict(f)["verdict"] == "mistake"


def test_check_makes_learning_better_in_simulation():
    from evals.data_check_eval import counts, sales
    c = counts(stores=8)["results"]
    assert c["on"]["right"] > c["off"]["right"] and c["on"]["wrong"] <= c["off"]["wrong"]
    s = sales()
    assert s["mistakes_caught"] == s["mistakes"] and s["error"]["after the manager decides"] < s["error"]["no check"]
