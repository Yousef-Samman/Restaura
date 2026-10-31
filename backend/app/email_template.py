"""The supplier order email: a branded HTML version (logo, Restaura colours) with the plain text kept as a fallback.

Email clients ignore most CSS, so the layout is tables with inline styles, and the logo travels as an inline
image attachment (cid:restaura-header) instead of a link, so it shows without loading remote images."""
import datetime as dt
from html import escape

HEADER_CID = "restaura-header"

PAGE, CARD, LINE, CLOUD = "#FAF9F2", "#FFFFFF", "#E6E1CC", "#F3F1E4"
INK, MUTED, OLIVE, BRASS, BRASS_TEXT, BRASS_TINT = "#2E3A1C", "#5F6B60", "#4F6230", "#B8923F", "#8A6A22", "#FBF4E4"
FONT = "'Helvetica Neue',Helvetica,Arial,sans-serif"


def _qty(q: float) -> str:
    return f"{q:g}"


def order_email_html(*, store: str, supplier: str, po_id: int, lines: list[tuple[str, float, str]],
                     deliver_by: dt.date | None, sent_at: dt.datetime) -> str:
    """lines: (ingredient, qty, unit). sent_at is in store time."""
    rows = "".join(
        f'<tr><td style="padding:12px 16px;border-top:1px solid {LINE};font:15px {FONT};color:{INK}">{escape(name)}</td>'
        f'<td align="right" style="padding:12px 16px;border-top:1px solid {LINE};font:bold 15px {FONT};color:{INK};white-space:nowrap">'
        f'{_qty(qty)} <span style="font-weight:normal;color:{MUTED}">{escape(unit)}</span></td></tr>'
        for name, qty, unit in lines)
    deliver = deliver_by.strftime("%a %-d %b") if deliver_by else "As soon as you can"
    facts = "".join(
        f'<td width="33%" style="padding:12px;background:{CLOUD};border-radius:10px;font:12px {FONT};color:{MUTED}">'
        f'{k}<br><b style="font-size:15px;color:{INK}">{v}</b></td>{"<td width=8></td>" if i < 2 else ""}'
        for i, (k, v) in enumerate([("Order", f"#{po_id}"), ("Items", str(len(lines))), ("Deliver by", deliver)]))
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Purchase order #{po_id}</title></head>
<body style="margin:0;padding:0;background:{PAGE}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE}"><tr><td align="center" style="padding:28px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
  <tr><td style="background:{CARD};border:1px solid {LINE};border-radius:18px;overflow:hidden">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="height:5px;background:{BRASS};font-size:0;line-height:0">&nbsp;</td></tr>
      <tr><td style="padding:22px 28px 18px;border-bottom:1px solid {LINE}"><img src="cid:{HEADER_CID}" width="196" height="53" alt="RESTAURA" style="display:block;border:0"></td></tr>
      <tr><td style="padding:22px 28px 8px">
        <div style="font:bold 12px {FONT};letter-spacing:.12em;text-transform:uppercase;color:{BRASS_TEXT}">Purchase order</div>
        <div style="font:bold 24px {FONT};color:{INK};padding-top:6px">Order #{po_id} from {escape(store)}</div>
        <div style="font:15px/1.5 {FONT};color:{MUTED};padding-top:10px">Hello {escape(supplier)}, please deliver the items below. Thank you.</div>
      </td></tr>
      <tr><td style="padding:16px 28px 6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{facts}</tr></table></td></tr>
      <tr><td style="padding:16px 28px 6px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {LINE};border-radius:12px;border-collapse:separate">
          <tr><td style="padding:10px 16px;font:bold 12px {FONT};letter-spacing:.06em;text-transform:uppercase;color:{MUTED}">Item</td>
              <td align="right" style="padding:10px 16px;font:bold 12px {FONT};letter-spacing:.06em;text-transform:uppercase;color:{MUTED}">Quantity</td></tr>
          {rows}
        </table>
      </td></tr>
      <tr><td style="padding:18px 28px 26px">
        <div style="background:{BRASS_TINT};border-radius:12px;padding:14px 16px;font:14px/1.5 {FONT};color:{INK}">
          Please reply to this email to confirm the delivery day, or to tell us if anything is out of stock.</div>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:18px 8px 0;font:12px/1.6 {FONT};color:{MUTED}" align="center">
    Sent {sent_at.strftime("%-d %b %Y, %H:%M")} by {escape(store)} · Prepared by the Restaura stock agent and approved by the manager<br>
    <span style="color:{OLIVE};font-weight:bold;letter-spacing:.14em">RESTAURA</span> · AI agents for the restaurant.
  </td></tr>
</table></td></tr></table></body></html>"""
