import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def app(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", anthropic_api_key=None, smtp_host=None,
                        demo_supplier_email=None, manager_password="m-pass", cashier_password="c-pass")
    return create_app(settings)


@pytest.fixture
def anon(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(app):
    """Signed in as the manager."""
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "manager", "password": "m-pass"}).status_code == 200
        yield c


@pytest.fixture
def ipad(app, client):
    """A cashier signed in on a device the manager paired."""
    code = client.post("/api/devices", json={"name": "Cashier iPad"}).json()["code"]
    with TestClient(app) as c:
        assert c.post("/api/devices/pair", json={"code": code}).status_code == 200
        assert c.post("/api/auth/login", json={"username": "cashier", "password": "c-pass"}).status_code == 200
        yield c
