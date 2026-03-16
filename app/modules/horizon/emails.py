# app/modules/horizon/emails.py
"""
Horizon operator email notifications.

Support ticket triggers:
  - send_ticket_confirmation()  — fires when a user submits a new support ticket
                                   routes to support@ or development@ by category
  - send_ticket_reply()         — fires when an L3/S1 operator replies to a ticket
                                   routes to support@ or development@ by category

System alert trigger (S1 only):
  - send_system_alert()         — broadcasts a system alert to all users in a target scope

Category routing:
  - bug, feature_request  → SENDER_DEVELOPMENT (development@gridlineservice.com)
  - all others            → SENDER_SUPPORT     (support@gridlineservice.com)

Both are fire-and-forget: they log on failure but never raise.
"""

import logging

from app.core.ses import send_email, SENDER_SUPPORT, SENDER_DEVELOPMENT, SENDER_SYSTEM

logger = logging.getLogger(__name__)

_DEV_CATEGORIES = {'bug', 'feature_request'}


def _sender_for(category: str) -> str:
    return SENDER_DEVELOPMENT if category in _DEV_CATEGORIES else SENDER_SUPPORT


def _body(content: str, footer: str = "This is an automated message. Do not reply.") -> str:
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;
            background:#ffffff;padding:32px 40px;color:#333333;font-size:14px;line-height:1.7;">
    {content}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px;">
    <p style="color:#9ca3af;font-size:12px;margin:0;">{footer}</p>
</div>
"""


def send_ticket_confirmation(user_email: str, username: str,
                             ticket_id: int, subject: str, category: str,
                             first_name: str = '', last_name: str = '',
                             inquiry_link: str = '') -> None:
    """Send a submission confirmation when a user opens a support ticket."""
    if not user_email:
        logger.info(f"[horizon.emails] No email for {username} — skipping ticket #{ticket_id} confirmation")
        return

    is_dev   = category in _DEV_CATEGORIES
    sender   = _sender_for(category)
    greeting = (
        f"Hello {first_name} {last_name},"
        if (first_name or last_name)
        else f"Hello {username},"
    )
    inq_line = (
        f'For Instance inquiries and profile issues please file a user inquiry here: '
        f'<a href="{inquiry_link}" style="color:#1d4ed8;">{inquiry_link}</a>.'
        if inquiry_link
        else 'For Instance inquiries and profile issues please file a user inquiry through the platform.'
    )
    inq_plain = (
        f"For Instance inquiries and profile issues please file a user inquiry here: {inquiry_link}."
        if inquiry_link
        else "For Instance inquiries and profile issues please file a user inquiry through the platform."
    )

    if is_dev:
        email_subject = f"[{subject}] {ticket_id} - Developer Matter Submitted"
        content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">
    Thank you for contacting the development team. Tickets like these may take up to 72 hours
    in order to properly diagnose and create a preferred action plan to solve.
    Sending multiple tickets detailing the same issue will not help and will result in delays.
</p>
<p style="margin:0 0 16px;">
    {inq_line}
    This is also for password resets which are handled by your L1 and L2 admins.
</p>
<p style="margin:0 0 16px;">
    For L1 admins seeking elevation to L2 please file a support ticket as a &ldquo;General Inquiry&rdquo;.
</p>
<p style="margin:0 0 4px;">Sincerely,</p>
<p style="margin:0;">Gridline Development</p>
"""
        plain = (
            f"{greeting}\n\n"
            f"Thank you for contacting the development team. Tickets like these may take up to 72 hours "
            f"in order to properly diagnose and create a preferred action plan to solve. "
            f"Sending multiple tickets detailing the same issue will not help and will result in delays.\n\n"
            f"{inq_plain} This is also for password resets which are handled by your L1 and L2 admins.\n\n"
            f"For L1 admins seeking elevation to L2 please file a support ticket as a \"General Inquiry\".\n\n"
            f"Sincerely,\nGridline Development"
        )
    else:
        email_subject = f"[{subject}] {ticket_id} Submission"
        content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">
    Thank you for reaching out, your ticket has been sent to our internal system for review.
    Please keep in mind that it can take up to 48 hours to receive a response.
    {inq_line} This link is also for password resets.
</p>
<p style="margin:0 0 4px;">Sincerely,</p>
<p style="margin:0;">Gridline Team</p>
"""
        plain = (
            f"{greeting}\n\n"
            f"Thank you for reaching out, your ticket has been sent to our internal system for review. "
            f"Please keep in mind that it can take up to 48 hours to receive a response. "
            f"{inq_plain} This link is also for password resets.\n\n"
            f"Sincerely,\nGridline Team"
        )

    send_email(
        to=user_email,
        subject=email_subject,
        body_text=plain,
        body_html=_body(content),
        sender=sender,
    )


def send_ticket_reply(user_email: str, username: str, ticket_id: int,
                      subject: str, category: str,
                      reply_body: str, operator_name: str,
                      operator_first_name: str = '', operator_email: str = '',
                      operator_position: str = '') -> None:
    """Send an operator reply to the ticket submitter.

    For dev categories, ``operator_position`` is rendered as the developer's
    handle/sign-off line between their name and email (e.g. "Senior Developer").
    """
    if not user_email:
        logger.info(f"[horizon.emails] No email for {username} — skipping ticket #{ticket_id} reply")
        return

    is_dev     = category in _DEV_CATEGORIES
    sender     = _sender_for(category)
    staff_name = operator_first_name or operator_name

    if is_dev:
        email_subject = f"RE: [{subject}] {ticket_id} - Investigation"
        sign_off_line = (
            f'<p style="margin:0 0 4px;">{operator_position}</p>'
            if operator_position else ''
        )
        content = f"""
<p style="margin:0 0 16px;white-space:pre-line;">{reply_body}</p>
<p style="margin:0 0 4px;">{staff_name}</p>
{sign_off_line}
<p style="margin:0 0 4px;">{operator_email}</p>
<p style="margin:0;">Gridline Development</p>
"""
        plain_sign_off = f"{operator_position}\n" if operator_position else ''
        plain = (
            f"{reply_body}\n\n"
            f"{staff_name}\n"
            f"{plain_sign_off}"
            f"{operator_email}\n"
            f"Gridline Development"
        )
    else:
        email_subject = f"RE: [{subject}] {ticket_id}"
        content = f"""
<p style="margin:0 0 16px;white-space:pre-line;">{reply_body}</p>
<p style="margin:0 0 4px;">Sincerely,</p>
<p style="margin:0 0 4px;">{staff_name}</p>
<p style="margin:0 0 4px;">{operator_email}</p>
<p style="margin:0;">Gridline Support</p>
"""
        plain = (
            f"{reply_body}\n\n"
            f"Sincerely,\n{staff_name}\n{operator_email}\nGridline Support"
        )

    send_email(
        to=user_email,
        subject=email_subject,
        body_text=plain,
        body_html=_body(content, ""),
        sender=sender,
        reply_to=sender,
    )


def send_system_alert(user_email: str, username: str,
                      alert_type: str, title: str, message: str,
                      scope_label: str, sender_name: str = '') -> None:
    """Send a system alert broadcast to a single recipient.

    Call once per recipient — the caller is responsible for iterating users.
    ``scope_label`` is a human-readable string like "All Users" or "Instance: Acme Corp".
    """
    if not user_email:
        return

    type_labels = {
        'maintenance': 'Maintenance',
        'outage':      'Outage',
        'resolved':    'Resolved',
        'security':    'Security',
        'info':        'Notice',
    }
    action_type = type_labels.get(alert_type, alert_type.title())
    sysadmin    = sender_name or 'Gridline Platform'

    content = f"""
<p style="margin:0 0 16px;white-space:pre-line;">{message}</p>
<p style="margin:0 0 16px;">
    We apologize for the inconvenience as we are currently investigating this matter.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0 0 4px;">{sysadmin}</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject=f"[{action_type}] {title}",
        body_text=(
            f"{message}\n\n"
            f"We apologize for the inconvenience as we are currently investigating this matter.\n\n"
            f"With regards,\n{sysadmin}\nGridline Platform"
        ),
        body_html=_body(content, "This is an automated message, Do not reply."),
        sender=SENDER_SYSTEM,
    )
