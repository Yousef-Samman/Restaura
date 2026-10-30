"""Sample data for the demo. Names, prices and recipes are illustrative, not a real store's records."""
import datetime as dt
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attendance, Expense, Ingredient, RoutineCheck, RoutineTask, Shift, StaffMember, MenuItem, Order, OrderLine, RecipeLine, StockMove, SuggestionEvent, Supplier

SUPPLIERS = [
    ("Fresh Produce Co.", "orders@fresh-produce.example", 1),  # orders go by WhatsApp, see WHATSAPP below
    ("Dairy Farms Co.", "orders@dairy-farms.example", 1),
    ("Pantry Wholesale", "orders@pantry-wholesale.example", 2),
    ("Frozen Treats Co.", "orders@frozen-treats.example", 2),
]

# suppliers that take orders on WhatsApp; the number is a placeholder, not a real business
WHATSAPP = {"Fresh Produce Co.": "966500000000"}

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


def seed(db: Session, history_days: int = 30) -> None:
    if db.scalar(select(Supplier).limit(1)):
        return
    suppliers = {name: Supplier(name=name, email=email, lead_days=lead) for name, email, lead in SUPPLIERS}
    for name, phone in WHATSAPP.items():
        suppliers[name].channel, suppliers[name].phone = "whatsapp", phone
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
    _seed_expenses(db)
    _seed_routines(db)
    _seed_staff(db)
    db.commit()


# sample buying habits: the drinks and add-ons each dessert is usually ordered with (illustrative)
PAIRINGS = {
    "Hazelnut crepe": (("Spanish latte", "Hot chocolate"), ("Extra whipped cream",)),
    "Triple chocolate crepe": (("Americano", "Latte"), ("Scoop of vanilla ice cream",)),
    "Strawberry crepe": (("Iced latte", "Latte"), ("Extra whipped cream",)),
    "Banana crepe": (("Spanish latte",), ("Scoop of vanilla ice cream", "Extra whipped cream")),
    "Pistachio kunafa crepe": (("Americano", "Spanish latte"), ("Pistachio drizzle",)),
    "Classic chocolate waffle": (("Iced latte", "Latte"), ("Scoop of vanilla ice cream",)),
    "Strawberry waffle": (("Iced latte",), ("Extra whipped cream", "Scoop of vanilla ice cream")),
    "Mini pancakes": (("Hot chocolate",), ("Extra whipped cream",)),
}


def _seed_history(db: Session, items: list[MenuItem], days: int) -> None:
    """Past orders before the opening stock count. They teach the agents what sells together
    and how fast ingredients are used; they do not change today's stock."""
    rng = random.Random(7)
    mains = [i for i in items if i.category in ("Crepes", "Waffles", "Pancakes")]
    drinks = [i for i in items if i.category == "Drinks"]
    addons = [i for i in items if i.is_addon]
    today = dt.date.today()
    orders = []
    by_name = {i.name: i for i in items}
    for d in range(days, 0, -1):
        day = today - dt.timedelta(days=d)
        for _ in range(rng.randint(35, 55)):
            main = rng.choice(mains)
            lines = [main]
            usual_drinks, usual_addons = PAIRINGS.get(main.name, ((), ()))
            # most customers take the drink and add-on that usually go with their dessert; some pick anything
            if rng.random() < 0.55:
                lines.append(by_name[rng.choice(usual_drinks)] if usual_drinks and rng.random() < 0.75 else rng.choice(drinks))
            if rng.random() < 0.3:
                lines.append(by_name[rng.choice(usual_addons)] if usual_addons and rng.random() < 0.75 else rng.choice(addons))
            order = Order(business_date=day, source="history", total=sum(i.price for i in lines))
            order.lines = [OrderLine(menu_item_id=i.id, qty=1, price=i.price) for i in lines]
            db.add(order)
            orders.append(order)
    _seed_times_and_helper(db, orders, addons)


# busier in the afternoon and evening; store time is UTC+3 (Saudi Arabia), timestamps are stored in UTC
HOUR_WEIGHTS = {10: 2, 11: 3, 12: 4, 13: 5, 14: 5, 15: 6, 16: 8, 17: 9, 18: 10, 19: 11, 20: 12, 21: 11, 22: 8, 23: 5}
STORE_UTC_OFFSET = dt.timedelta(hours=3)


def _seed_times_and_helper(db: Session, orders: list[Order], addons: list[MenuItem]) -> None:
    """Sample order times, and sample cashier-helper history: which add-ons were suggested and which
    were added because of a suggestion. A separate random stream keeps the orders themselves unchanged."""
    rng = random.Random(19)
    db.flush()
    hours, weights = list(HOUR_WEIGHTS), list(HOUR_WEIGHTS.values())
    addon_ids = {a.id for a in addons}
    for order in orders:
        local = dt.datetime.combine(order.business_date, dt.time(rng.choices(hours, weights)[0], rng.randrange(60)))
        order.created_at = local - STORE_UTC_OFFSET
        added = next((l for l in order.lines if l.menu_item_id in addon_ids), None)
        if added and rng.random() < 0.6:
            added.from_suggestion = True
            db.add(SuggestionEvent(created_at=order.created_at, menu_item_id=added.menu_item_id, source="rules",
                                   accepted=True, order_id=order.id))
        elif rng.random() < 0.7:
            db.add(SuggestionEvent(created_at=order.created_at, menu_item_id=rng.choice(addons).id, source="rules"))


# sample monthly costs and one-off payments (SAR); illustrative only
FIXED = [("Rent", 12000, "Shop rent"), ("Salaries", 21000, "5 staff"), ("Utilities", 2200, "Power, water, internet")]
ONE_OFF = [(26, "Packaging", 850, "Cups, boxes, bags"), (21, "Maintenance", 400, "Waffle maker repair"),
           (15, "Marketing", 1200, "Social media ads"), (9, "Cleaning", 380, "Cleaning supplies"), (3, "Packaging", 620, "Cups and lids")]


def _seed_expenses(db: Session) -> None:
    today = dt.date.today()
    db.add_all(Expense(date=today.replace(day=1), kind="fixed", category=c, amount=a, note=n) for c, a, n in FIXED)
    db.add_all(Expense(date=today - dt.timedelta(days=d), kind="one_off", category=c, amount=a, note=n) for d, c, a, n in ONE_OFF)


# sample checklists
TASKS = {
    "opening": ["Turn on the crepe and waffle machines", "Check fridge and freezer temperatures", "Prepare crepe and waffle batter",
                "Fill the toppings station", "Count the cash float", "Clean tables and counter"],
    "midday": ["Restock cups, lids and boxes", "Clean the toppings station", "Check batter and refill if needed", "Empty the bins"],
    "closing": ["Clean the machines", "Store toppings in the fridge", "Count the cash and close the till", "Mop the floor",
                "Turn off machines and lights"],
}
STAFF_NAMES = ["Sara", "Omar", "Lina", "Faisal", "Huda"]


def _seed_routines(db: Session) -> None:
    rng = random.Random(11)
    tasks = [RoutineTask(routine=r, text=t, position=i) for r, ts in TASKS.items() for i, t in enumerate(ts)]
    db.add_all(tasks)
    db.flush()
    today = dt.date.today()
    for d in range(14, 0, -1):
        day = today - dt.timedelta(days=d)
        for t in tasks:
            if rng.random() < (0.97 if t.routine == "opening" else 0.85 if t.routine == "midday" else 0.9):
                hour = {"opening": 10, "midday": 16, "closing": 23}[t.routine]
                db.add(RoutineCheck(date=day, task_id=t.id, done_by=rng.choice(STAFF_NAMES),
                                    done_at=dt.datetime.combine(day, dt.time(hour, rng.randint(0, 29)))))


# sample staff, PINs 1111..5555 for the demo; morning 10:00-17:00, evening 17:00-00:00
STAFF = [("Sara", "Shift lead", "1111"), ("Omar", "Crepe maker", "2222"), ("Lina", "Cashier", "3333"),
         ("Faisal", "Crepe maker", "4444"), ("Huda", "Cashier", "5555")]
MORNING, EVENING = (dt.time(10), dt.time(17)), (dt.time(17), dt.time(0))


def _seed_staff(db: Session) -> None:
    from .auth import hash_password
    rng = random.Random(5)
    members = [StaffMember(name=n, role=r, pin_hash=hash_password(p)) for n, r, p in STAFF]
    db.add_all(members)
    db.flush()
    today = dt.date.today()
    for d in range(-14, 7):
        day = today + dt.timedelta(days=d)
        off = members[(day.toordinal()) % len(members)]  # one person off each day, rotating
        working = [m for m in members if m is not off]
        for i, m in enumerate(working):
            start, end = MORNING if i % 2 == 0 else EVENING
            db.add(Shift(staff_id=m.id, date=day, start=start, end=end))
            if d < 0 and rng.random() > 0.04:  # past days: most people come, some late
                late = rng.choice([0, 0, 0, 0, 2, 5, 14, 22])
                cin = dt.datetime.combine(day, start) + dt.timedelta(minutes=late - 5)
                cout = dt.datetime.combine(day + dt.timedelta(days=1) if end < start else day, end) + dt.timedelta(minutes=rng.randint(0, 15))
                db.add(Attendance(staff_id=m.id, date=day, clock_in=cin, clock_out=cout))
            if d == 0 and dt.datetime.now() > dt.datetime.combine(day, start) and start < dt.time(12):  # today's morning shift is in
                db.add(Attendance(staff_id=m.id, date=day, clock_in=dt.datetime.combine(day, start) - dt.timedelta(minutes=4)))
