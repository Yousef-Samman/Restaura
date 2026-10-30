"""Regression checks: the offline evaluations must keep the results the report claims. If a change makes an agent
worse than its baseline, or breaks a known-correct order, CI fails. Thresholds sit a little under today's results."""
from evals import cashier_eval, forecast_eval, stock_eval


def test_cashier_learns_what_sells_together():
    r = cashier_eval.run(log=lambda *_: None)
    changed = r["changed habits"]["methods"]
    # when habits differ from the hand-written rules, learning from orders must clearly beat the best-seller baseline
    assert changed["Restaura rules (app)"]["hit_at_2"] >= changed["Best sellers (baseline)"]["hit_at_2"] + 0.15
    # and both signals must be pulling their weight
    assert changed["Restaura rules (app)"]["hit_at_2"] > changed["Ablation: pairing rules only"]["hit_at_2"]
    sample = r["app sample data"]["methods"]
    assert sample["Restaura rules (app)"]["hit_at_2"] >= sample["Best sellers (baseline)"]["hit_at_2"] - 0.02


def test_forecast_beats_baselines_and_previous_method():
    w = forecast_eval.windows(forecast_eval.synthetic_history())["test"]["methods"]
    app = w[forecast_eval.APP]["mape"]
    assert app < w[forecast_eval.PREVIOUS]["mape"]
    assert all(app < v["mape"] for k, v in w.items() if "baseline" in k)


def test_stock_agent_known_orders_and_random_stores():
    s = stock_eval.scenarios(stock_eval.no_llm())
    assert s["accuracy"] == 1 and s["warnings_found"] == s["warnings_expected"] and s["duplicate_orders_on_second_run"] == 0
    p = stock_eval.properties(n=80)
    assert p["recall"] == 1 and p["precision"] == 1 and p["orders_too_small"] == 0 and p["orders_too_large"] == 0
