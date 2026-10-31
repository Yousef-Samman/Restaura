"""What the API accepts: one small model per request body."""
import datetime as dt

from pydantic import BaseModel, Field


class CartLine(BaseModel):
    item_id: int
    qty: int = Field(1, ge=1)
    suggestion_event_id: int | None = None


class Cart(BaseModel):
    lines: list[CartLine]
    # how the sale went, for the staff coach: seconds from the first item to payment, items taken off, how they paid
    seconds_to_pay: int | None = Field(None, ge=0, le=3600)
    removed_items: int = Field(0, ge=0, le=100)
    payment: str | None = Field(None, pattern="^(card|cash|split)$")


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: str = Field("email", pattern="^(email|whatsapp)$")
    email: str | None = Field(None, max_length=200, pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(None, max_length=20)
    lead_days: int = Field(1, ge=0, le=30)
    ingredient_ids: list[int] = []


class DataCheckIn(BaseModel):
    correct: bool  # True: the record is right, learn from it. False: it's a mistake, leave it out.
    label: str | None = Field(None, max_length=60)  # for a real sales day: tag it as a special day


class SpecialDayIn(BaseModel):
    date: dt.date
    label: str = Field(min_length=1, max_length=60)


class ReviewIn(BaseModel):
    quality: int = Field(ge=1, le=5)
    speed: int = Field(ge=1, le=5)
    cleanliness: int = Field(ge=1, le=5)
    teamwork: int = Field(ge=1, le=5)
    note: str | None = Field(None, max_length=200)


class ReceiveLine(BaseModel):
    ingredient_id: int
    qty: float = Field(gt=0)


class Receive(BaseModel):
    lines: list[ReceiveLine]
    invoice_ref: str | None = None


class ExpenseIn(BaseModel):
    kind: str = Field(pattern="^(fixed|one_off)$")
    category: str = Field(min_length=1, max_length=40)
    amount: float = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)
    date: dt.date | None = None


class ClockIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4}$")


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=60)
    pin: str = Field(pattern=r"^\d{4}$")


class ShiftIn(BaseModel):
    staff_id: int
    date: dt.date
    start: dt.time
    end: dt.time


class TaskToggle(BaseModel):
    done_by: str | None = Field(default=None, max_length=120)


class TaskIn(BaseModel):
    routine: str = Field(pattern="^(opening|midday|closing)$")
    text: str = Field(min_length=1, max_length=160)


class CountLine(BaseModel):
    ingredient_id: int
    counted: float = Field(ge=0)


class Login(BaseModel):
    username: str
    password: str


class StaffLogin(BaseModel):
    staff_id: int
    pin: str = Field(pattern=r"^\d{4}$")


class PairStart(BaseModel):
    name: str = Field("Cashier iPad", min_length=1, max_length=120)


class PairCode(BaseModel):
    code: str


class EditLine(BaseModel):
    line_id: int
    qty: float = Field(ge=0)
