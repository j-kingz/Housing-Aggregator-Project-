"""Reservation deposits paid with M-Pesa.

Flow: a renter opens a vacant unit, taps "Reserve with M-Pesa", types their
phone number and approves the prompt on the phone. The unit is then marked
reserved so nobody else can pay for it.
"""

import hmac
import math
import random
import re
import string
import time
from datetime import timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import csrf, db
from app.email import (
    EmailDeliveryError,
    send_premium_subscription_confirmation,
    send_reservation_confirmation,
)
from app.models import Notification, Payment, Property, utcnow
from app.models import PremiumSubscription
from app.payments import mpesa

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

# how long a demo payment waits before it is confirmed
DEMO_CONFIRM_SECONDS = 4
# a prompt the phone never answered is closed after this long
PENDING_EXPIRES = timedelta(minutes=3)
# wait this long after the prompt is sent before asking Safaricom for a result
FIRST_QUERY_AFTER = timedelta(seconds=10)
# ask Safaricom about one payment at most this often (the status page polls
# every few seconds, and too many queries get the computer blocked)
QUERY_EVERY_SECONDS = 6
# a real payment marked failed is checked with Safaricom again for this long,
# so a PIN entered after the page gave up is still recorded as paid
RECHECK_FAILED_FOR = timedelta(hours=24)
_last_query = {}
# M-Pesa's largest single STK push payment
MAX_CUSTOM_AMOUNT = 250_000
MAX_EXTRA_EMAILS = 5
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def reservation_amount(listing):
    """The deposit for a unit: a share of one month's rent, rounded up."""
    percent = current_app.config.get("MPESA_RESERVATION_PERCENT", 10)
    return max(1, math.ceil(float(listing.rentamount) * percent / 100))


def can_reserve(listing):
    """Only a unit confirmed vacant can be reserved.

    A unit whose status is unknown may already be let, so taking a deposit for
    it is refused; the renter can ask for a premium vacancy check first.
    """
    return bool(listing.is_active) and listing.availability_status == "vacant"


def not_reservable_message(listing):
    """Why a unit cannot be reserved, in words for the renter."""
    status = listing.availability_status
    if not listing.is_active:
        return "This listing is no longer active, so it can't be reserved."
    if status == "reserved":
        return "This unit has already been reserved by another renter."
    if status == "occupied":
        return "This unit is occupied, so it can't be reserved."
    return (
        "This unit can only be reserved once it is confirmed vacant. "
        "Request a vacancy check to have it confirmed."
    )


def has_pending_reservation(listing_id):
    pending = Payment.query.filter_by(listing_id=listing_id, status="pending").all()
    now = utcnow()
    active = False
    for payment in pending:
        if now - (payment.created_at or now) >= PENDING_EXPIRES:
            payment.status = "failed"
            payment.result_desc = mpesa.RESULT_MESSAGES[1037]
        else:
            active = True
    return active


def _renter_required():
    if not current_user.is_renter:
        flash("Only renter accounts can pay a reservation deposit.", "warning")
        return False
    return True


def _visible_to_current_user(payment):
    if current_user.is_admin or payment.renter_id == current_user.user_id:
        return True
    listing = payment.listing
    return bool(listing and listing.landlord_id == current_user.user_id)


# -- paying -----------------------------------------------------------------
@payments_bp.route("/pay/<int:listing_id>", methods=["GET", "POST"])
@login_required
def pay(listing_id):
    listing = db.get_or_404(Property, listing_id)
    if not _renter_required():
        return redirect(url_for("listings.detail", listing_id=listing_id))

    config = current_app.config
    amount = reservation_amount(listing)
    demo = mpesa.is_demo(config)

    if not can_reserve(listing):
        flash(not_reservable_message(listing), "warning")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    if request.method == "POST":
        # Serialize payment creation for this unit. The pending payment is
        # committed before contacting Safaricom so it acts as a reservation
        # hold for concurrent requests.
        listing = (
            Property.query.filter_by(listing_id=listing_id)
            .with_for_update()
            .first()
        )
        if listing is None:
            abort(404)
        # checked again under the row lock: the status may have changed since
        # the form was opened
        if not can_reserve(listing):
            flash(not_reservable_message(listing), "warning")
            return redirect(url_for("listings.detail", listing_id=listing_id))
        if has_pending_reservation(listing_id):
            flash("This unit already has a reservation in progress.", "warning")
            return redirect(url_for("listings.detail", listing_id=listing_id))
        amount = reservation_amount(listing)

        form = request.form
        choice = "custom" if form.get("amount_choice") == "custom" else "reservation"

        def refuse(message):
            flash(message, "danger")
            return render_template(
                "payments/pay.html", listing=listing, amount=amount, demo=demo,
                phone=form.get("phone", ""), choice=choice,
                custom_amount=form.get("custom_amount", ""),
                receipt_email=form.get("receipt_email", ""),
                max_custom=MAX_CUSTOM_AMOUNT,
            ), 400

        phone = mpesa.normalise_phone(form.get("phone"))
        if not phone:
            return refuse("Enter a valid Safaricom number, for example 0712 345 678 or 0112 345 678.")

        to_pay = amount
        if choice == "custom":
            try:
                to_pay = int(str(form.get("custom_amount", "")).replace(",", "").strip())
            except ValueError:
                to_pay = 0
            if not 1 <= to_pay <= MAX_CUSTOM_AMOUNT:
                return refuse(f"Enter an amount between KSh 1 and KSh {MAX_CUSTOM_AMOUNT:,}.")

        extra = [a for a in re.split(r"[,;\s]+", form.get("receipt_email") or "") if a]
        bad = [a for a in extra if not EMAIL_PATTERN.fullmatch(a)]
        if bad:
            return refuse(f"{bad[0]} is not a valid email address.")
        if len(extra) > MAX_EXTRA_EMAILS:
            return refuse(f"Add at most {MAX_EXTRA_EMAILS} extra email addresses.")
        receipt_email = ", ".join(extra)

        renter = current_user.ensure_renter_details()
        payment = Payment(
            renter_id=renter.renter_id,
            listing_id=listing.listing_id,
            amount=Decimal(to_pay),
            modeofpayment="M-Pesa",
            status="pending",
            phone=phone,
            purpose=choice,
            simulated=demo,
            receipt_email=receipt_email or None,
        )
        db.session.add(payment)
        db.session.flush()
        db.session.commit()

        try:
            if demo:
                payment.checkout_request_id = "DEMO-" + "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=12)
                )
                payment.merchant_request_id = payment.checkout_request_id
            else:
                result = mpesa.stk_push(
                    config, phone, to_pay,
                    reference=f"UNIT{listing.listing_id}",
                    description="Reservation",
                )
                payment.checkout_request_id = result["checkout_request_id"]
                payment.merchant_request_id = result["merchant_request_id"]
        except mpesa.MpesaError as exc:
            payment.status = "failed"
            payment.result_desc = str(exc)[:255]
            db.session.commit()
            flash(f"The M-Pesa prompt could not be sent: {exc}", "danger")
            return redirect(url_for("payments.status", payment_id=payment.payment_id))

        db.session.commit()
        return redirect(url_for("payments.status", payment_id=payment.payment_id))

    return render_template(
        "payments/pay.html",
        listing=listing,
        amount=amount,
        demo=demo,
        phone=mpesa.local_part(current_user.phonenumber),
        choice="reservation",
        custom_amount="",
        receipt_email="",
        max_custom=MAX_CUSTOM_AMOUNT,
    )


# -- status -----------------------------------------------------------------
def _email_proof(payment):
    """Email the reservation proof to the renter and record whether it went."""
    try:
        send_reservation_confirmation(payment)
        payment.confirmation_email_sent_at = utcnow()
        payment.confirmation_email_error = None
        sent = True
    except EmailDeliveryError as exc:
        payment.confirmation_email_error = str(exc)[:255]
        current_app.logger.warning(
            "Reservation email was not sent for payment %s: %s", payment.payment_id, exc
        )
        sent = False
    db.session.commit()
    return sent


def _finish(payment, code, description, receipt=None):
    """Record the outcome of a payment. Safe to call twice.

    A success reported by Safaricom always wins over an earlier "failed":
    the money has left the renter's M-Pesa, so the payment must show as paid.
    """
    late_success = payment.status == "failed" and code == 0
    if payment.status != "pending" and not late_success:
        return
    payment.result_desc = (description or mpesa.RESULT_MESSAGES.get(code, ""))[:255]
    if code == 0:
        payment.status = "paid"
        payment.paid_at = utcnow()
        payment.mpesa_receipt = receipt
        listing = payment.listing
        if listing is not None and listing.availability_status != "occupied":
            listing.availability_status = "reserved"
        db.session.add(
            Notification(
                renter_id=payment.renter_id,
                listing_id=payment.listing_id,
                message=(
                    f"Payment of KShs {float(payment.amount):,.0f} received, "
                    "you now have access to premium subscription."
                    if payment.purpose in ("premium_subscription", "premium_subscription_demo")
                    else f"Payment of KSh {float(payment.amount):,.0f} received. "
                    f"{listing.title if listing else 'Your unit'} is reserved for you."
                ),
                type="payment",
                url=url_for("payments.status", payment_id=payment.payment_id),
            )
        )
        db.session.commit()
        if payment.listing_id is not None:
            _email_proof(payment)
        if payment.purpose in ("premium_subscription", "premium_subscription_demo"):
            now = utcnow()
            current = (
                PremiumSubscription.query
                .filter_by(renter_id=payment.renter_id, status="active")
                .order_by(PremiumSubscription.expires_at.desc())
                .first()
            )
            start = current.expires_at if current and current.expires_at > now else now
            db.session.add(
                PremiumSubscription(
                    renter_id=payment.renter_id,
                    payment_id=payment.payment_id,
                    starts_at=start,
                    expires_at=start + timedelta(days=current_app.config["PREMIUM_SUBSCRIPTION_DAYS"]),
                )
            )
            db.session.commit()
            try:
                send_premium_subscription_confirmation(
                    payment.renter.user,
                    payment,
                    start + timedelta(days=current_app.config["PREMIUM_SUBSCRIPTION_DAYS"]),
                )
            except EmailDeliveryError as exc:
                current_app.logger.warning(
                    "Premium subscription email was not sent for payment %s: %s",
                    payment.payment_id,
                    exc,
                )
    elif code in (1032,):
        payment.status = "cancelled"
    else:
        payment.status = "failed"
    db.session.commit()


def _query_safaricom(payment):
    """Safaricom's result for a real payment, or None if not known yet.

    Throttled per payment so polling the status page does not flood Daraja.
    """
    if not payment.checkout_request_id:
        return None
    now = time.monotonic()
    if now - _last_query.get(payment.payment_id, 0) < QUERY_EVERY_SECONDS:
        return None
    _last_query[payment.payment_id] = now
    try:
        return mpesa.stk_query(current_app.config, payment.checkout_request_id)
    except mpesa.MpesaError as exc:
        current_app.logger.info("STK query for payment %s failed: %s", payment.payment_id, exc)
        return None


def _reconcile(payment, recheck_failed=False):
    """Bring a pending payment up to date. Called whenever the status is read.

    With recheck_failed, a real payment that was marked failed in the last
    RECHECK_FAILED_FOR is asked about again, and turned into "paid" if
    Safaricom says the renter did approve it.
    """
    age = utcnow() - (payment.created_at or utcnow())

    if payment.status == "failed":
        if recheck_failed and not payment.simulated and age < RECHECK_FAILED_FOR:
            outcome = _query_safaricom(payment)
            if outcome is not None and outcome["code"] == 0:
                _finish(payment, 0, outcome["description"])
        return
    if payment.status != "pending":
        return

    if payment.simulated:
        if age >= timedelta(seconds=DEMO_CONFIRM_SECONDS):
            receipt = "DEMO" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            _finish(payment, 0, "Demo payment confirmed (no real money moved).", receipt)
        return

    # real payment: the callback normally arrives first. If it has not, ask
    # Safaricom; "still processing" comes back as None and we keep waiting.
    if age >= FIRST_QUERY_AFTER:
        outcome = _query_safaricom(payment)
        if outcome is not None:
            _finish(payment, outcome["code"], outcome["description"])
            return
    if age >= PENDING_EXPIRES:
        _finish(payment, 1037, mpesa.RESULT_MESSAGES[1037])


@payments_bp.route("/<int:payment_id>")
@login_required
def status(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if not _visible_to_current_user(payment):
        abort(403)
    _reconcile(payment, recheck_failed=True)
    listing = payment.listing
    return render_template(
        "payments/status.html", payment=payment, listing=listing,
        deposit=reservation_amount(listing) if listing else None,
    )


@payments_bp.route("/<int:payment_id>/status.json")
@login_required
def status_json(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if not _visible_to_current_user(payment):
        abort(403)
    _reconcile(payment)
    return jsonify(
        {
            "status": payment.status,
            "receipt": payment.mpesa_receipt,
            "message": payment.result_desc,
        }
    )


@payments_bp.route("/<int:payment_id>/cancel", methods=["POST"])
@login_required
def cancel(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if payment.renter_id != current_user.user_id:
        abort(403)
    if payment.status == "pending":
        payment.status = "cancelled"
        payment.result_desc = "Cancelled by the renter."
        db.session.commit()
        flash("Payment cancelled. If you already approved it on your phone, contact support.", "info")
    return redirect(url_for("payments.status", payment_id=payment.payment_id))


@payments_bp.route("/<int:payment_id>/resend-email", methods=["POST"])
@login_required
def resend_email(payment_id):
    """Send the reservation proof email again (the renter or an administrator)."""
    payment = db.get_or_404(Payment, payment_id)
    if payment.renter_id != current_user.user_id and not current_user.is_admin:
        abort(403)
    if payment.status != "paid":
        flash("Only a paid reservation has a proof email.", "warning")
    elif _email_proof(payment):
        flash(f"The reservation proof was sent to {payment.proof_email}.", "success")
    else:
        flash("The email could not be sent: " + (payment.confirmation_email_error or ""), "danger")
    return redirect(url_for("payments.status", payment_id=payment.payment_id))


@payments_bp.route("/")
@login_required
def history():
    """A renter's own payments, or the payments received for a landlord's units."""
    if current_user.is_landlord:
        rows = (
            Payment.query.join(Property, Payment.listing_id == Property.listing_id)
            .filter(Property.landlord_id == current_user.user_id)
            .order_by(Payment.created_at.desc())
            .all()
        )
        mode = "received"
    elif current_user.is_admin:
        rows = Payment.query.order_by(Payment.created_at.desc()).limit(200).all()
        mode = "all"
    else:
        rows = (
            Payment.query.filter_by(renter_id=current_user.user_id)
            .order_by(Payment.created_at.desc())
            .all()
        )
        mode = "mine"
    for payment in rows:
        _reconcile(payment)
    return render_template("payments/history.html", payments=rows, mode=mode)


# -- Safaricom's callback ----------------------------------------------------
@payments_bp.route("/mpesa/callback/<token>", methods=["POST"])
@csrf.exempt
def mpesa_callback(token):
    """Safaricom reports the result of a payment prompt here.

    The URL carries a secret token, the payment must exist and still be
    pending, and the paid amount must match, so a forged call cannot mark
    a unit as paid.
    """
    expected = mpesa.callback_token(current_app.config)
    if not hmac.compare_digest(token, expected):
        abort(404)

    result = mpesa.parse_callback(request.get_json(silent=True) or {})
    accepted = {"ResultCode": 0, "ResultDesc": "Accepted"}
    if result is None:
        return jsonify(accepted)

    payment = Payment.query.filter_by(checkout_request_id=result["checkout_request_id"]).first()
    accepts_late_success = (
        payment is not None and payment.status == "failed" and result["code"] == 0
    )
    if payment is None or (payment.status != "pending" and not accepts_late_success):
        return jsonify(accepted)

    if result["code"] == 0:
        paid = Decimal(str(result["amount"] or 0))
        if paid < payment.amount:
            _finish(payment, 1, f"Amount paid ({paid}) was less than required ({payment.amount}).")
            return jsonify(accepted)
    _finish(payment, result["code"], result["description"], result["receipt"])
    return jsonify(accepted)
