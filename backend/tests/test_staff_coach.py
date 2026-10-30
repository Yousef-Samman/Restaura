"""The Staff agent (rules mode): who gets measured on what, weekly reviews, tips on the iPad, and learning from past tips."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def lina(app, client):
    """Lina (a cashier in the sample data) signed in with her PIN on a paired iPad."""
    code = client.post("/api/devices", json={"name": "Cashier iPad"}).json()["code"]
    with TestClient(app) as c:
        assert c.post("/api/devices/pair", json={"code": code}).status_code == 200
        sid = next(s["id"] for s in c.get("/api/auth/staff").json() if s["name"] == "Lina")
        assert c.post("/api/auth/staff-login", json={"staff_id": sid, "pin": "3333"}).status_code == 200
        c.sid = sid
        yield c


def people(client):
    return {p["name"]: p for p in client.get("/api/staff/coach").json()["people"]}


def test_only_order_takers_are_measured_on_selling(client):
    p = people(client)
    assert p["Lina"]["takes_orders"] and "sales" in p["Lina"]
    for maker in ("Omar", "Faisal"):  # crepe makers: no bill, no add-ons, judged on the review and attendance
        assert not p[maker]["takes_orders"] and "sales" not in p[maker]


def test_run_gives_every_person_a_tip_fitting_their_job(client):
    r = client.post("/api/agents/staff/run").json()
    assert r["source"] == "rules" and len(r["tips"]) == 5
    focus = {t["name"]: t["focus"] for t in r["tips"]}
    assert focus["Omar"] not in ("offers", "time_to_pay", "removed")
    assert all(t["name"] in t["tip"] for t in r["tips"])
    # Lina's seeded tip from last week moved her number, and the agent says so
    assert "Lina" in r["headline"]
    lina = client.get(f"/api/staff/{people(client)['Lina']['id']}/coach").json()
    assert lina["previous_tip"]["result"]["verdict"] == "worked"
    assert "offers" in lina["history"]["works_for_them"]


def test_weekly_review_saves_once_per_week(client):
    sid = people(client)["Omar"]["id"]
    body = {"quality": 4, "speed": 3, "cleanliness": 5, "teamwork": 4, "note": "Gets slow at the rush"}
    assert client.post(f"/api/staff/{sid}/review", json=body).status_code == 200
    assert client.post(f"/api/staff/{sid}/review", json=body | {"speed": 4}).status_code == 200
    d = client.get(f"/api/staff/{sid}/coach").json()
    assert d["review_done"] and sum(r["week_start"] == d["reviews"][0]["week_start"] for r in d["reviews"]) == 1
    assert d["reviews"][0]["speed"] == 4
    assert client.post(f"/api/staff/{sid}/review", json=body | {"quality": 6}).status_code == 422


def test_tip_shows_once_on_the_ipad_and_orders_record_who_served(client, lina):
    client.post("/api/agents/staff/run")
    t = lina.get("/api/me/tip").json()
    assert t["tip"]["tip"].startswith("Lina")
    assert lina.post(f"/api/me/tip/{t['tip']['id']}/seen").status_code == 200
    assert lina.get("/api/me/tip").json()["tip"] is None
    item = lina.get("/api/menu").json()[0]
    o = lina.post("/api/orders", json={"lines": [{"item_id": item["id"], "qty": 1}], "seconds_to_pay": 42,
                                       "removed_items": 1, "payment": "cash"})
    assert o.status_code == 200
    assert client.get("/api/me/tip").json()["tip"] is None  # the manager account is not a staff member


def test_staff_coach_is_manager_only(lina):
    assert lina.get("/api/staff/coach").status_code == 403
    assert lina.post("/api/agents/staff/run").status_code == 403
