"""Reads a POS daily sales report (CSV with columns item,qty). The whole file is checked before anything
is recorded, so a bad report never changes stock halfway through."""
import csv
import io

from .models import MenuItem

MAX_QTY = 10_000  # per line; anything larger is a typo, not a day's sales


class ReportError(ValueError):
    """A problem the manager can fix in the file. The message says which rows and why."""


def parse(data: bytes, menu: dict[str, MenuItem]) -> list[tuple[MenuItem, int]]:
    """`menu` maps lower-case item names to items. Returns (item, qty) lines, with repeated items merged."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ReportError("The file is not a UTF-8 CSV. Export the report from the POS as CSV (UTF-8).")
    reader = csv.DictReader(io.StringIO(text))
    cols = {(c or "").strip().lower() for c in reader.fieldnames or []}
    if not {"item", "qty"} <= cols:
        raise ReportError("The report needs two columns named item and qty.")
    unknown, bad = [], []
    totals: dict[str, int] = {}
    for n, row in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
        name, qty = row.get("item", ""), row.get("qty", "")
        if not name and not qty:
            continue  # blank line
        if name.lower() not in menu:
            unknown.append(name or f"(empty name on row {n})")
            continue
        try:
            q = float(qty)
        except ValueError:
            bad.append(f"row {n} ({name}): quantity '{qty}' is not a number")
            continue
        if q != int(q) or not 0 <= q <= MAX_QTY:
            bad.append(f"row {n} ({name}): quantity {qty} must be a whole number from 0 to {MAX_QTY}")
            continue
        if q == 0:
            continue  # POS reports often list items that did not sell
        totals[name.lower()] = totals.get(name.lower(), 0) + int(q)
    if unknown:
        raise ReportError(f"Items not on the menu: {', '.join(unknown)}")
    if bad:
        raise ReportError("Some quantities are wrong: " + "; ".join(bad))
    if not totals:
        raise ReportError("The report has no sales lines.")
    return [(menu[k], q) for k, q in totals.items()]
