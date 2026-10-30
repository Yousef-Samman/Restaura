from app.agents import invoice
from app.db import Base, make_engine, make_sessionmaker
from app.seed import seed


class FakeLLM:
    """Stands in for Claude: returns a fixed reading and records the prompt."""
    def __init__(self, out):
        self.out, self.system = out, None

    def json(self, system, content, schema, **_):
        self.system = system
        return self.out


def line(desc, ingredient, qty_in_unit):
    return {"description": desc, "quantity": 6, "unit_price": 5.0, "line_total": 30.0,
            "ingredient": ingredient, "qty_in_unit": qty_in_unit}


def test_invoice_lines_carry_the_ingredient_unit_and_unmatched_lines_have_no_quantity(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/inv.db")
    Base.metadata.create_all(engine)
    with make_sessionmaker(engine)() as db:
        seed(db, history_days=1)
        fake = FakeLLM({"supplier_name": "Veg", "invoice_number": "8419", "invoice_date": None, "total": 60.0, "notes": [],
                        "lines": [line("BANANA 6 KG", "Bananas", 6000), line("EGGS 0.5 BOX", "Eggs", None),
                                  line("KIWI", "Kiwi", 1000)]})
        out = invoice.read(db, fake, b"img", "image/jpeg")
    banana, eggs, kiwi = out["lines"]
    assert banana["ingredient_id"] and banana["unit"] == "g" and banana["qty_in_unit"] == 6000
    assert eggs["ingredient_id"] and eggs["unit"] == "pcs" and eggs["qty_in_unit"] is None
    assert kiwi["ingredient_id"] is None and kiwi["ingredient"] is None and kiwi["qty_in_unit"] is None
    assert "6 KG is 6000 g" in fake.system
