# app/core/ses.py
"""
Amazon SES Email Utility

Provides a single send_email() function for all outbound mail.
Uses the IAM instance-profile role — no credentials in code.

Falls back to a log-only no-op when SES_ENABLED is not set (local dev).

Sender constants (import and pass as `sender=`):
    SENDER_NOREPLY      noreply@gridlineservice.com     — general notifications
    SENDER_FULFILLMENT  fulfillment@gridlineservice.com — print job / request updates
    SENDER_SUPPORT      support@gridlineservice.com     — support correspondence
    SENDER_RESET        reset@gridlineservice.com       — password reset emails

Usage:
    from app.core.ses import send_email, SENDER_FULFILLMENT

    send_email(
        to="user@example.com",
        subject="Your request is ready",
        body_text="Plain text fallback.",
        body_html="<p>HTML version.</p>",
        sender=SENDER_FULFILLMENT,
    )
"""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_ENABLED       = os.environ.get("SES_ENABLED", "").strip().lower() == "true"
_DEFAULT_FROM  = os.environ.get("SES_SENDER_EMAIL", "noreply@gridlineservice.com").strip()
_REGION        = os.environ.get("SES_REGION", "us-east-1").strip()
_CONFIG_SET    = os.environ.get("SES_CONFIG_SET", "").strip()   # optional

# ── Sender addresses ──────────────────────────────────────────────────────────
_DOMAIN = "gridlineservice.com"
SENDER_NOREPLY     = f"noreply@{_DOMAIN}"       # general notifications
SENDER_FULFILLMENT = f"fulfillment@{_DOMAIN}"   # print job / request updates
SENDER_USERSUPPORT = f"usersupport@{_DOMAIN}"   # user inquiries, password resets
SENDER_SUPPORT     = f"support@{_DOMAIN}"       # L3/S1 support ticket replies
SENDER_SYSTEM      = f"system@{_DOMAIN}"        # S1 system-wide alerts
SENDER_DEVELOPMENT = f"development@{_DOMAIN}"   # bug reports and suggestions


def ses_configured() -> bool:
    """Return True when SES is enabled (i.e. running on EB with SES_ENABLED=true)."""
    return _ENABLED


def _client():
    """Return a boto3 SES client using the instance-profile role."""
    return boto3.client("ses", region_name=_REGION)


def send_email(
    to: str | list[str],
    subject: str,
    body_text: str = "",
    body_html: str = "",
    sender: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """
    Send a transactional email via Amazon SES.

    Args:
        to:         Recipient address or list of addresses.
        subject:    Email subject line.
        body_text:  Plain-text body (fallback for clients that don't render HTML).
        body_html:  HTML body (optional but recommended).
        sender:     From address. Defaults to SES_SENDER_EMAIL env var.
                    Must be under the verified domain (gridlineservice.com).
        reply_to:   Optional Reply-To address.

    Returns:
        True on success, False on failure (never raises — caller decides how to handle).
    """
    if not _ENABLED:
        # Local dev — log the email instead of sending it
        recipients = [to] if isinstance(to, str) else to
        logger.info(
            f"[SES disabled] Would send email | to={recipients} "
            f"subject='{subject}' from={sender or _DEFAULT_FROM}"
        )
        return True

    from_addr = sender or _DEFAULT_FROM
    recipients = [to] if isinstance(to, str) else to

    message: dict = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {},
    }
    if body_html:
        message["Body"]["Html"] = {"Data": body_html, "Charset": "UTF-8"}
    if body_text:
        message["Body"]["Text"] = {"Data": body_text, "Charset": "UTF-8"}

    send_kwargs: dict = {
        "Source": from_addr,
        "Destination": {"ToAddresses": recipients},
        "Message": message,
    }
    if reply_to:
        send_kwargs["ReplyToAddresses"] = [reply_to]
    if _CONFIG_SET:
        send_kwargs["ConfigurationSetName"] = _CONFIG_SET

    try:
        response = _client().send_email(**send_kwargs)
        message_id = response.get("MessageId", "unknown")
        logger.info(f"SES sent | to={recipients} subject='{subject}' message_id={message_id}")
        return True
    except (BotoCoreError, ClientError) as exc:
        logger.error(f"SES send failed | to={recipients} subject='{subject}' error={exc}")
        return False
