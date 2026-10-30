"""Run every evaluation and write the report.

    python -m evals            # rules only, no key needed (this is what CI runs)
    python -m evals --ai       # also Claude, with the key in RESTAURA_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY

Writes evals/results/latest.json (every number) and evals/RESULTS.md (the readable report).
"""
import argparse
import datetime as dt
import json
import logging
import time
from pathlib import Path

from . import cashier_eval, forecast_eval, invoice_eval, stock_eval
from .common import ai_llm
from .report import markdown

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m evals")
    ap.add_argument("--ai", action="store_true", help="also evaluate the Claude path")
    ap.add_argument("--model", default="claude-haiku-5-5", help="Claude model for the AI runs (default: a small, cheap one)")
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
    }
    results["run"]["seconds"] = round(time.time() - started)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(results, indent=1, default=str))
    (HERE / "RESULTS.md").write_text(markdown(results))
    print(f"Done in {results['run']['seconds']} s. Report: evals/RESULTS.md, numbers: {out / 'latest.json'}")


if __name__ == "__main__":
    main()
