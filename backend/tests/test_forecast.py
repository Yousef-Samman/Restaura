import datetime as dt


def test_forecast_shape_and_method(client):
    f = client.get("/api/forecast").json()
    assert len(f["days"]) == 7 and len(f["actual"]) == 14
    today = dt.date.today()
    assert f["days"][0]["date"] == today.isoformat()
    for d in f["days"]:
        assert d["based_on"] == 4  # 30 days of sample history covers four of each weekday
        assert d["low"] <= d["sales"] <= d["high"]
    assert f["tomorrow_items"] and all(i["qty"] >= 0 for i in f["tomorrow_items"])
    flour = next(i for i in f["ingredients"] if i["name"] == "Flour")
    assert flour["need"] > 0


def test_forecast_matches_same_weekday_average(client):
    f = client.get("/api/forecast").json()
    actual = {a["date"]: a["sales"] for a in f["actual"]}
    d = f["days"][0]["date"]
    week1 = (dt.date.fromisoformat(d) - dt.timedelta(days=7)).isoformat()
    week2 = (dt.date.fromisoformat(d) - dt.timedelta(days=14)).isoformat()
    assert f["days"][0]["low"] <= min(actual[week1], actual[week2])
    assert f["days"][0]["high"] >= max(actual[week1], actual[week2])
