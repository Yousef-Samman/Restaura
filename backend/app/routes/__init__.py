"""The API, one module per area. Each module has register(app, c), which adds its routes; `c` holds what they share."""
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI

from ..agents.llm import LLM
from ..config import Settings


@dataclass
class Ctx:
    settings: Settings
    llm: LLM
    Session_: Any  # the session factory
    get_db: Callable
    staff: Callable  # dependency: a signed-in cashier or manager
    manager_only: Callable  # dependency: a signed-in manager
    staff_id: Callable  # the staff member behind a cashier account
    cookie: dict
    guarded: Callable  # runs a sign-in or PIN attempt under the lockout
    who: Callable  # where a request comes from


def register_all(app: FastAPI, c: Ctx) -> None:
    from . import accounts, cashier, inventory, operations, people, purchasing, web
    for module in (accounts, cashier, people, operations, inventory, purchasing, web):
        module.register(app, c)
