"""Reads a photo of a supplier invoice and proposes delivery lines for the manager to confirm."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ingredient
from .llm import LLM, image_block

SYSTEM = (
    "You read photos of supplier invoices for a restaurant. Extract every line exactly as printed. "
    "Match each line to one of the restaurant's ingredient names when it is the same product, even if the brand, "
    "pack size or wording differ (for example 'Almarai Full Fat Milk 1L' is Milk); otherwise use null. Never guess a number you cannot read: use null and add a note. For matched lines, convert the "
    "delivered quantity into the ingredient's unit (g, ml or pcs) in qty_in_unit when the line gives a weight or "
    "volume (for example 6 KG is 6000 g, 2.85L is 2850 ml) or prints the pack size (20 x 2.85L is 57000 ml). "
    "When the line only gives packs, boxes or cases with no size printed, or converting would mean turning a volume "
    "into a weight, leave qty_in_unit null."
)


def schema(names: list[str]) -> dict:
    line = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "quantity": {"type": ["number", "null"]},
            "unit_price": {"type": ["number", "null"]},
            "line_total": {"type": ["number", "null"]},
            "ingredient": {"type": ["string", "null"]},
            "qty_in_unit": {"type": ["number", "null"]},
        },
        "required": ["description", "quantity", "unit_price", "line_total", "ingredient", "qty_in_unit"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "supplier_name": {"type": ["string", "null"]},
            "invoice_number": {"type": ["string", "null"]},
            "invoice_date": {"type": ["string", "null"]},
            "lines": {"type": "array", "items": line},
            "total": {"type": ["number", "null"]},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["supplier_name", "invoice_number", "invoice_date", "lines", "total", "notes"],
        "additionalProperties": False,
    }


def read(db: Session, llm: LLM, data: bytes, media_type: str) -> dict | None:
    ings = db.scalars(select(Ingredient)).all()
    names = [i.name for i in ings]
    units = {i.name: i.unit for i in ings}
    content = [image_block(data, media_type),
               {"type": "text", "text": "Ingredients and units: " + ", ".join(f"{n} ({units[n]})" for n in names)}]
    out = llm.json(SYSTEM, content, schema(names), effort="medium", max_tokens=8000)
    if out:
        ids = {i.name: i.id for i in ings}
        for line in out["lines"]:
            line["ingredient_id"] = ids.get(line["ingredient"])
            line["unit"] = units.get(line["ingredient"])
            if line["ingredient_id"] is None:
                line["ingredient"] = line["qty_in_unit"] = None
    return out
