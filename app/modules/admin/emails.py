# app/modules/admin/emails.py
"""
User Inquiry email notifications — usersupport@gridlineservice.com

Triggers:
  - send_inquiry_submitted()    — fires when a user submits a new inquiry
  - send_inquiry_reviewed()     — fires on approve/deny; routes to specific template by type
  - send_password_reset_link()  — fires when a password_reset inquiry is approved

All are fire-and-forget: they log on failure but never raise.
"""

import logging

from app.core.ses import (send_email, SENDER_USERSUPPORT,
                          user_wants_email,
                          EMAIL_PREF_INQUIRY_SUBMITTED, EMAIL_PREF_INQUIRY_APPROVAL)

logger = logging.getLogger(__name__)

REQUEST_TYPE_LABELS = {
    'password_reset':        'Password Reset',
    'profile_adjustment':    'Profile Adjustment',
    'account_deletion':      'Account Deletion',
    'elevation_request':     'Elevation Request',
    'module_access_request': 'Module Access Request',
}


def _body(content: str, footer: str = "This is an automated message. Do not reply.") -> str:
    return f"""
<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;
            background:#ffffff;padding:32px 40px;color:#333333;font-size:14px;line-height:1.7;">
    {content}
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 16px;">
    <p style="color:#9ca3af;font-size:12px;margin:0;">{footer}</p>
</div>
"""


# ── Public send functions ──────────────────────────────────────────────────────

def send_inquiry_submitted(user_email: str, username: str,
                           request_type: str, details: str | None = None,
                           first_name: str = '', last_name: str = '',
                           inquiry_id: int = 0, instance_name: str = '',
                           user_id: int = 0) -> None:
    """Send a confirmation email when a user submits a new inquiry."""
    if not user_wants_email(user_id, EMAIL_PREF_INQUIRY_SUBMITTED):
        logger.info(f"[admin.emails] user_id={user_id} opted out of inquiry notifications — skipping submission notice")
        return
    if not user_email:
        logger.info(f"[admin.emails] No email for {username} — skipping inquiry submission notice")
        return

    greeting = f"Hello {first_name} {last_name}," if (first_name or last_name) else f"Hello {username},"
    id_str   = str(inquiry_id) if inquiry_id else '—'
    inst_str = instance_name or 'Platform'

    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">Your inquiry has been submitted with the following ID: {id_str}.</p>
<p style="margin:0 0 16px;">
    An L1 or L2 will determine and approve or deny for this change or correction.
    Once they've approved a change will be made to reflect your inquiry.
    If the inquiry was denied you'll be given a reason why.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform &mdash; {inst_str}</p>
"""
    send_email(
        to=user_email,
        subject=f"User Inquiry {id_str} Submission",
        body_text=(
            f"{greeting}\n\n"
            f"Your inquiry has been submitted with the following ID: {id_str}.\n\n"
            f"An L1 or L2 will determine and approve or deny for this change or correction. "
            f"Once they've approved a change will be made to reflect your inquiry. "
            f"If the inquiry was denied you'll be given a reason why.\n\n"
            f"With regards,\nGridline Platform — {inst_str}"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )


def send_password_reset_link(user_email: str, username: str,
                             reset_url: str, first_name: str = '') -> None:
    """Send a password reset link after an admin approves a password_reset inquiry."""
    if not user_email:
        logger.info(f"[admin.emails] No email for {username} — skipping password reset link")
        return

    greeting = f"Hello {first_name}," if first_name else f"Hello {username},"

    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">Your password reset was approved! Below is the link to reset your password:</p>
<p style="margin:0 0 16px;">
    <a href="{reset_url}" style="color:#1d4ed8;">{reset_url}</a>
</p>
<p style="margin:0 0 16px;">
    This link will expire in 1 hour from the time this email was sent.
    If your link expired you'll have to make another inquiry.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject="Password Reset Approved",
        body_text=(
            f"{greeting}\n\n"
            f"Your password reset was approved! Below is the link to reset your password:\n{reset_url}\n\n"
            f"This link will expire in 1 hour from the time this email was sent. "
            f"If your link expired you'll have to make another inquiry.\n\n"
            f"With regards,\nGridline Platform"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )


def send_inquiry_reviewed(user_email: str, username: str,
                          request_type: str, action: str,
                          reason: str | None = None,
                          first_name: str = '', last_name: str = '',
                          user_id: int = 0) -> None:
    """Send an approve/deny notification when an admin reviews an inquiry."""
    if not user_email:
        logger.info(f"[admin.emails] No email for {username} — skipping inquiry review notice")
        return

    type_label = REQUEST_TYPE_LABELS.get(request_type, request_type.replace('_', ' ').title())
    greeting   = f"Hello {first_name}," if first_name else f"Hello {username},"

    if action == 'deny':
        # Denials are always delivered — not subject to opt-out
        _send_inquiry_denied(user_email, username, type_label, reason or 'No reason provided.',
                             greeting)
    else:
        # Approvals are opt-outable
        if not user_wants_email(user_id, EMAIL_PREF_INQUIRY_APPROVAL):
            logger.info(f"[admin.emails] user_id={user_id} opted out of inquiry approval notifications — skipping")
            return
        if request_type == 'profile_adjustment':
            _send_profile_update_approved(user_email, greeting)
        elif request_type == 'account_deletion':
            _send_account_deletion_approved(user_email, greeting)
        else:
            # Generic approval for elevation_request, module_access_request, etc.
            _send_generic_approved(user_email, type_label, greeting)


def _send_profile_update_approved(user_email: str, greeting: str) -> None:
    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">
    Your inquiry has been approved and you should see the change reflect accordingly within 24 hours.
    If no change has been committed but the request was approved, submit a Platform ticket under
    &ldquo;General Inquiry&rdquo; with this email provided.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject="Profile Update Approved",
        body_text=(
            f"{greeting}\n\n"
            f"Your inquiry has been approved and you should see the change reflect accordingly within 24 hours. "
            f"If no change has been committed but the request was approved, submit a Platform ticket under "
            f"\"General Inquiry\" with this email provided.\n\n"
            f"With regards,\nGridline Platform"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )


def _send_account_deletion_approved(user_email: str, greeting: str) -> None:
    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">Your inquiry has been approved and should reflect in the next 24 hours.</p>
<p style="margin:0 0 16px;">
    Notice with account deletions: Once an account is deleted all subsequent data associated
    will also be deleted unable to be recovered. Your account has been placed as
    &ldquo;Deletion Pending&rdquo; until an L2 performs the final approval. You can continue
    to use your account until said action is finalized which you'll be forcibly logged out.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject="Account Deletion Approved",
        body_text=(
            f"{greeting}\n\n"
            f"Your inquiry has been approved and should reflect in the next 24 hours.\n\n"
            f"Notice with account deletions: Once an account is deleted all subsequent data associated "
            f"will also be deleted unable to be recovered. Your account has been placed as \"Deletion Pending\" "
            f"until an L2 performs the final approval. You can continue to use your account until said action "
            f"is finalized which you'll be forcibly logged out.\n\n"
            f"With regards,\nGridline Platform"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )


def _send_inquiry_denied(user_email: str, username: str,
                         type_label: str, reason: str, greeting: str) -> None:
    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 8px;">This is a notice that your inquiry has been denied for the following reason(s):</p>
<p style="margin:0 0 4px;"><strong>Inquiry Type:</strong> {type_label}</p>
<p style="margin:0 0 16px;"><strong>Reason:</strong> {reason}</p>
<p style="margin:0 0 16px;">
    If you believe this is a mistake, you may file another inquiry at any time.
    Please be mindful that excess use of the inquiry system will result in your account being locked.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject="Inquiry Denied",
        body_text=(
            f"{greeting}\n\n"
            f"This is a notice that your inquiry has been denied for the following reason(s):\n"
            f"Inquiry Type: {type_label}\nReason: {reason}\n\n"
            f"If you believe this is a mistake, you may file another inquiry at any time. "
            f"Please be mindful that excess use of the inquiry system will result in your account being locked.\n\n"
            f"With regards,\nGridline Platform"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )


def _send_generic_approved(user_email: str, type_label: str, greeting: str) -> None:
    content = f"""
<p style="margin:0 0 16px;">{greeting}</p>
<p style="margin:0 0 16px;">
    Your <strong>{type_label}</strong> inquiry has been approved.
    You should see the change reflected accordingly within 24 hours.
</p>
<p style="margin:0 0 4px;">With regards,</p>
<p style="margin:0;">Gridline Platform</p>
"""
    send_email(
        to=user_email,
        subject=f"{type_label} Approved",
        body_text=(
            f"{greeting}\n\n"
            f"Your {type_label} inquiry has been approved. "
            f"You should see the change reflected accordingly within 24 hours.\n\n"
            f"With regards,\nGridline Platform"
        ),
        body_html=_body(content),
        sender=SENDER_USERSUPPORT,
    )
