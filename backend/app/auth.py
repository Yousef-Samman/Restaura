"""Accounts, sessions and cashier device pairing.

Managers sign in from any device. Cashiers sign in only on a device the manager has paired
as a cashier station (the store's iPad): pairing stores a long-lived device token in a cookie."""
import datetime as dt
import hashlib
import hmac
import os
import secrets

from fastapi import Cookie, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthSession, Device, StaffMember, User, now

SESSION_COOKIE, DEVICE_COOKIE = "restaura_session", "restaura_device"
SESSION_HOURS = 12
PAIRING_MINUTES = 10


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _ = stored.split("$", 1)
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)), stored)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def seed_users(db: Session, manager_password: str, cashier_password: str) -> None:
    if db.scalar(select(User).limit(1)):
        return
    db.add_all([
        User(username="manager", name="Store manager", role="manager", password_hash=hash_password(manager_password)),
        User(username="cashier", name="Cashier", role="cashier", password_hash=hash_password(cashier_password)),
    ])
    db.commit()


def device_from_cookie(db: Session, device_token: str | None) -> Device | None:
    if not device_token:
        return None
    dev = db.scalar(select(Device).where(Device.token_hash == _h(device_token)))
    return dev if dev and not dev.revoked else None


def login(db: Session, username: str, password: str, device_token: str | None) -> tuple[str, User]:
    user = db.scalar(select(User).where(User.username == username.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Wrong username or password")
    device = device_from_cookie(db, device_token)
    if user.role == "cashier" and not device:
        raise HTTPException(403, "Cashier accounts can only sign in on the store's paired cashier iPad.")
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_h(token), user_id=user.id, device_id=device.id if device else None,
                       expires=now() + dt.timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token, user


def staff_login(db: Session, staff_id: int, pin: str, device_token: str | None) -> tuple[str, User]:
    """A staff member signs in on the paired cashier iPad with their own 4-digit PIN, so the app
    knows who is working (checklists, orders). Each staff member gets their own cashier account."""
    device = device_from_cookie(db, device_token)
    if not device:
        raise HTTPException(403, "Staff can only sign in on the store's paired cashier iPad.")
    member = db.get(StaffMember, staff_id)
    if not member or not member.active or not verify_password(pin, member.pin_hash):
        raise HTTPException(401, "Wrong PIN")
    username = f"staff-{member.id}"
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        # no password sign-in for these accounts: the PIN on the paired iPad is the only way in
        user = User(username=username, name=member.name, role="cashier", password_hash=hash_password(secrets.token_urlsafe(24)))
        db.add(user)
        db.flush()
    user.name = member.name
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_h(token), user_id=user.id, device_id=device.id, expires=now() + dt.timedelta(hours=SESSION_HOURS)))
    db.commit()
    return token, user


def logout(db: Session, token: str | None) -> None:
    if token and (s := db.get(AuthSession, _h(token))):
        db.delete(s)
        db.commit()


def current_user(db: Session, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = db.get(AuthSession, _h(token))
    if not s or s.expires < now():
        return None
    if s.user.role == "cashier":
        # a cashier session stays valid only while the device is still paired
        if not s.device_id or not device_from_cookie(db, request.cookies.get(DEVICE_COOKIE)):
            return None
    return s.user


def start_pairing(db: Session, name: str) -> Device:
    dev = Device(name=name, pairing_code=f"{secrets.randbelow(1_000_000):06d}",
                 pairing_expires=now() + dt.timedelta(minutes=PAIRING_MINUTES))
    db.add(dev)
    db.commit()
    return dev


def complete_pairing(db: Session, code: str) -> tuple[str, Device]:
    dev = db.scalar(select(Device).where(Device.pairing_code == code.strip(), Device.token_hash.is_(None)))
    if not dev or dev.revoked or dev.pairing_expires < now():
        raise HTTPException(400, "This pairing code is wrong or has expired. Ask the manager for a new one.")
    token = secrets.token_urlsafe(32)
    dev.token_hash, dev.pairing_code, dev.paired_at = _h(token), None, now()
    db.commit()
    return token, dev
