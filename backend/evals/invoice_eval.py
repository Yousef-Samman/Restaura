"""Invoice reader accuracy. Needs the Claude key.

The real invoice photos can't go in a public repository and their values haven't been confirmed by a person yet,
so this test draws invoices whose correct values are known, then checks what the reader extracts from them.
Each invoice is read in four conditions: clean, blurry, a skewed low-quality phone photo, and with one quantity
covered by a smudge. On the smudged one the right answer is "can't read it" (null), not a guess.
"""
import difflib
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.agents import invoice
from app.seed import seed

from .common import fresh_db, rate

# description, qty, unit price, matching ingredient (None: not an ingredient), quantity in the ingredient's unit
INVOICES = [
    {"supplier": "Dairy Farms Co.", "number": "DF-20418", "date": "2026-10-28", "lines": [
        ("Fresh Milk 1L", 12, 6.50, "Milk", 12000),
        ("Eggs tray 30 pcs", 4, 18.00, "Eggs", 120),
        ("Unsalted Butter 500g", 6, 19.75, "Butter", 3000),
        ("Whipped Cream 1L", 5, 28.00, "Whipped cream", 5000),
    ]},
    {"supplier": "Pantry Wholesale", "number": "PW-7731", "date": "2026-10-27", "lines": [
        ("Wheat Flour 10kg bag", 2, 31.00, "Flour", 20000),
        ("White Sugar 5kg", 1, 21.50, "Sugar", 5000),
        ("Hazelnut Spread 3kg tub", 2, 172.00, "Hazelnut spread", 6000),
        ("Coffee Beans 1kg", 3, 148.00, "Coffee beans", 3000),
        ("Gas cylinder refill", 1, 45.00, None, None),
    ]},
    {"supplier": "Fresh Produce Co.", "number": "FP-0952", "date": "2026-10-29", "lines": [
        ("Strawberries 250g punnet", 8, 7.25, "Strawberries", 2000),
        ("Bananas 1kg", 5, 8.00, "Bananas", 5000),
        ("Mint bunch", 3, 2.50, None, None),
    ]},
]
VAT = 0.15
SMUDGED_LINE = 1  # in the smudged condition, this line's quantity is covered


def _total(inv):
    return round(sum(q * p for _, q, p, _, _ in inv["lines"]) * (1 + VAT), 2)


def draw(inv, smudge=False) -> Image.Image:
    font = ImageFont.load_default(size=22)
    bold = ImageFont.load_default(size=30)
    img = Image.new("RGB", (1000, 760 + 50 * len(inv["lines"])), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 30), inv["supplier"].upper(), font=bold, fill="black")
    d.text((40, 75), "Tax invoice", font=font, fill="black")
    d.text((620, 30), f"Invoice no: {inv['number']}", font=font, fill="black")
    d.text((620, 62), f"Date: {inv['date']}", font=font, fill="black")
    d.text((40, 120), "Bill to: Demo Store, Jeddah", font=font, fill="black")
    y = 190
    for x, h in ((40, "Description"), (520, "Qty"), (640, "Unit price"), (820, "Total")):
        d.text((x, y), h, font=font, fill="black")
    d.line((40, y + 34, 960, y + 34), fill="black", width=2)
    y += 50
    qty_box = None
    for k, (desc, q, p, _, _) in enumerate(inv["lines"]):
        d.text((40, y), desc, font=font, fill="black")
        d.text((520, y), str(q), font=font, fill="black")
        d.text((640, y), f"{p:.2f}", font=font, fill="black")
        d.text((820, y), f"{q * p:.2f}", font=font, fill="black")
        if k == SMUDGED_LINE:
            qty_box = (505, y - 8, 600, y + 32)
        y += 50
    sub = sum(q * p for _, q, p, _, _ in inv["lines"])
    d.line((40, y, 960, y), fill="black", width=1)
    for label, v in (("Subtotal", sub), ("VAT 15%", sub * VAT), ("Total SAR", sub * (1 + VAT))):
        y += 40
        d.text((620, y), label, font=font, fill="black")
        d.text((820, y), f"{v:.2f}", font=font, fill="black")
    if smudge and qty_box:
        d.ellipse(qty_box, fill=(70, 60, 55))
    return img


def condition(img: Image.Image, name: str, rng: random.Random) -> Image.Image:
    if name == "blurry":
        return img.filter(ImageFilter.GaussianBlur(2.2))
    if name == "phone photo":
        img = img.rotate(rng.uniform(3, 5), expand=True, fillcolor=(205, 200, 190))
        img = img.resize((img.width * 11 // 20, img.height * 11 // 20))
        px = img.load()
        for _ in range(img.width * img.height // 25):
            x, y = rng.randrange(img.width), rng.randrange(img.height)
            px[x, y] = tuple(max(0, c - rng.randint(30, 90)) for c in px[x, y])
        return img.filter(ImageFilter.GaussianBlur(0.6))
    return img


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _close(a, b, tol=0.011):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def score(inv, out, smudged=False) -> dict:
    preds = list(out["lines"]) if out else []
    s = {"lines": 0, "found": 0, "qty": 0, "price": 0, "total": 0, "ingredient": 0, "converted": 0}
    abstained = guessed = None
    for k, (desc, q, p, ing, conv) in enumerate(inv["lines"]):
        s["lines"] += 1
        best = max(preds, key=lambda x: difflib.SequenceMatcher(None, desc.lower(), (x["description"] or "").lower()).ratio(), default=None)
        if not best or difflib.SequenceMatcher(None, desc.lower(), (best["description"] or "").lower()).ratio() < 0.6:
            continue
        preds.remove(best)
        s["found"] += 1
        if smudged and k == SMUDGED_LINE:
            # covered, but it can be worked out from line total / unit price; only a wrong number is a failure
            abstained = best["quantity"] is None
            guessed = None if abstained else best["quantity"]
            s["qty"] += abstained or _close(guessed, q)
        else:
            s["qty"] += _close(best["quantity"], q)
        s["price"] += _close(best["unit_price"], p)
        s["total"] += _close(best["line_total"], round(q * p, 2))
        s["ingredient"] += best["ingredient"] == ing
        s["converted"] += (conv is None and best["qty_in_unit"] is None) or _close(best["qty_in_unit"], conv, 0.5)
    s["invoice_total"] = int(bool(out) and _close(out["total"], _total(inv), 0.05))
    s["header"] = int(bool(out) and (out["supplier_name"] or "").lower().startswith(inv["supplier"].lower()[:8])
                      and (out["invoice_number"] or "").replace(" ", "") == inv["number"])
    s["extra_lines"] = len(preds)
    if smudged:
        s["abstained_on_smudge"], s["guessed_value"] = abstained, guessed
    return s


CONDITIONS = ["clean", "blurry", "phone photo", "smudged quantity"]


def run(llm=None, log=print) -> dict:
    if not llm:
        log("  invoice: skipped, needs the Claude key")
        return {"skipped": "needs the Claude key"}
    rng = random.Random(4)
    out = {}
    with fresh_db() as db:
        seed(db, history_days=0)
        for cond in CONDITIONS:
            totals, failed, abstain = {}, 0, []
            for inv in INVOICES:
                smudged = cond == "smudged quantity"
                img = condition(draw(inv, smudge=smudged), cond, rng)
                res = invoice.read(db, llm, _png(img), "image/png")
                failed += res is None
                sc = score(inv, res, smudged)
                if smudged:
                    said, guess = sc.pop("abstained_on_smudge"), sc.pop("guessed_value")
                    true_q = inv["lines"][SMUDGED_LINE][1]
                    abstain.append({"invoice": inv["number"], "said_unreadable": bool(said),
                                    "worked_out_correctly": guess is not None and _close(guess, true_q),
                                    "wrong_number": guess is not None and not _close(guess, true_q)})
                for k, v in sc.items():
                    totals[k] = totals.get(k, 0) + v
            n, docs = totals["lines"], len(INVOICES)
            row = {"invoices": docs, "lines": n, "unreadable_invoices": failed,
                   "line_found": rate(totals["found"], n), "quantity": rate(totals["qty"], n),
                   "unit_price": rate(totals["price"], n), "line_total": rate(totals["total"], n),
                   "ingredient_match": rate(totals["ingredient"], n), "unit_conversion": rate(totals["converted"], n),
                   "invoice_total": rate(totals["invoice_total"], docs), "supplier_and_number": rate(totals["header"], docs),
                   "invented_lines": totals["extra_lines"]}
            if abstain:
                row["smudged_quantity"] = abstain
            out[cond] = row
            log(f"  invoice / {cond}: lines found {row['line_found']:.0%}, qty {row['quantity']:.0%}, "
                f"ingredient match {row['ingredient_match']:.0%}, conversion {row['unit_conversion']:.0%}, "
                f"totals {row['invoice_total']:.0%}" + (f", smudge: wrong numbers {sum(a['wrong_number'] for a in abstain)}/{len(abstain)}" if abstain else ""))
    return out
