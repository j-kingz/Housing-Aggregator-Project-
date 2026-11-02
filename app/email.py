"""Transactional email delivery for reservation confirmations."""

import smtplib
from email.message import EmailMessage

from flask import current_app


class EmailDeliveryError(RuntimeError):
    """Raised when a configured email provider cannot deliver a message."""


def send_reservation_confirmation(payment):
    """Send the reservation receipt to the renter's registered email address."""
    config = current_app.config
    host = config.get("SMTP_HOST", "")
    sender = config.get("MAIL_SENDER", "")
    renter = payment.renter.user if payment.renter else None
    listing = payment.listing

    if not host or not sender:
        raise EmailDeliveryError(
            "Reservation email is not configured. Set SMTP_HOST and MAIL_SENDER."
        )
    if not renter or not renter.email:
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

    receipt = payment.mpesa_receipt or "Not supplied"
    paid_at = payment.paid_at.strftime("%Y-%m-%d %H:%M UTC") if payment.paid_at else "Not supplied"
    message = EmailMessage()
    message["Subject"] = f"Reservation confirmation - {location}"
    message["From"] = sender
    message["To"] = renter.email
    message.set_content(
        f"Hello {renter.full_name},\n\n"
        "This email confirms that the following home/unit has been reserved for you "
        "after your reservation deposit was received:\n\n"
        f"Listing: {listing.title}\n"
        f"Location: {location}\n"
        f"Amount received: KSh {float(payment.amount):,.0f}\n"
        f"M-Pesa receipt: {receipt}\n"
        f"Payment reference: {payment.payment_id}\n"
        f"Confirmed at: {paid_at}\n\n"
        "Please keep this email as proof of the reservation. It confirms the "
        "reservation deposit only and is not a lease agreement.\n\n"
        "Housing Aggregator"
    )

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
