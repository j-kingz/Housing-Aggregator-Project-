"""Reservation deposits paid with M-Pesa.

Flow: a renter opens a vacant unit, taps "Reserve with M-Pesa", types their
phone number and approves the prompt on the phone. The unit is then marked
reserved so nobody else can pay for it.
"""

import hmac
import math
import random
import string
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
from app.models import Notification, Payment, Property, utcnow
from app.payments import mpesa

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

# how long a demo payment waits before it is confirmed
DEMO_CONFIRM_SECONDS = 4
# a prompt the phone never answered is closed after this long
PENDING_EXPIRES = timedelta(minutes=3)


def reservation_amount(listing):
    """The deposit for a unit: a share of one month's rent, rounded up."""
    percent = current_app.config.get("MPESA_RESERVATION_PERCENT", 10)
    return max(1, math.ceil(float(listing.rentamount) * percent / 100))


def can_reserve(listing):
    return bool(listing.is_active) and listing.availability_status in ("vacant", "unknown")


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
        flash("This unit is no longer open for reservation.", "warning")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    if request.method == "POST":
        phone = mpesa.normalise_phone(request.form.get("phone"))
        if not phone:
            flash("Enter a valid Safaricom number, for example 0712 345 678.", "danger")
            return render_template(
                "payments/pay.html", listing=listing, amount=amount, demo=demo,
                phone=request.form.get("phone", ""),
            ), 400

        renter = current_user.ensure_renter_details()
        payment = Payment(
            renter_id=renter.renter_id,
            listing_id=listing.listing_id,
            amount=Decimal(amount),
            modeofpayment="M-Pesa",
            status="pending",
            phone=phone,
            purpose="reservation",
            simulated=demo,
        )
        db.session.add(payment)
        db.session.flush()

        try:
            if demo:
                payment.checkout_request_id = "DEMO-" + "".join(
                    random.choices(string.ascii_uppercase + string.digits, k=12)
                )
                payment.merchant_request_id = payment.checkout_request_id
            else:
                result = mpesa.stk_push(
                    config, phone, amount,
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
        phone=current_user.phonenumber or "",
    )


# -- status -----------------------------------------------------------------
def _finish(payment, code, description, receipt=None):
    """Record the outcome of a payment. Safe to call twice."""
    if payment.status != "pending":
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
                message=f"Payment of KSh {float(payment.amount):,.0f} received. "
                        f"{listing.title if listing else 'Your unit'} is reserved for you.",
                type="payment",
                url=url_for("payments.status", payment_id=payment.payment_id),
            )
        )
    elif code in (1032,):
        payment.status = "cancelled"
    else:
        payment.status = "failed"
    db.session.commit()


def _reconcile(payment):
    """Bring a pending payment up to date. Called whenever the status is read."""
    if payment.status != "pending":
        return
    age = utcnow() - (payment.created_at or utcnow())

    if payment.simulated:
        if age >= timedelta(seconds=DEMO_CONFIRM_SECONDS):
            receipt = "DEMO" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            _finish(payment, 0, "Demo payment confirmed (no real money moved).", receipt)
        return

    # real payment: the callback normally arrives first. If it has not, ask Safaricom.
    if age >= timedelta(seconds=8) and payment.checkout_request_id:
        try:
            outcome = mpesa.stk_query(current_app.config, payment.checkout_request_id)
        except mpesa.MpesaError:
            outcome = None
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
    _reconcile(payment)
    return render_template("payments/status.html", payment=payment, listing=payment.listing)


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
    if payment is None or payment.status != "pending":
        return jsonify(accepted)

    if result["code"] == 0:
        paid = Decimal(str(result["amount"] or 0))
        if paid < payment.amount:
            _finish(payment, 1, f"Amount paid ({paid}) was less than required ({payment.amount}).")
            return jsonify(accepted)
    _finish(payment, result["code"], result["description"], result["receipt"])
    return jsonify(accepted)
