import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Supplier(Base):
    __tablename__ = "supplier"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    email: Mapped[str | None] = mapped_column(String(200))
    lead_days: Mapped[int] = mapped_column(Integer, default=1)
    channel: Mapped[str] = mapped_column(String(10), default="email")  # email | whatsapp
    phone: Mapped[str | None] = mapped_column(String(20))  # international format, digits only
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # removed suppliers with past orders are kept for the records


class Ingredient(Base):
    __tablename__ = "ingredient"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    unit: Mapped[str] = mapped_column(String(10))  # g, ml, pcs
    unit_cost: Mapped[float] = mapped_column(Float)  # SAR per unit
    min_level: Mapped[float] = mapped_column(Float)  # set by the manager
    par_level: Mapped[float] = mapped_column(Float)  # target level after a delivery
    on_hand: Mapped[float] = mapped_column(Float, default=0)
    # multiplies the code's order quantity; changed only when the manager applies something the stock agent learned
    order_factor: Mapped[float] = mapped_column(Float, default=1.0)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    supplier: Mapped[Supplier] = relationship()


class MenuItem(Base):
    __tablename__ = "menu_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    category: Mapped[str] = mapped_column(String(60))
    price: Mapped[float] = mapped_column(Float)
    is_addon: Mapped[bool] = mapped_column(Boolean, default=False)
    recipe: Mapped[list["RecipeLine"]] = relationship(back_populates="item", cascade="all, delete-orphan")


class RecipeLine(Base):
    __tablename__ = "recipe_line"
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_item.id"), primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"), primary_key=True)
    qty: Mapped[float] = mapped_column(Float)
    item: Mapped[MenuItem] = relationship(back_populates="recipe")
    ingredient: Mapped[Ingredient] = relationship()


class Order(Base):
    __tablename__ = "sale_order"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    business_date: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20))  # cashier | import | history
    total: Mapped[float] = mapped_column(Float, default=0)
    # who served it and how the bill went, for the Staff agent's coaching
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_member.id"))
    seconds_to_pay: Mapped[int | None] = mapped_column(Integer)  # first item tapped to paid
    removed_items: Mapped[int] = mapped_column(Integer, default=0)  # items taken off the bill before paying
    payment: Mapped[str | None] = mapped_column(String(10))  # card | cash | split
    lines: Mapped[list["OrderLine"]] = relationship(cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sale_order.id"))
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_item.id"))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    from_suggestion: Mapped[bool] = mapped_column(Boolean, default=False)
    item: Mapped[MenuItem] = relationship()


class SuggestionEvent(Base):
    """Every add-on the cashier helper shows, and whether it was sold."""
    __tablename__ = "suggestion_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_item.id"))
    source: Mapped[str] = mapped_column(String(10))  # ai | rules
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("sale_order.id"))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_member.id"))  # who offered it


class StockMove(Base):
    __tablename__ = "stock_move"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"))
    qty: Mapped[float] = mapped_column(Float)  # + in, - out
    kind: Mapped[str] = mapped_column(String(20))  # opening | sale | delivery | count
    ref: Mapped[str | None] = mapped_column(String(60))


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("supplier.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | received | rejected
    note: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    sent_via: Mapped[str | None] = mapped_column(String(10))  # email | whatsapp, picked by the manager when approving
    received_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_line"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_order.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredient.id"))
    qty: Mapped[float] = mapped_column(Float)
    drafted_qty: Mapped[float | None] = mapped_column(Float)  # what the agent drafted, before the manager's edits
    reason: Mapped[str | None] = mapped_column(Text)
    ingredient: Mapped[Ingredient] = relationship()


class Outbox(Base):
    """Emails the app sent, or logged when no mail server is configured."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    to: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # sent | logged | failed
    error: Mapped[str | None] = mapped_column(Text)
    html: Mapped[str | None] = mapped_column(Text)  # the branded version, when there is one


class AgentRun(Base):
    __tablename__ = "agent_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    agent: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(10))  # ai | rules
    summary: Mapped[str] = mapped_column(Text)


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))  # cashier | manager
    password_hash: Mapped[str] = mapped_column(String(200))


class Device(Base):
    """A device the manager has paired as a cashier station. Cashiers can only sign in on one of these."""
    __tablename__ = "device"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str | None] = mapped_column(String(100), unique=True)
    pairing_code: Mapped[str | None] = mapped_column(String(10))
    pairing_expires: Mapped[dt.datetime | None] = mapped_column(DateTime)
    paired_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AuthSession(Base):
    __tablename__ = "auth_session"
    token_hash: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("device.id"))
    expires: Mapped[dt.datetime] = mapped_column(DateTime)
    user: Mapped[User] = relationship()


class Expense(Base):
    """Money going out. fixed: a monthly cost such as rent, spread evenly over the days of a period.
    one_off: a dated payment. purchase: a supplier delivery, recorded automatically at cost."""
    __tablename__ = "expense"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    date: Mapped[dt.date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(10))  # fixed | one_off | purchase
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Float)  # SAR; for fixed, per month
    note: Mapped[str | None] = mapped_column(String(200))


class RoutineTask(Base):
    """One task on a daily checklist (opening, midday or closing)."""
    __tablename__ = "routine_task"
    id: Mapped[int] = mapped_column(primary_key=True)
    routine: Mapped[str] = mapped_column(String(10))  # opening | midday | closing
    text: Mapped[str] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoutineCheck(Base):
    """A task ticked off on a given business day."""
    __tablename__ = "routine_check"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    task_id: Mapped[int] = mapped_column(ForeignKey("routine_task.id"))
    done_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    done_by: Mapped[str | None] = mapped_column(String(120))


class StaffMember(Base):
    __tablename__ = "staff_member"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60))
    pin_hash: Mapped[str] = mapped_column(String(200))  # 4-digit PIN for clocking in on the cashier iPad
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Shift(Base):
    """A planned shift. end may be past midnight (end < start)."""
    __tablename__ = "shift"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_member.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    start: Mapped[dt.time] = mapped_column()
    end: Mapped[dt.time] = mapped_column()
    staff: Mapped[StaffMember] = relationship()


class Attendance(Base):
    __tablename__ = "attendance"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_member.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    clock_in: Mapped[dt.datetime] = mapped_column(DateTime)
    clock_out: Mapped[dt.datetime | None] = mapped_column(DateTime)
    staff: Mapped[StaffMember] = relationship()


class StaffReview(Base):
    """The manager's weekly review of one staff member: four 1-5 ratings and a note."""
    __tablename__ = "staff_review"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_member.id"))
    week_start: Mapped[dt.date] = mapped_column(Date)  # the Sunday the work week starts
    quality: Mapped[int] = mapped_column(Integer)
    speed: Mapped[int] = mapped_column(Integer)
    cleanliness: Mapped[int] = mapped_column(Integer)
    teamwork: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)


class StaffTip(Base):
    """One coaching tip the Staff agent gave a staff member, with the number it should move, so the next check can
    tell whether it worked."""
    __tablename__ = "staff_tip"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_member.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    tip: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)
    focus: Mapped[str] = mapped_column(String(40))  # the measure it targets, see agents/staff_agent.FOCUS
    baseline: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(10), default="rules")  # ai | rules
    seen_at: Mapped[dt.datetime | None] = mapped_column(DateTime)  # when the staff member tapped Got it
    staff: Mapped[StaffMember] = relationship()


class Lesson(Base):
    """Something an agent learned from what happened after it acted, as a suggestion the manager applies or not.
    Nothing changes until the manager applies it."""
    __tablename__ = "lesson"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(20))  # stock | forecast
    kind: Mapped[str] = mapped_column(String(20))  # order_size | lead_time | usage
    subject: Mapped[str] = mapped_column(String(40))  # ingredient:<id> | supplier:<id>
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    current: Mapped[float] = mapped_column(Float)  # the value in use when it was learned
    value: Mapped[float] = mapped_column(Float)  # the value it suggests
    evidence: Mapped[int] = mapped_column(Integer)  # how many orders, deliveries or counts it rests on
    status: Mapped[str] = mapped_column(String(12), default="suggested")  # suggested | applied | dismissed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime)


class SpecialDay(Base):
    """A day the manager tags as not normal (Eid, payday, a promotion, a closed day). The forecast keeps tagged days
    out of the normal pattern and learns each label's lift from the past tagged days."""
    __tablename__ = "special_day"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, unique=True)
    label: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=now)
