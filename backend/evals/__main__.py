"""Run every evaluation and write the report.

    python -m evals                 # rules only, no key needed
    python -m evals --ai            # also Claude, with the key in RESTAURA_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY
    python -m evals --with-tests    # also run the test suite and record which tests passed (CI does this)
    python -m evals --keep-ai       # rules only, keeping the Claude results of the last --ai run (the app's button)

Writes evals/results/latest.json (every number) and evals/RESULTS.md (the readable report).
"""
import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import cashier_eval, forecast_eval, invoice_eval, stock_eval
from .common import ai_llm
from .fixes import FIXES
from .report import markdown

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m evals")
    ap.add_argument("--ai", action="store_true", help="also evaluate the Claude path")
    ap.add_argument("--model", default="claude-haiku-5-5", help="Claude model for the AI runs (default: a small, cheap one)")
    ap.add_argument("--with-tests", action="store_true", help="also run pytest and record the results")
    ap.add_argument("--keep-ai", action="store_true", help="keep the Claude results and test results of the last run")
    ap.add_argument("--out", default=str(HERE / "results"), help="folder for latest.json")
    args = ap.parse_args()
    logging.basicConfig(level=logging.ERROR)

    llm = None
    if args.ai:
        llm = ai_llm(args.model)
        if not llm:
            raise SystemExit("--ai needs RESTAURA_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY")
    print(f"Restaura evaluation, {'rules and Claude (' + args.model + ')' if llm else 'rules only'}")
    started = time.time()
    results = {
        "run": {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "ai_model": args.model if llm else None},
        "cashier": cashier_eval.run(llm),
        "forecast": forecast_eval.run(),
        "stock": stock_eval.run(llm),
        "invoice": invoice_eval.run(llm),
        # learning on vs off: special days for the forecast, the stock agent's learning loop
        "learning": {"forecast_special_days": forecast_eval.special_days()},
    }
    results["learning"]["stock"] = results["stock"]["learning"]
    if llm:
        results["run"]["ai_at"] = results["run"]["at"]
    results["fixes"] = FIXES
    out = Path(args.out)
    previous = _load(out / "latest.json")
    if args.with_tests:
        print("  running the test suite…")
        results["tests"] = run_tests()
    elif args.keep_ai and previous.get("tests"):
        results["tests"] = previous["tests"]
    if args.keep_ai and not llm and previous.get("run", {}).get("ai_model"):
        _carry_ai(results, previous)
    results["run"]["seconds"] = round(time.time() - started)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(results, indent=1, default=str))
    (HERE / "RESULTS.md").write_text(markdown(results))
    print(f"Done in {results['run']['seconds']} s. Report: evals/RESULTS.md, numbers: {out / 'latest.json'}")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _carry_ai(results: dict, previous: dict) -> None:
    """Copy the Claude results of the last --ai run into a rules-only run, marked with when they were measured."""
    results["run"]["ai_model"] = previous["run"]["ai_model"]
    results["run"]["ai_at"] = previous["run"].get("ai_at") or previous["run"]["at"]
    for scen, s in previous.get("cashier", {}).items():
        ai = s["methods"].get("Restaura with Claude")
        if ai and scen in results["cashier"]:
            results["cashier"][scen]["methods"]["Restaura with Claude"] = ai
    if "with Claude" in previous.get("stock", {}):
        results["stock"]["with Claude"] = previous["stock"]["with Claude"]
        if "busy_days_ahead" in previous["stock"]:
            results["stock"]["busy_days_ahead"] = previous["stock"]["busy_days_ahead"]
    if "skipped" not in previous.get("invoice", {"skipped": 1}):
        results["invoice"] = previous["invoice"]


def run_tests() -> dict:
    """Runs the test suite and returns which tests passed, by file."""
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "junit.xml"
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"],
                       cwd=HERE.parent, capture_output=True, text=True)
        if not xml.exists():
            return {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "error": "pytest did not run"}
        cases = []
        for tc in ET.parse(xml).getroot().iter("testcase"):
            failed = any(child.tag in ("failure", "error") for child in tc)
            skipped = any(child.tag == "skipped" for child in tc)
            cases.append({"file": tc.get("classname", "").split(".")[-1], "name": tc.get("name"),
                          "outcome": "failed" if failed else "skipped" if skipped else "passed"})
    return {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "passed": sum(c["outcome"] == "passed" for c in cases), "total": len(cases), "cases": cases}


if __name__ == "__main__":
    main()
