import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .config import Settings
from .models import Outbox


def send(db: Session, settings: Settings, to: str, subject: str, body: str) -> Outbox:
    to = settings.demo_supplier_email or to
    rec = Outbox(to=to, subject=subject, body=body, status="logged")
    if settings.smtp_host:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
                if settings.smtp_user:
                    s.starttls()
                    s.login(settings.smtp_user, settings.smtp_password or "")
                s.send_message(msg)
            rec.status = "sent"
        except Exception as exc:  # the order stays approved; the manager sees the failure
            rec.status, rec.error = "failed", str(exc)
    db.add(rec)
    return rec
