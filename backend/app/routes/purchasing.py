"""Routes: suppliers, supplier orders and deliveries."""
import datetime as dt
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from .. import finance, mailer, stock
from ..email_template import HEADER_CID, order_email_html
from ..agents import invoice, stock_memory
from ..agents.stock_agent import split_change
from ..models import Ingredient, Outbox, PurchaseOrder, PurchaseOrderLine, StockMove, Supplier
from ..seed import STORE_UTC_OFFSET
from ..schemas import SupplierIn, Receive, EditLine


def register(app, c):
    settings, llm, get_db, manager_only = c.settings, c.llm, c.get_db, c.manager_only

    # ---- suppliers ------------------------------------------------------------------
    def supplier_dict(sup: Supplier) -> dict:
        db_ings = object_session(sup).scalars(select(Ingredient).where(Ingredient.supplier_id == sup.id).order_by(Ingredient.name))
        return {"id": sup.id, "name": sup.name, "channel": sup.channel, "email": sup.email, "phone": sup.phone,
                "lead_days": sup.lead_days, "ingredients": [{"id": i.id, "name": i.name} for i in db_ings]}

    @app.get("/api/suppliers")
    def suppliers(db: Session = Depends(get_db), _=Depends(manager_only)):
        return {"suppliers": [supplier_dict(x) for x in db.scalars(select(Supplier).where(Supplier.active).order_by(Supplier.name))],
                "ingredients": [{"id": i.id, "name": i.name, "supplier_id": i.supplier_id}
                                for i in db.scalars(select(Ingredient).order_by(Ingredient.name))]}

    def save_supplier(db: Session, sup: Supplier, body: SupplierIn) -> dict:
        email = (body.email or "").strip() or None
        phone = "".join(ch for ch in (body.phone or "") if ch.isdigit()) or None
        if body.channel == "email" and not email:
            raise HTTPException(400, "Add the email address orders go to")
        if body.channel == "whatsapp" and not phone:
            raise HTTPException(400, "Add the WhatsApp number orders go to")
        clash = db.scalar(select(Supplier).where(func.lower(Supplier.name) == body.name.strip().lower(), Supplier.id != (sup.id or 0), Supplier.active))
        if clash:
            raise HTTPException(409, "A supplier with this name already exists")
        sup.name, sup.channel, sup.email, sup.phone, sup.lead_days = body.name.strip(), body.channel, email, phone, body.lead_days
        if not sup.id:
            db.add(sup)
            db.flush()
        mine = set(body.ingredient_ids)
        for ing in db.scalars(select(Ingredient)):
            if ing.id in mine:
                ing.supplier_id = sup.id  # each ingredient has one supplier: ticking it here moves it
            elif ing.supplier_id == sup.id:
                raise HTTPException(400, f"{ing.name} needs a supplier. Tick it on another supplier to move it there.")
        db.commit()
        return supplier_dict(sup)

    @app.post("/api/suppliers")
    def add_supplier(body: SupplierIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        return save_supplier(db, Supplier(), body)

    @app.put("/api/suppliers/{supplier_id}")
    def edit_supplier(supplier_id: int, body: SupplierIn, db: Session = Depends(get_db), _=Depends(manager_only)):
        sup = db.get(Supplier, supplier_id)
        if not sup:
            raise HTTPException(404, "Supplier not found")
        return save_supplier(db, sup, body)

    @app.delete("/api/suppliers/{supplier_id}")
    def remove_supplier(supplier_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        sup = db.get(Supplier, supplier_id)
        if not sup:
            raise HTTPException(404, "Supplier not found")
        if db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status == "sent")):
            raise HTTPException(409, "An order from this supplier is on the way. Receive it first.")
        if db.scalar(select(func.count(Ingredient.id)).where(Ingredient.supplier_id == sup.id)):
            raise HTTPException(409, "Move this supplier's ingredients to another supplier first.")
        for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status == "draft")):
            po.status = "rejected"
        # past orders keep pointing at the supplier, so one with history is hidden instead of deleted
        if db.scalar(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.supplier_id == sup.id)):
            sup.active = False
            sup.name = f"{sup.name} (removed {sup.id})"  # frees the name for a new supplier
        else:
            db.delete(sup)
        db.commit()
        return {"removed": supplier_id}

    # ---- purchase orders -------------------------------------------------------
    def order_text(po: PurchaseOrder) -> str:
        return "\n".join([f"Hello {po.supplier.name},", "", f"Please deliver the following to {settings.store_name}:", ""]
                         + [f"- {l.ingredient.name}: {l.qty:g} {l.ingredient.unit}" for l in po.lines]
                         + ["", f"Purchase order #{po.id}. Thank you.", settings.store_name])

    def whatsapp_number(po: PurchaseOrder) -> str | None:
        return settings.demo_supplier_whatsapp or po.supplier.phone or None

    def via(po: PurchaseOrder) -> str:
        return po.sent_via or po.supplier.channel

    def whatsapp_link(po: PurchaseOrder) -> str | None:
        """Click-to-chat link with the order typed in; the manager presses send in WhatsApp."""
        number = whatsapp_number(po)
        if via(po) != "whatsapp" or not number:
            return None
        return f"https://wa.me/{''.join(c for c in number if c.isdigit())}?text={quote(order_text(po))}"

    def order_html(po: PurchaseOrder) -> str:
        sent = po.sent_at or dt.datetime.now(dt.UTC).replace(tzinfo=None)
        deliver_by = (sent + dt.timedelta(days=po.supplier.lead_days)).date()
        return order_email_html(store=settings.store_name, supplier=po.supplier.name, po_id=po.id,
                                lines=[(l.ingredient.name, l.qty, l.ingredient.unit) for l in po.lines],
                                deliver_by=deliver_by, sent_at=sent + STORE_UTC_OFFSET)

    def po_ref(po: PurchaseOrder) -> str:
        return f"PO {po.id}"

    def po_delivery(po: PurchaseOrder) -> dict | None:
        """What arrived for a received order, from its stock moves."""
        if po.status != "received":
            return None
        moves = object_session(po).scalars(select(StockMove).where(
            StockMove.kind == "delivery", (StockMove.ref == po_ref(po)) | StockMove.ref.startswith(po_ref(po) + " · "))).all()
        if not moves:
            return {"at": None, "lines": []}
        names = {l.ingredient_id: (l.ingredient.name, l.ingredient.unit) for l in po.lines}
        return {"at": max(m.at for m in moves).isoformat(),
                "lines": [{"ingredient_id": m.ingredient_id, "ingredient": names.get(m.ingredient_id, ("", ""))[0],
                           "unit": names.get(m.ingredient_id, ("", ""))[1], "qty": m.qty} for m in moves]}

    def po_dict(po: PurchaseOrder) -> dict:
        expected = (po.sent_at + dt.timedelta(days=po.supplier.lead_days)).date().isoformat() if po.sent_at else None
        return {"id": po.id, "supplier": po.supplier.name, "status": po.status, "note": po.note,
                "expected": expected, "delivery": po_delivery(po),
                "channel": via(po), "supplier_email": settings.demo_supplier_email or po.supplier.email, "supplier_whatsapp": whatsapp_number(po),
                "whatsapp_link": whatsapp_link(po) if po.status == "sent" else None,
                "created_at": po.created_at.isoformat(), "sent_at": po.sent_at.isoformat() if po.sent_at else None,
                "lead_days": po.supplier.lead_days, "changed": any(split_change(l.reason)[1] for l in po.lines),
                "lines": [{"id": l.id, "ingredient_id": l.ingredient_id, "ingredient": l.ingredient.name,
                           "unit": l.ingredient.unit, "qty": l.qty, "reason": split_change(l.reason)[0],
                           "change": split_change(l.reason)[1], "drafted_qty": l.drafted_qty,
                           # a waiting lesson about this ingredient, shown beside the line for the manager to use or not
                           "suggestion": stock_memory.line_suggestion(object_session(po), l.ingredient, l.qty) if po.status == "draft" else None,
                           "est_cost": round(l.qty * l.ingredient.unit_cost, 2)} for l in po.lines]}

    def get_po(db: Session, po_id: int) -> PurchaseOrder:
        po = db.get(PurchaseOrder, po_id)
        if not po:
            raise HTTPException(404, "Purchase order not found")
        return po

    @app.get("/api/purchase-orders")
    def list_pos(db: Session = Depends(get_db), _=Depends(manager_only)):
        return [po_dict(po) for po in db.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()))]

    @app.post("/api/purchase-orders/{po_id}/approve")
    def approve(po_id: int, edits: list[EditLine] | None = None, via_: str | None = Query(None, alias="via", pattern="^(email|whatsapp)$"),
                db: Session = Depends(get_db), _=Depends(manager_only)):
        """Approve a draft and send it the way the manager picked (email or WhatsApp); without a pick, the
        supplier's usual way."""
        po = get_po(db, po_id)
        if po.status != "draft":
            raise HTTPException(409, f"Order is already {po.status}")
        channel = via_ or po.supplier.channel
        if channel == "whatsapp" and not whatsapp_number(po):
            raise HTTPException(400, f"{po.supplier.name} has no WhatsApp number. Add one under More › Suppliers, or send by email.")
        if channel == "email" and not (settings.demo_supplier_email or po.supplier.email):
            raise HTTPException(400, f"{po.supplier.name} has no email address. Add one under More › Suppliers, or send on WhatsApp.")
        for e in edits or []:
            line = db.get(PurchaseOrderLine, e.line_id)
            if not line or line.purchase_order_id != po.id:
                raise HTTPException(400, f"Line {e.line_id} is not on this order")
            if e.qty == 0:
                db.delete(line)
            else:
                line.qty = e.qty
        db.flush()
        db.refresh(po)
        if not po.lines:
            raise HTTPException(400, "Order has no lines left")
        po.status, po.sent_at, po.sent_via = "sent", dt.datetime.now(dt.UTC).replace(tzinfo=None), channel
        if channel == "whatsapp":
            to = whatsapp_number(po) or ""
            db.add(Outbox(to=f"WhatsApp +{to}", subject=f"Purchase order #{po.id} from {settings.store_name}", body=order_text(po), status="link"))
            db.commit()
            return po_dict(po) | {"email": None}
        mail = mailer.send(db, settings, po.supplier.email or "", f"Purchase order #{po.id} from {settings.store_name}",
                           order_text(po), order_html(po))
        db.commit()
        return po_dict(po) | {"email": {"id": mail.id, "to": mail.to, "status": mail.status, "error": mail.error}}

    @app.post("/api/purchase-orders/{po_id}/reject")
    def reject(po_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        po = get_po(db, po_id)
        if po.status != "draft":
            raise HTTPException(409, f"Order is already {po.status}")
        po.status = "rejected"
        db.commit()
        return po_dict(po)

    @app.post("/api/purchase-orders/{po_id}/receive")
    def receive_po(po_id: int, body: Receive, db: Session = Depends(get_db), _=Depends(manager_only)):
        po = get_po(db, po_id)
        if po.status != "sent":
            raise HTTPException(409, "Only sent orders can be received")
        for l in body.lines:
            stock.receive(db, l.ingredient_id, l.qty, ref=po_ref(po) + (f" · {body.invoice_ref[:40]}" if body.invoice_ref else ""))
        finance.record_purchase(db, [(l.ingredient_id, l.qty) for l in body.lines], f"{po.supplier.name} · {body.invoice_ref or po_ref(po)}")
        po.status, po.received_at = "received", dt.datetime.now(dt.UTC).replace(tzinfo=None)
        db.commit()
        return po_dict(po)

    @app.post("/api/deliveries")
    def manual_delivery(body: Receive, db: Session = Depends(get_db), _=Depends(manager_only)):
        for l in body.lines:
            if not db.get(Ingredient, l.ingredient_id):
                raise HTTPException(404, f"Ingredient {l.ingredient_id} not found")
            stock.receive(db, l.ingredient_id, l.qty, ref=body.invoice_ref or "manual delivery")
        finance.record_purchase(db, [(l.ingredient_id, l.qty) for l in body.lines], body.invoice_ref or "Manual delivery")
        db.commit()
        return {"received": len(body.lines)}

    @app.post("/api/invoices/read")
    async def read_invoice(file: UploadFile, db: Session = Depends(get_db), _=Depends(manager_only)):
        if not llm.enabled:
            raise HTTPException(503, "Reading invoice photos needs the AI key. Enter the delivery manually instead.")
        if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
            raise HTTPException(415, "Upload a JPEG, PNG, WebP or GIF photo")
        out = invoice.read(db, llm, await file.read(), file.content_type)
        if out is None:
            raise HTTPException(502, "The invoice could not be read. Enter the delivery manually instead.")
        return out

    @app.get("/api/outbox/{mail_id}/html", response_class=HTMLResponse)
    def outbox_html(mail_id: int, db: Session = Depends(get_db), _=Depends(manager_only)):
        """The branded email as the supplier sees it, with the inline logo pointed at the app's copy."""
        mail = db.get(Outbox, mail_id)
        if not mail or not mail.html:
            raise HTTPException(404, "No branded version of this email")
        return mail.html.replace(f"cid:{HEADER_CID}", "/static/email-header.png")

    @app.get("/api/outbox")
    def outbox(db: Session = Depends(get_db), _=Depends(manager_only)):
        return [{"id": m.id, "at": m.created_at.isoformat(), "to": m.to, "subject": m.subject, "body": m.body,
                 "status": m.status, "error": m.error} for m in db.scalars(select(Outbox).order_by(Outbox.id.desc()))]
