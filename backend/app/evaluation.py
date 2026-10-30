"""Agent evaluation page: reads the latest results of `python -m evals` and shapes them for the manager app.
Every number shown comes from evals/results/latest.json; nothing here measures anything itself.
The manager can re-run the rules-only checks from the page; Claude results carry over from the last --ai run."""
import json
import subprocess
import sys
import threading
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
RESULTS = BACKEND / "evals" / "results" / "latest.json"
APP_CASHIER, BASELINE_CASHIER, AI_CASHIER = "Restaura rules (app)", "Best sellers (baseline)", "Restaura with Claude"
FORECAST_APP, FORECAST_PREVIOUS = "Restaura: recent level x weekday, 8 weeks (app)", "Previous app method: same weekday, 4-week average"

# robustness tests, grouped as the manager would think of them (test name prefix -> group)
GROUPS = [
    ("Bad sales files are refused with a clear reason, and stock isn't touched",
     ("test_bad_sales_report", "test_messy_but_valid_report")),
    ("Claude down, slow or answering badly: the rules take over",
     ("test_agents_fall_back_to_rules", "test_invoice_photo_when_claude_is_down", "test_claude_calls_have_a_short_timeout")),
    ("Selling more than is in stock, or a dish with no recipe, gets a clear warning",
     ("test_selling_more_than_stock", "test_menu_item_without_recipe")),
    ("A new store with no data, or nothing in stock, still works",
     ("test_new_store_with_no_data", "test_nothing_in_stock")),
]


class Runner:
    """Runs `python -m evals --keep-ai` in the background, one run at a time."""

    def __init__(self, results: Path = RESULTS):
        self.results = results
        self.proc: subprocess.Popen | None = None
        self.error: str | None = None
        self.lock = threading.Lock()

    @property
    def running(self) -> bool:
        if self.proc and self.proc.poll() is not None:
            if self.proc.returncode:
                err = (self.proc.stderr.read() or "").strip().splitlines()
                self.error = err[-1] if err else "The checks stopped with an error."
            self.proc = None
        return self.proc is not None

    def start(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.error = None
            self.proc = subprocess.Popen([sys.executable, "-m", "evals", "--keep-ai", "--out", str(self.results.parent)],
                                         cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            return True


def _pct(x):
    return None if x is None else round(100 * x, 1)


def load(path: Path = RESULTS) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def view(r: dict) -> dict:
    """The page's data: summary, verdict, one block per agent, robustness checks and fixes."""
    run = r["run"]
    cashier = {}
    for key, scen in (("own", "changed habits"), ("demo", "app sample data")):
        s = r["cashier"].get(scen)
        if not s:
            continue
        m = s["methods"]
        rows = [{"label": "Suggest best sellers", "value": _pct(m[BASELINE_CASHIER]["hit_at_2"]), "kind": "base"},
                {"label": "Restaura rules", "value": _pct(m[APP_CASHIER]["hit_at_2"]), "kind": "app"}]
        if AI_CASHIER in m:
            rows.append({"label": "Restaura with Claude", "value": _pct(m[AI_CASHIER]["hit_at_2"]), "kind": "ai"})
        best = max(r["value"] for r in rows[1:])
        cashier[key] = {"cases": m[APP_CASHIER]["cases"], "rows": rows, "lift": round(best - rows[0]["value"], 1)}

    data = "U Walk (real)" if "U Walk (real)" in r["forecast"] else "synthetic store"
    fm = r["forecast"][data]["test"]["methods"]
    baselines = {k: v["mape"] for k, v in fm.items() if "baseline" in k}
    forecast = {"data": "Real U Walk sales" if data == "U Walk (real)" else "Synthetic store", "days": r["forecast"][data]["test"]["days_of_history"],
                "before": _pct(fm[FORECAST_PREVIOUS]["mape"]), "after": _pct(fm[FORECAST_APP]["mape"]),
                "rows": [{"label": k.replace(" (baseline)", ""), "value": _pct(v), "kind": "base"} for k, v in baselines.items()]
                + [{"label": "Restaura", "value": _pct(fm[FORECAST_APP]["mape"]), "kind": "app"}]}

    st = r["stock"]
    sc = st.get("with Claude") or st["rules"]
    rs = st["random_stores"]
    stock = {"right": sc["correct_lines"], "expected": sc["expected_lines"], "recall": _pct(rs["recall"]),
             "precision": _pct(rs["precision"]), "stores": rs["stores"], "too_small": rs["orders_too_small"],
             "warnings": [sc["warnings_found"], sc["warnings_expected"]],
             "claude_numbers_ok": (len(st["with Claude"]["ungrounded_numbers"]) == 0) if "with Claude" in st else None}

    inv = r["invoice"]
    invoice = None
    if "skipped" not in inv:
        conds = [{"name": k.replace(" quantity", "").capitalize(), "key": k.split()[0],
                  "value": _pct(min(v["quantity"], v["unit_price"], v["ingredient_match"])), "lines": v["lines"]} for k, v in inv.items()]
        smudge = inv.get("smudged quantity", {}).get("smudged_quantity", [])
        invoice = {"conditions": conds, "lines": next(iter(inv.values()))["lines"],
                   "smudge_ok": sum(not a["wrong_number"] for a in smudge), "smudge_total": len(smudge),
                   "smudge_said": sum(a["said_unreadable"] for a in smudge)}

    tests = r.get("tests") or {}
    robustness = []
    for text, prefixes in GROUPS:
        cases = [c for c in tests.get("cases", []) if c["name"].startswith(prefixes)]
        if cases:
            robustness.append({"text": text, "passed": sum(c["outcome"] == "passed" for c in cases), "total": len(cases)})

    cases = (sum(s["methods"][APP_CASHIER]["cases"] for s in r["cashier"].values())
             + sum(w["test"]["methods"][FORECAST_APP]["forecasts"] for w in r["forecast"].values())
             + stock["expected"] + stock["stores"] + (sum(c["lines"] for c in invoice["conditions"]) if invoice else 0))

    # verdict, from the numbers only
    own = cashier.get("own")
    beats = [own and own["lift"] > 0, forecast["after"] < min(x["value"] for x in forecast["rows"] if x["kind"] == "base"),
             stock["right"] == stock["expected"] and stock["recall"] == 100 and stock["precision"] == 100,
             invoice is None or all(c["value"] == 100 for c in invoice["conditions"])]
    headline = ("Every agent was tested on data it had never seen, and each one beats the simple method it replaces."
                if all(beats) else "Every agent was tested on data it had never seen. Some results need a look below.")
    points = []
    if own:
        best = own["rows"][-1]
        points.append({"agent": "Cashier helper", "text": f"guesses the add-on a customer really wants {best['value']:.0f}% of the time, "
                       f"against {own['rows'][0]['value']:.0f}% for suggesting best sellers."})
    points.append({"agent": "Forecast", "text": f"is off by {forecast['after']}% on {forecast['data'][0].lower() + forecast['data'][1:]}, "
                   f"down from {forecast['before']}% before testing."})
    points.append({"agent": "Stock agent" + (" and invoice reader" if invoice else ""),
                   "text": f"got {stock['right']} of {stock['expected']} orders exactly right"
                   + (f" and read {min(c['value'] for c in invoice['conditions']):.0f}% of invoice lines right." if invoice else ".")})
    return {
        "run": {"at": run["at"], "ai_at": run.get("ai_at"), "ai_model": run.get("ai_model"), "tests_at": tests.get("at")},
        "summary": {"checks_passed": tests.get("passed"), "checks_total": tests.get("total"), "agents": 4, "cases": cases,
                    "fixes": len(r.get("fixes", []))},
        "verdict": {"headline": headline, "points": points},
        "cashier": cashier, "forecast": forecast, "stock": stock, "invoice": invoice,
        "robustness": robustness, "fixes": r.get("fixes", []),
    }
