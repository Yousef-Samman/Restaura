def test_api_needs_sign_in(anon):
    assert anon.get("/api/menu").status_code == 401
    assert anon.get("/api/stock").status_code == 401
    assert anon.get("/", follow_redirects=False).headers["location"] == "/login"


def test_wrong_password(anon):
    assert anon.post("/api/auth/login", json={"username": "manager", "password": "nope"}).status_code == 401


def test_manager_signs_in_anywhere_and_lands_on_manager(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/manager"
    assert client.get("/cashier", follow_redirects=False).headers["location"] == "/login"


def test_cashier_refused_on_unpaired_device(anon):
    r = anon.post("/api/auth/login", json={"username": "cashier", "password": "c-pass"})
    assert r.status_code == 403 and "iPad" in r.json()["detail"]


def test_cashier_on_paired_ipad(ipad):
    assert ipad.get("/", follow_redirects=False).headers["location"] == "/cashier"
    assert ipad.get("/api/menu").status_code == 200
    assert ipad.get("/api/stock").status_code == 403  # manager screens stay closed
    assert ipad.get("/manager", follow_redirects=False).headers["location"] == "/login"


def test_pairing_code_works_once(app, client, anon):
    code = client.post("/api/devices", json={"name": "iPad"}).json()["code"]
    assert anon.post("/api/devices/pair", json={"code": code}).status_code == 200
    assert anon.post("/api/devices/pair", json={"code": code}).status_code == 400


def test_revoking_device_signs_cashier_out(client, ipad):
    dev = client.get("/api/devices").json()[0]
    client.post(f"/api/devices/{dev['id']}/revoke")
    assert ipad.get("/api/menu").status_code == 401
