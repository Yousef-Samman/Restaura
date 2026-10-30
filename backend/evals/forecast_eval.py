"""Forecast backtest. Walk forward through a sales history: on each day, forecast the next 7 days using only the
days before it, exactly as the app does, then compare with what was actually sold.

Restaura's method (app/forecast.py): the last 7 days' average times the weekday's share of a normal week over 8 weeks.
It replaced the earlier method, a plain average of the same weekday over 4 weeks, after this backtest: chosen on the
validation window, confirmed on the test window (both are reported).
Baselines: yesterday's sales, the last 7-day average, and the same weekday last week.
Ablations: the weekday pattern from 4 weeks instead of 8, and the method without the recent level.

Data:
- "synthetic store": 26 weeks with a weekend peak, slow growth, noise and two promotion days. Committed, reproducible.
- "U Walk (real)": the store's real daily sales, April to July 2026, read from the DSR workbooks when they are on
  this machine (RESTAURA_REAL_SALES_DIR). They are not in the repository. Only percentage errors are reported.
"""
import datetime as dt
import glob
import os
import random
from pathlib import Path

from app.forecast import WEEKS, level_weekday_forecast, same_weekday_average

HORIZON = 7
TEST_DAYS = 42
DEFAULT_REAL_DIR = "/mnt/project-files/ai-store-analytics-platform-main/data/samples/U Walk"


def synthetic_history(seed: int = 3, weeks: int = 26) -> dict[dt.date, float]:
    rng = random.Random(seed)
    start = dt.date(2026, 1, 4)
    weekday = {0: 0.85, 1: 0.8, 2: 0.9, 3: 1.25, 4: 1.45, 5: 1.2, 6: 0.9}  # Thu-Sat busiest, as in Saudi cafes
    out = {}
    for i in range(weeks * 7):
        d = start + dt.timedelta(days=i)
        level = 2400 * (1 + 0.004 * i)
        out[d] = round(level * weekday[d.weekday()] * rng.gauss(1, 0.08), 2)
    for promo in (start + dt.timedelta(days=60), start + dt.timedelta(days=130)):
        out[promo] *= 1.6
    return out


def real_history(folder: str | None = None) -> dict[dt.date, float] | None:
    """Daily gross sales = in-store payments + delivery apps, per the original project's format spec."""
    folder = folder or os.getenv("RESTAURA_REAL_SALES_DIR", DEFAULT_REAL_DIR)
    files = sorted(glob.glob(str(Path(folder) / "*.xlsx")))
    if not files:
        return None
    import openpyxl
    out = {}
    for f in files:
        ws = openpyxl.load_workbook(f, data_only=True, read_only=True)["Sales "]
        rows = ws.iter_rows(values_only=True)
        for _ in range(10):
            next(rows)
        header = [str(h).strip() if h else "" for h in next(rows)]
        cols = [i for i, h in enumerate(header) if h in
                ("CASH", "SPAN", "Near Pay", "QLUB", "LOYALTY", "HUNGER", "TOYOU", "JAHEZ", "CHEFFZ", "NOON", "NINJA", "KEETA")]
        for r in rows:
            if not isinstance(r[0], dt.datetime):
                continue
            total = sum(float(r[i]) for i in cols if isinstance(r[i], (int, float)))
            if total > 0:
                out[r[0].date()] = total
    return out or None


# ---- methods: each forecasts `target` from the history before `origin` ------------------------------------------
def _before(h, origin):
    return {d: v for d, v in h.items() if d < origin}


def m_app(h, origin, target, weeks=WEEKS):
    return level_weekday_forecast(_before(h, origin), origin, target, weeks)


def m_previous(h, origin, target, weeks=4):
    return same_weekday_average(_before(h, origin), target, weeks)


def m_yesterday(h, origin, target):
    return h.get(origin - dt.timedelta(days=1))


def m_last7(h, origin, target):
    vals = [h[d] for d in (origin - dt.timedelta(days=k) for k in range(1, 8)) if d in h]
    return sum(vals) / len(vals) if vals else None


def m_last_week(h, origin, target):
    """Same weekday last week; for targets more than a week ahead this is still the last one seen."""
    past = _before(h, origin)
    d = target - dt.timedelta(days=7)
    while d >= origin:
        d -= dt.timedelta(days=7)
    return past.get(d)


APP = "Restaura: recent level x weekday, 8 weeks (app)"
PREVIOUS = "Previous app method: same weekday, 4-week average"
METHODS = {
    "Yesterday's sales (baseline)": m_yesterday,
    "Last 7-day average (baseline)": m_last7,
    "Same weekday last week (baseline)": m_last_week,
    PREVIOUS: m_previous,
    APP: m_app,
    "Ablation: weekday pattern from 4 weeks": lambda h, o, t: m_app(h, o, t, 4),
    "Ablation: no recent level (same weekday, 8-week average)": lambda h, o, t: m_previous(h, o, t, 8),
}


def backtest(h: dict[dt.date, float], test_days: int = TEST_DAYS) -> dict:
    days = sorted(h)
    origins = [d for d in days[-test_days - HORIZON + 1:-HORIZON + 1]]
    res = {}
    for name, f in METHODS.items():
        abs_err, pct_err, n, missing = 0.0, 0.0, 0, 0
        for o in origins:
            for k in range(HORIZON):
                t = o + dt.timedelta(days=k)
                if t not in h:
                    continue
                p = f(h, o, t)
                if p is None:
                    missing += 1
                    continue
                abs_err += abs(p - h[t])
                pct_err += abs(p - h[t]) / h[t]
                n += 1
        res[name] = {"forecasts": n, "no_forecast": missing, "mae_sar": round(abs_err / n, 1) if n else None,
                     "mape": pct_err / n if n else None}
    return {"days_of_history": len(days), "forecast_origins": len(origins), "horizon_days": HORIZON, "methods": res}


def windows(h: dict[dt.date, float]) -> dict:
    """Validation: the TEST_DAYS days before the test window, used to choose a method.
    Test: the last TEST_DAYS days, used only to confirm the choice."""
    cut = sorted(h)[-TEST_DAYS - 1]
    return {"validation": backtest({d: v for d, v in h.items() if d <= cut}), "test": backtest(h)}


def run(log=print) -> dict:
    out = {"synthetic store": windows(synthetic_history())}
    real = real_history()
    if real:
        r = windows(real)
        for w in r.values():
            for m in w["methods"].values():
                m.pop("mae_sar")  # real revenue stays private; percentages only
        out["U Walk (real)"] = r
    for name, r in out.items():
        t = r["test"]["methods"]
        log(f"  forecast / {name} (test window): app error {t[APP]['mape']:.1%}, previous method {t[PREVIOUS]['mape']:.1%}, "
            f"best baseline {min(v['mape'] for k, v in t.items() if 'baseline' in k):.1%}")
    if not real:
        log("  forecast / U Walk (real): skipped, the DSR workbooks are not on this machine")
    return out
