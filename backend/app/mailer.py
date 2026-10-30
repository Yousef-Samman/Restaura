import smtplib
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy.orm import Session

from .config import Settings
from .email_template import HEADER_CID
from .models import Outbox

HEADER_PNG = Path(__file__).parent / "static" / "email-header.png"


def send(db: Session, settings: Settings, to: str, subject: str, body: str, html: str | None = None) -> Outbox:
    """Send one email, or log it when no mail server is set. The plain text always goes along as the fallback;
    with html, the logo travels as an inline image so it shows without loading remote images."""
    to = settings.demo_supplier_email or to
    rec = Outbox(to=to, subject=subject, body=body, html=html, status="logged")
    if settings.smtp_host:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
            msg.get_payload()[1].add_related(HEADER_PNG.read_bytes(), "image", "png", cid=f"<{HEADER_CID}>")
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
