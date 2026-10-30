"""Sample data for the demo. Names, prices and recipes are illustrative, not a real store's records."""
import datetime as dt
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Ingredient, MenuItem, Order, OrderLine, RecipeLine, StockMove, Supplier

SUPPLIERS = [
    ("Fresh Produce Co.", "orders@fresh-produce.example", 1),
    ("Dairy Farms Co.", "orders@dairy-farms.example", 1),
    ("Pantry Wholesale", "orders@pantry-wholesale.example", 2),
    ("Frozen Treats Co.", "orders@frozen-treats.example", 2),
]

# name, unit, SAR per unit, min, par, opening stock, supplier
INGREDIENTS = [
    ("Flour", "g", 0.003, 5000, 20000, 12000, "Pantry Wholesale"),
    ("Milk", "ml", 0.006, 6000, 20000, 15000, "Dairy Farms Co."),
    ("Eggs", "pcs", 0.6, 60, 180, 120, "Dairy Farms Co."),
    ("Butter", "g", 0.04, 1000, 4000, 2500, "Dairy Farms Co."),
    ("Sugar", "g", 0.004, 2000, 8000, 6000, "Pantry Wholesale"),
    ("Hazelnut spread", "g", 0.06, 1500, 6000, 2400, "Pantry Wholesale"),
    ("Chocolate sauce", "ml", 0.05, 1500, 5000, 3000, "Pantry Wholesale"),
    ("Pistachio cream", "g", 0.12, 800, 3000, 1000, "Pantry Wholesale"),
    ("Kunafa pastry", "g", 0.04, 600, 2000, 900, "Pantry Wholesale"),
    ("Coffee beans", "g", 0.15, 1000, 4000, 2500, "Pantry Wholesale"),
    ("Strawberries", "g", 0.03, 1500, 5000, 2000, "Fresh Produce Co."),
    ("Bananas", "g", 0.008, 1500, 5000, 3000, "Fresh Produce Co."),
    ("Whipped cream", "ml", 0.03, 1000, 4000, 2000, "Dairy Farms Co."),
    ("Vanilla ice cream", "g", 0.03, 2000, 8000, 4000, "Frozen Treats Co."),
    ("Ice", "g", 0.001, 5000, 20000, 15000, "Frozen Treats Co."),
]

CREPE = {"Flour": 80, "Milk": 120, "Eggs": 1, "Butter": 10}
WAFFLE = {"Flour": 120, "Milk": 100, "Eggs": 1, "Butter": 20, "Sugar": 20}

# category, name, price, is_addon, recipe
MENU = [
    ("Crepes", "Hazelnut crepe", 38, False, CREPE | {"Hazelnut spread": 60}),
    ("Crepes", "Triple chocolate crepe", 48, False, CREPE | {"Chocolate sauce": 60, "Hazelnut spread": 30}),
    ("Crepes", "Strawberry crepe", 52, False, CREPE | {"Strawberries": 100, "Chocolate sauce": 30}),
    ("Crepes", "Banana crepe", 49, False, CREPE | {"Bananas": 120, "Chocolate sauce": 40}),
    ("Crepes", "Pistachio kunafa crepe", 56, False, CREPE | {"Pistachio cream": 70, "Kunafa pastry": 50}),
    ("Waffles", "Classic chocolate waffle", 42, False, WAFFLE | {"Chocolate sauce": 40}),
    ("Waffles", "Strawberry waffle", 49, False, WAFFLE | {"Strawberries": 100, "Whipped cream": 40}),
    ("Pancakes", "Mini pancakes", 39, False, {"Flour": 100, "Milk": 120, "Eggs": 1, "Butter": 10, "Sugar": 15, "Chocolate sauce": 30}),
    ("Drinks", "Americano", 18, False, {"Coffee beans": 18}),
    ("Drinks", "Latte", 21, False, {"Coffee beans": 18, "Milk": 200}),
    ("Drinks", "Spanish latte", 24, False, {"Coffee beans": 18, "Milk": 180, "Sugar": 15}),
    ("Drinks", "Iced latte", 23, False, {"Coffee beans": 18, "Milk": 180, "Ice": 150}),
    ("Drinks", "Hot chocolate", 21, False, {"Milk": 220, "Chocolate sauce": 40}),
    ("Add-ons", "Scoop of vanilla ice cream", 9, True, {"Vanilla ice cream": 80}),
    ("Add-ons", "Extra whipped cream", 6, True, {"Whipped cream": 40}),
    ("Add-ons", "Pistachio drizzle", 10, True, {"Pistachio cream": 30}),
]


def seed(db: Session, history_days: int = 14) -> None:
    if db.scalar(select(Supplier).limit(1)):
        return
    suppliers = {name: Supplier(name=name, email=email, lead_days=lead) for name, email, lead in SUPPLIERS}
    db.add_all(suppliers.values())
    ingredients = {}
    for name, unit, cost, mn, par, opening, sup in INGREDIENTS:
        ing = Ingredient(name=name, unit=unit, unit_cost=cost, min_level=mn, par_level=par, on_hand=opening, supplier=suppliers[sup])
        ingredients[name] = ing
    db.add_all(ingredients.values())
    db.flush()
    for ing in ingredients.values():
        db.add(StockMove(ingredient_id=ing.id, qty=ing.on_hand, kind="opening"))
    items = []
    for cat, name, price, addon, recipe in MENU:
        item = MenuItem(name=name, category=cat, price=price, is_addon=addon)
        item.recipe = [RecipeLine(ingredient=ingredients[i], qty=q) for i, q in recipe.items()]
        items.append(item)
    db.add_all(items)
    db.flush()
    _seed_history(db, items, history_days)
    db.commit()


def _seed_history(db: Session, items: list[MenuItem], days: int) -> None:
    """Past orders before the opening stock count. They teach the agents what sells together
    and how fast ingredients are used; they do not change today's stock."""
    rng = random.Random(7)
    mains = [i for i in items if i.category in ("Crepes", "Waffles", "Pancakes")]
    drinks = [i for i in items if i.category == "Drinks"]
    addons = [i for i in items if i.is_addon]
    today = dt.date.today()
    for d in range(days, 0, -1):
        day = today - dt.timedelta(days=d)
        for _ in range(rng.randint(35, 55)):
            lines = [rng.choice(mains)]
            if rng.random() < 0.55:
                lines.append(rng.choice(drinks[1:4]) if lines[0].category == "Crepes" else rng.choice(drinks))
            if rng.random() < 0.3:
                lines.append(addons[0] if lines[0].category != "Drinks" else rng.choice(addons))
            order = Order(business_date=day, source="history", total=sum(i.price for i in lines))
            order.lines = [OrderLine(menu_item_id=i.id, qty=1, price=i.price) for i in lines]
            db.add(order)
