"""Demo mode: one tap signs in as the manager, or opens the cashier iPad, so people trying the app need no passwords."""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def demo_app(tmp_path, demo):
    return create_app(Settings(database_url=f"sqlite:///{tmp_path}/demo.db", anthropic_api_key=None, smtp_host=None,
                               demo_supplier_email=None, demo_mode=demo))


def test_one_tap_manager_and_cashier(tmp_path):
    with TestClient(demo_app(tmp_path, True)) as c:
        info = c.get("/api/auth/demo").json()
        assert info["enabled"] and info["manager_password"] == "manager-demo"
        r = c.post("/api/auth/demo/manager")
        assert r.status_code == 200 and r.json()["home"] == "/manager"
        assert c.get("/api/forecast").status_code == 200  # a real manager session
        c.post("/api/auth/logout")
        r = c.post("/api/auth/demo/cashier")  # an unpaired browser becomes the demo iPad
        assert r.status_code == 200 and r.json()["home"] == "/cashier"
        assert c.get("/api/menu").status_code == 200 and c.get("/api/forecast").status_code == 403


def test_off_when_not_a_demo(tmp_path):
    with TestClient(demo_app(tmp_path, False)) as c:
        assert c.get("/api/auth/demo").json() == {"enabled": False}
        assert c.post("/api/auth/demo/manager").status_code == 404


def test_staff_agent_text_shows_percentages_not_decimals():
    from app.agents.staff_agent import percent_words
    assert percent_words("offers from 0.118 to 0.254") == "offers from 12% to 25%"
    assert percent_words("rated 4.2/5, 10 orders, 0.5/5") == "rated 4.2/5, 10 orders, 0.5/5"
