"""The manager's Agent evaluation page shows the latest results of `python -m evals`, and nothing else."""
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import evaluation
from app.config import Settings
from app.main import create_app

COMMITTED = Path(__file__).resolve().parent.parent / "evals" / "results" / "latest.json"


def manager(tmp_path, results: Path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/t.db", anthropic_api_key=None, eval_results=results,
                              manager_password="m", cashier_password="c"))
    c = TestClient(app)
    c.__enter__()
    assert c.post("/api/auth/login", json={"username": "manager", "password": "m"}).status_code == 200
    return c


def test_page_shows_the_committed_results(tmp_path):
    results = tmp_path / "latest.json"
    shutil.copy(COMMITTED, results)
    body = manager(tmp_path, results).get("/api/evaluation").json()
    assert body["running"] is False
    e = body["results"]
    raw = evaluation.load(results)
    own = raw["cashier"]["changed habits"]["methods"]
    # the page shows the evaluation's own numbers, rounded, never different ones
    assert e["cashier"]["own"]["rows"][0]["value"] == round(100 * own["Best sellers (baseline)"]["hit_at_2"], 1)
    assert e["cashier"]["own"]["rows"][1]["value"] == round(100 * own["Restaura rules (app)"]["hit_at_2"], 1)
    assert e["stock"]["right"] == raw["stock"]["rules"]["correct_lines"]
    assert e["summary"]["fixes"] == len(raw["fixes"])
    assert e["verdict"]["headline"] and len(e["verdict"]["points"]) == 3


def test_verdict_does_not_claim_a_win_it_did_not_get(tmp_path):
    raw = evaluation.load(COMMITTED)
    m = raw["cashier"]["changed habits"]["methods"]
    m["Best sellers (baseline)"]["hit_at_2"] = 0.99  # baseline now beats the helper
    assert "Some results need a look" in evaluation.view(raw)["verdict"]["headline"]


def test_page_without_results_says_so(tmp_path):
    body = manager(tmp_path, tmp_path / "missing.json").get("/api/evaluation").json()
    assert body["results"] is None


def test_page_is_for_the_manager_only(anon):
    assert anon.get("/api/evaluation").status_code == 401
    assert anon.post("/api/evaluation/run").status_code == 401
