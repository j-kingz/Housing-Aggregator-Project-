"""Transactional email delivery for reservation confirmations."""

import smtplib
from email.message import EmailMessage
from html import escape

from flask import current_app


CUSTOM_AMOUNT_NOTE = (
    "You chose this amount yourself. It is not the real reservation price for this "
    "unit yet; the landlord may ask for the balance of the reservation deposit."
)


class EmailDeliveryError(RuntimeError):
    """Raised when a configured email provider cannot deliver a message."""


def email_configured(config=None):
    config = config if config is not None else current_app.config
    return bool(config.get("SMTP_HOST") and config.get("MAIL_SENDER"))


def deliver(message, config=None):
    """Send an EmailMessage through the SMTP server in the settings."""
    config = config if config is not None else current_app.config
    if not email_configured(config):
        raise EmailDeliveryError(
            "Reservation email is not configured. Set SMTP_HOST and MAIL_SENDER."
        )
    if not message["From"]:
        message["From"] = config["MAIL_SENDER"]

    host = config["SMTP_HOST"]
    port = int(config.get("SMTP_PORT", 587))
    username = config.get("SMTP_USERNAME", "")
    password = config.get("SMTP_PASSWORD", "")
    timeout = int(config.get("SMTP_TIMEOUT", 15))

    try:
        if config.get("SMTP_USE_SSL", False):
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                smtp.ehlo()
                if config.get("SMTP_USE_TLS", True):
                    smtp.starttls()
                    smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(f"Reservation confirmation email failed: {exc}") from exc


def send_reservation_confirmation(payment):
    """Send the reservation receipt to the renter's registered email address."""
    config = current_app.config
    renter = payment.renter.user if payment.renter else None
    listing = payment.listing

    if not email_configured(config):
        raise EmailDeliveryError(
            "Reservation email is not configured. Set SMTP_HOST and MAIL_SENDER."
        )
    to_address = payment.proof_email  # every recipient, comma separated
    if not renter or not to_address:
        raise EmailDeliveryError("The renter does not have a valid email address.")
    if not listing:
        raise EmailDeliveryError("The reserved listing no longer exists.")

    location = listing.building_name or listing.title or "your selected unit"
    unit_details = []
    if listing.floor_number is not None:
        unit_details.append(f"Floor {listing.floor_number}")
    if listing.room_number:
        unit_details.append(f"Unit {listing.room_number}")
    if unit_details:
        location += " - " + ", ".join(unit_details)
    area = ", ".join(part for part in (listing.address, listing.city) if part)

    receipt = payment.mpesa_receipt or "Not supplied"
    paid_at = payment.paid_at.strftime("%Y-%m-%d %H:%M UTC") if payment.paid_at else "Not supplied"
    amount = f"KSh {float(payment.amount):,.0f}"
    rows = [
        ("Listing", listing.title),
        ("Unit", location),
        ("Area", area or "Not supplied"),
        ("Monthly rent", f"KSh {float(listing.rentamount):,.0f}"),
        ("Amount received" if payment.is_custom_amount else "Deposit received", amount),
        ("Paid from", payment.phone or "Not supplied"),
        ("M-Pesa receipt", receipt),
        ("Payment reference", str(payment.payment_id)),
        ("Confirmed at", paid_at),
    ]
    if payment.is_custom_amount:
        rows.append(("Note", CUSTOM_AMOUNT_NOTE))
    if payment.simulated:
        rows.append(("Note", "Demo payment - no real money moved"))

    message = EmailMessage()
    message["Subject"] = f"Reservation confirmation - {location}"
    message["From"] = config["MAIL_SENDER"]
    message["To"] = to_address
    message.set_content(
        f"Hello {renter.full_name},\n\n"
        "This email confirms that the following home/unit has been reserved for you "
        "after your reservation deposit was received:\n\n"
        + "".join(f"{label}: {value}\n" for label, value in rows)
        + "\nPlease keep this email as proof of the reservation. It confirms the "
        "reservation deposit only and is not a lease agreement.\n\n"
        "Housing Aggregator"
    )
    table = "".join(
        f'<tr><td style="padding:6px 12px 6px 0;color:#52514e">{escape(label)}</td>'
        f'<td style="padding:6px 0;font-weight:600">{escape(str(value))}</td></tr>'
        for label, value in rows
    )
    message.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;max-width:560px;color:#0b0b0b">
  <h2 style="color:#0f766e;margin-bottom:4px">Reservation confirmed</h2>
  <p>Hello {escape(renter.full_name)},</p>
  <p>This email confirms that the following home/unit has been reserved for you
  after your reservation deposit of <strong>{escape(amount)}</strong> was received.</p>
  <table style="border-collapse:collapse;font-size:14px">{table}</table>
  <p style="font-size:13px;color:#52514e">Please keep this email as proof of the reservation.
  It confirms the reservation deposit only and is not a lease agreement.</p>
  <p>Housing Aggregator</p>
</div>""",
        subtype="html",
    )
    deliver(message, config)


def send_test_email(to_address, config=None):
    """A short message that proves the SMTP settings work."""
    message = EmailMessage()
    message["Subject"] = "Housing Aggregator test email"
    message["To"] = to_address
    message.set_content(
        "Your SMTP settings work. Reservation confirmation emails will be delivered."
    )
    deliver(message, config)


def send_password_reset(user, reset_url):
    """Send a single-use password reset link to the user's registered email."""
    config = current_app.config
    if not email_configured(config):
        raise EmailDeliveryError("Password reset email is not configured.")

    message = EmailMessage()
    message["Subject"] = "Reset your Housing Aggregator password"
    message["From"] = config["MAIL_SENDER"]
    message["To"] = user.email
    message.set_content(
        f"Hello {user.full_name},\n\n"
        "Use the link below to choose a new Housing Aggregator password. "
        "The link expires in 30 minutes and can only be used once:\n\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email.\n\n"
        "Housing Aggregator"
    )
    message.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;max-width:560px;color:#0b0b0b">
  <h2 style="color:#0f766e">Reset your password</h2>
  <p>Hello {escape(user.full_name)},</p>
  <p>Use the button below to choose a new Housing Aggregator password.
  The link expires in 30 minutes and can only be used once.</p>
  <p><a href="{escape(reset_url)}" style="background:#0f766e;color:white;padding:10px 16px;text-decoration:none;border-radius:4px">Reset password</a></p>
  <p style="font-size:13px;color:#52514e">If you did not request this, you can ignore this email.</p>
  <p>Housing Aggregator</p>
</div>""",
        subtype="html",
    )
    deliver(message, config)


def send_premium_subscription_confirmation(user, payment, expires_at):
    """Send confirmation that premium vacancy-verification access is active."""
    config = current_app.config
    if not email_configured(config):
        raise EmailDeliveryError("Premium subscription email is not configured.")

    amount = f"KShs {float(payment.amount):,.0f}"
    expiry = expires_at.strftime("%d %b %Y")
    message = EmailMessage()
    message["Subject"] = "Your premium subscription is active"
    message["From"] = config["MAIL_SENDER"]
    message["To"] = user.email
    message.set_content(
        f"Hello {user.full_name},\n\n"
        f"Payment of {amount} received, you now have access to premium subscription.\n"
        f"Your access is active until {expiry}.\n\n"
        "You can now request verified vacancy checks from the Premium checks section.\n\n"
        "Housing Aggregator"
    )
    message.add_alternative(
        f"""<div style="font-family:Arial,sans-serif;max-width:560px;color:#0b0b0b">
  <h2 style="color:#0f766e">Premium subscription active</h2>
  <p>Hello {escape(user.full_name)},</p>
  <p><strong>Payment of {escape(amount)} received, you now have access to premium subscription.</strong></p>
  <p>Your access is active until <strong>{escape(expiry)}</strong>.</p>
  <p>You can now request verified vacancy checks from the Premium checks section.</p>
  <p>Housing Aggregator</p>
</div>""",
        subtype="html",
    )
    deliver(message, config)
