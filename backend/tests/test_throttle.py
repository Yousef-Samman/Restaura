"""Guessing is slowed down: after 5 wrong tries the same account from the same address is locked, even for the
right password, and the lock ends by itself."""
from app.throttle import Throttle


def wrong(client, user="manager"):
    return client.post("/api/auth/login", json={"username": user, "password": "nope"})


def test_manager_login_locks_after_five_wrong_tries(anon):
    assert [wrong(anon).status_code for _ in range(5)] == [401] * 5
    r = anon.post("/api/auth/login", json={"username": "manager", "password": "m-pass"})
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]  # even the right password waits
    assert wrong(anon, "cashier").status_code == 401  # another account is not locked


def test_right_password_resets_the_count(anon):
    for _ in range(4):
        wrong(anon)
    assert anon.post("/api/auth/login", json={"username": "manager", "password": "m-pass"}).status_code == 200
    assert [wrong(anon).status_code for _ in range(4)] == [401] * 4


def test_wrong_pins_lock_the_clock(ipad):
    codes = [ipad.post("/api/staff/clock", json={"pin": "9999"}).status_code for _ in range(6)]
    assert codes[:5] == [404] * 5 and codes[5] == 429


def test_wrong_staff_pins_lock_that_person(ipad):
    sid = ipad.get("/api/auth/staff").json()[0]["id"]
    codes = [ipad.post("/api/auth/staff-login", json={"staff_id": sid, "pin": "0000"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_lock_ends_by_itself():
    t = [0.0]
    th = Throttle(clock=lambda: t[0])
    for _ in range(5):
        th.fail("k")
    try:
        th.check("k")
        assert False
    except Exception as exc:
        assert exc.status_code == 429
    t[0] += 15 * 60 + 1
    th.check("k")  # the old failures have aged out
