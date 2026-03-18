# app/modules/fulfillment/emails.py
"""
Fulfillment email notifications — fulfillment@gridlineservice.com

Three triggers:
  - send_request_created()   — fires when a user submits a new request
  - send_request_hold()      — fires when a request is moved to Hold
  - send_request_completed() — fires when a request is marked Completed

All functions are fire-and-forget: they log on failure but never raise.
"""

import logging

from app.core.ses import send_email, SENDER_FULFILLMENT, user_wants_email, EMAIL_PREF_FULFILLMENT
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

_AUTO = "This message is automated, please do not reply to this email. For issues concerning your request or cancellations please create a support ticket."


def _get_user_info(user_id: int) -> dict:
    """Return email, first_name, last_name, username for a user."""
    try:
        with get_db_connection('core') as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email, first_name, last_name, username FROM users WHERE id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
                if row:
                    return dict(row)
    except Exception as exc:
        logger.warning(f"[fulfillment.emails] Could not look up info for user_id={user_id}: {exc}")
    return {}


def _name(first_name: str, last_name: str, username: str = '') -> str:
    """Return 'First, Last' or fall back to username."""
    first = (first_name or '').strip()
    last  = (last_name  or '').strip()
    if first and last:
        return f"{first}, {last}"
    if first:
        return first
    return username or 'User'


def _body(content: str, footer: str = _AUTO) -> str:
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;
            background:#ffffff;padding:32px 40px;color:#333333;font-size:14px;line-height:1.7;">
    {content}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px;">
    <p style="color:#9ca3af;font-size:12px;margin:0;">{footer}</p>
</div>
"""


# ── Public send functions ──────────────────────────────────────────────────────

def send_request_created(request_id: int, created_by_id: int, created_by_name: str,
                         description: str, date_due=None, notes: str | None = None) -> None:
    """Send a confirmation email when a new fulfillment request is submitted."""
    if not user_wants_email(created_by_id, EMAIL_PREF_FULFILLMENT):
        logger.info(f"[fulfillment.emails] user_id={created_by_id} opted out of fulfillment alerts — skipping created notice for request #{request_id}")
        return
    info = _get_user_info(created_by_id)
    email = (info.get('email') or '').strip()
    if not email:
        logger.info(f"[fulfillment.emails] No email for user_id={created_by_id} — skipping created notice for request #{request_id}")
        return

    to_name = _name(info.get('first_name', ''), info.get('last_name', ''), created_by_name)

    content = f"""
<p style="margin:0 0 16px;">To {to_name},</p>
<p style="margin:0 0 16px;">
    Thank you for your submission, a staff member will fulfill this request once they are
    available to do so. No further action is required at this time.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Team</p>
"""
    send_email(
        to=email,
        subject=f"Request {request_id} Confirmation",
        body_text=(
            f"To {to_name},\n\n"
            f"Thank you for your submission, a staff member will fulfill this request once they are available to do so. "
            f"No further action is required at this time.\n\n"
            f"With regards,\nGridline Team\n\n"
            f"P.S. {_AUTO}"
        ),
        body_html=_body(content, f"P.S. {_AUTO}"),
        sender=SENDER_FULFILLMENT,
    )


def send_request_hold(request_id: int, created_by_id: int, created_by_name: str,
                      description: str, notes: str | None = None) -> None:
    """Send a hold notification when a request is moved to Hold status."""
    if not user_wants_email(created_by_id, EMAIL_PREF_FULFILLMENT):
        logger.info(f"[fulfillment.emails] user_id={created_by_id} opted out of fulfillment alerts — skipping hold notice for request #{request_id}")
        return
    info = _get_user_info(created_by_id)
    email = (info.get('email') or '').strip()
    if not email:
        logger.info(f"[fulfillment.emails] No email for user_id={created_by_id} — skipping hold notice for request #{request_id}")
        return

    to_name  = _name(info.get('first_name', ''), info.get('last_name', ''), created_by_name)
    comment  = notes or 'No specific reason was provided.'
    sep      = '<hr style="border:none;border-top:1px solid #cccccc;margin:16px 0;">'

    content = f"""
<p style="margin:0 0 16px;">To {to_name},</p>
<p style="margin:0 0 16px;">
    We wanted to inform you that your request [{description} - {request_id}] was
    placed on hold for the reason(s) below:
</p>
{sep}
<p style="margin:0 0 16px;">{comment}</p>
{sep}
<p style="margin:0 0 16px;">At your earliest convenience, please resubmit a request with the noted corrections.</p>
<p style="margin:0 0 4px;">Sincerely,</p>
<p style="margin:0;">Gridline Team</p>
"""
    send_email(
        to=email,
        subject=f"Action Required: Request {request_id} Update",
        body_text=(
            f"To {to_name},\n\n"
            f"We wanted to inform you that your request [{description} - {request_id}] was placed on hold "
            f"for the reason(s) below:\n\n"
            f"{'—' * 50}\n{comment}\n{'—' * 50}\n\n"
            f"At your earliest convenience, please resubmit a request with the noted corrections.\n\n"
            f"Sincerely,\nGridline Team\n\n"
            f"{'—' * 50}\nThis is an automated message. Please do not reply."
        ),
        body_html=_body(content, "This is an automated message. Please do not reply."),
        sender=SENDER_FULFILLMENT,
    )


def send_request_completed(request_id: int, created_by_id: int, created_by_name: str,
                            description: str) -> None:
    """Send a completion notice when a request is marked Completed."""
    if not user_wants_email(created_by_id, EMAIL_PREF_FULFILLMENT):
        logger.info(f"[fulfillment.emails] user_id={created_by_id} opted out of fulfillment alerts — skipping completion notice for request #{request_id}")
        return
    info = _get_user_info(created_by_id)
    email = (info.get('email') or '').strip()
    if not email:
        logger.info(f"[fulfillment.emails] No email for user_id={created_by_id} — skipping completion notice for request #{request_id}")
        return

    to_name = _name(info.get('first_name', ''), info.get('last_name', ''), created_by_name)

    content = f"""
<p style="margin:0 0 16px;">To {to_name},</p>
<p style="margin:0 0 16px;">
    We are pleased to inform you that your request #{request_id} has been fully processed
    and completed.
</p>
<p style="margin:0 0 16px;">Thank you for using Gridline Service.</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Team</p>
"""
    send_email(
        to=email,
        subject=f"Request {request_id} Successfully Fulfilled",
        body_text=(
            f"To {to_name},\n\n"
            f"We are pleased to inform you that your request #{request_id} has been fully processed and completed.\n\n"
            f"Thank you for using Gridline Service.\n\n"
            f"With regards,\nGridline Team\n\n"
            f"P.S. This message is automated. If you believe there is an error with this fulfillment, please create a support ticket."
        ),
        body_html=_body(
            content,
            "P.S. This message is automated. If you believe there is an error with this fulfillment, please create a support ticket."
        ),
        sender=SENDER_FULFILLMENT,
    )
