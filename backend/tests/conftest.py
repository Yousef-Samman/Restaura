import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", anthropic_api_key=None, smtp_host=None,
                        demo_supplier_email=None)
    with TestClient(create_app(settings)) as c:
        yield c
