import datetime as dt

from app.forecast import level_weekday_forecast, same_weekday_average


def test_forecast_shape_and_method(client):
    f = client.get("/api/forecast").json()
    assert len(f["days"]) == 7 and len(f["actual"]) == 14
    today = dt.date.today()
    assert f["days"][0]["date"] == today.isoformat()
    for d in f["days"]:
        assert 4 <= d["based_on"] <= 5  # 30 days of sample history covers four or five of each weekday
        assert d["low"] <= d["sales"] <= d["high"]
    assert f["tomorrow_items"] and all(i["qty"] >= 0 for i in f["tomorrow_items"])
    flour = next(i for i in f["ingredients"] if i["name"] == "Flour")
    assert flour["need"] > 0


def _two_weeks(origin, normal, friday):
    return {origin - dt.timedelta(days=k): (friday if (origin - dt.timedelta(days=k)).weekday() == 4 else normal)
            for k in range(1, 15)}


def test_steady_sales_give_the_weekday_back():
    origin = dt.date(2026, 3, 2)  # a Monday
    h = _two_weeks(origin, 100, 200)
    friday = dt.date(2026, 3, 6)
    assert abs(level_weekday_forecast(h, origin, friday, weeks=2) - 200) < 1e-9
    assert abs(level_weekday_forecast(h, origin, origin, weeks=2) - 100) < 1e-9


def test_forecast_follows_a_change_in_level():
    # sales doubled last week; a plain weekday average lags, the level x weekday forecast follows
    origin = dt.date(2026, 3, 2)
    h = _two_weeks(origin, 100, 200)
    h |= {d: v * 2 for d, v in h.items() if d >= origin - dt.timedelta(days=7)}
    friday = dt.date(2026, 3, 6)
    assert abs(same_weekday_average(h, friday, weeks=2) - 300) < 1e-9
    assert abs(level_weekday_forecast(h, origin, friday, weeks=2) - 400) < 1e-9


def test_no_history_gives_no_forecast():
    assert level_weekday_forecast({}, dt.date(2026, 3, 2), dt.date(2026, 3, 3)) is None
