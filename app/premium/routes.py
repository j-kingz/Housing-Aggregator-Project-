import re
from datetime import timedelta
from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Notification, Payment, PremiumSubscription, Property, VerificationRequest, utcnow
from app.payments import mpesa
from app.payments.routes import MAX_CUSTOM_AMOUNT
from app.premium import services

REPORT_RESULTS = ("vacant", "occupied")  # "occupied" is shown as "Not vacant"
PHONE_PATTERN = re.compile(r"\+?[\d\s-]{9,20}")
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")

premium_bp = Blueprint("premium", __name__, url_prefix="/premium")


def renter_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_renter:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def active_subscription():
    subscription = (
        PremiumSubscription.query
        .filter_by(renter_id=current_user.user_id, status="active")
        .order_by(PremiumSubscription.expires_at.desc())
        .first()
    )
    if subscription and subscription.is_active:
        return subscription
    if subscription:
        subscription.status = "expired"
        db.session.commit()
    return None


@premium_bp.route("/")
@renter_required
def dashboard():
    services.enforce_deadlines()
    subscription = active_subscription()
    requests = (
        VerificationRequest.query
        .filter_by(renter_id=current_user.user_id)
        .order_by(VerificationRequest.requested_at.desc())
        .all()
    )
    return render_template("premium/dashboard.html", subscription=subscription, requests=requests)


def _chosen_amount(form, standard):
    """(amount, error) for the premium form: the standard price or the renter's own."""
    if form.get("amount_choice") != "custom":
        return standard, None
    try:
        amount = int(str(form.get("custom_amount", "")).replace(",", "").strip())
    except ValueError:
        amount = 0
    if not 1 <= amount <= MAX_CUSTOM_AMOUNT:
        return None, f"Enter an amount between KSh 1 and KSh {MAX_CUSTOM_AMOUNT:,}."
    return amount, None


@premium_bp.route("/subscribe", methods=["GET", "POST"])
@renter_required
def subscribe():
    subscription = active_subscription()
    if subscription:
        flash("Your premium subscription is already active.", "info")
        return redirect(url_for("premium.dashboard"))

    standard = current_app.config["PREMIUM_SUBSCRIPTION_AMOUNT"]
    demo = mpesa.is_demo(current_app.config)

    def form_page(phone, choice="standard", custom_amount="", status=200):
        return render_template(
            "premium/subscribe.html", amount=standard, phone=mpesa.local_part(phone),
            choice=choice, custom_amount=custom_amount, max_custom=MAX_CUSTOM_AMOUNT,
            demo=demo,
        ), status

    if request.method == "POST":
        form = request.form
        choice = "custom" if form.get("amount_choice") == "custom" else "standard"

        def refuse(message, status=400):
            flash(message, "danger")
            return form_page(form.get("phone", ""), choice, form.get("custom_amount", ""), status)

        amount, error = _chosen_amount(form, standard)
        if error:
            return refuse(error)
        phone = mpesa.normalise_phone(form.get("phone"))
        if not phone:
            return refuse("Enter a valid Safaricom number after +254, for example 712 345 678 or 112 345 678.")

        renter = current_user.ensure_renter_details()
        payment = Payment(
            renter_id=renter.renter_id,
            listing_id=None,
            amount=amount,
            modeofpayment="M-Pesa",
            purpose="premium_subscription",
            status="pending",
            phone=phone,
            simulated=demo,
        )
        db.session.add(payment)
        db.session.flush()
        if demo:
            # no Daraja keys configured: the whole site runs in demo mode
            payment.checkout_request_id = f"PREMIUM-DEMO-{payment.payment_id}"
            payment.merchant_request_id = payment.checkout_request_id
        else:
            try:
                result = mpesa.stk_push(
                    current_app.config, phone, amount,
                    reference=f"PREMIUM{payment.payment_id}",
                    description="Premium access",
                )
            except mpesa.MpesaError as exc:
                db.session.rollback()
                return refuse(f"The M-Pesa prompt could not be sent: {exc}", 502)
            payment.checkout_request_id = result["checkout_request_id"]
            payment.merchant_request_id = result["merchant_request_id"]
        db.session.commit()
        return redirect(url_for("payments.status", payment_id=payment.payment_id))

    return form_page(current_user.phonenumber or "")


@premium_bp.route("/verify/<int:listing_id>", methods=["POST"])
@renter_required
def request_verification(listing_id):
    listing = db.get_or_404(Property, listing_id)
    if not active_subscription():
        flash("An active premium subscription is required before requesting a vacancy check.", "warning")
        return redirect(url_for("premium.subscribe"))
    # overdue checks are moved on first, so they free up (or count against) verifiers
    services.enforce_deadlines()
    existing = VerificationRequest.query.filter_by(
        renter_id=current_user.user_id, listing_id=listing_id
    ).filter(VerificationRequest.status.in_(services.OPEN_STATUSES)).first()
    if existing:
        return redirect(url_for("premium.request_status", request_id=existing.request_id))

    # the least busy verifier who is neither this renter nor the unit's landlord
    verifier = services.pick_verifier(listing, current_user.user_id)
    if verifier is None:
        flash("No verifier is available right now. Please try again later.", "warning")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    verification = VerificationRequest(renter_id=current_user.user_id, listing_id=listing_id)
    services.assign(verification, verifier)
    db.session.add(verification)
    db.session.commit()
    flash(
        "A verified checker has been assigned. Their contact details are now available, "
        f"and their report is due within {services.deadline_hours()} hours.",
        "success",
    )
    return redirect(url_for("premium.request_status", request_id=verification.request_id))


@premium_bp.route("/requests/<int:request_id>")
@renter_required
def request_status(request_id):
    verification = db.get_or_404(VerificationRequest, request_id)
    if verification.renter_id != current_user.user_id:
        abort(403)
    services.enforce_deadlines()
    return render_template(
        "premium/request_status.html", verification=verification,
        deadline_hours=services.deadline_hours(),
    )


@premium_bp.route("/verifier")
@login_required
def verifier_queue():
    if not current_user.verifier_approved:
        abort(403)
    services.enforce_deadlines()
    # the check due soonest first
    requests = VerificationRequest.query.filter_by(
        verifier_id=current_user.user_id, status="assigned"
    ).order_by(VerificationRequest.due_at.asc()).all()
    return render_template(
        "premium/verifier_queue.html", requests=requests, now=utcnow(),
        soon=timedelta(hours=6),
    )


@premium_bp.route("/verifier/<int:request_id>", methods=["POST"])
@login_required
def submit_report(request_id):
    verification = db.get_or_404(VerificationRequest, request_id)
    if not current_user.verifier_approved:
        abort(403)
    was_mine = verification.verifier_id == current_user.user_id
    # a report that arrives after the deadline is not accepted: by then the
    # check has gone to someone else (or closed) and the renter has been told
    services.enforce_deadlines()
    if was_mine and (verification.verifier_id != current_user.user_id
                     or verification.status == "expired"):
        flash(
            "The deadline for that check passed before your report arrived, "
            "so it was handed on or closed.",
            "warning",
        )
        return redirect(url_for("premium.verifier_queue"))
    if verification.verifier_id != current_user.user_id:
        abort(403)
    listing = verification.listing
    if listing is not None and listing.landlord_id == current_user.user_id:
        abort(403)  # never a report on your own unit
    if verification.status != "assigned":
        flash("That check has already been reported.", "info")
        return redirect(url_for("premium.verifier_queue"))
    form = request.form
    status = form.get("verified_status", "")
    report = form.get("report", "").strip()
    contact_name = form.get("contact_name", "").strip() or current_user.full_name
    contact_phone = form.get("contact_phone", "").strip()
    contact_email = form.get("contact_email", "").strip()
    if status not in REPORT_RESULTS:
        flash("Choose whether the unit is vacant or not vacant.", "danger")
        return redirect(url_for("premium.verifier_queue"))
    if not report:
        flash("Write a short report of what you checked.", "danger")
        return redirect(url_for("premium.verifier_queue"))
    if not PHONE_PATTERN.fullmatch(contact_phone):
        flash("Enter a phone number the renter can reach you on.", "danger")
        return redirect(url_for("premium.verifier_queue"))
    if contact_email and not EMAIL_PATTERN.fullmatch(contact_email):
        flash(f"{contact_email} is not a valid email address.", "danger")
        return redirect(url_for("premium.verifier_queue"))
    verification.verified_status = status
    verification.report = report[:5000]
    verification.verifier_contact_name = contact_name[:120]
    verification.verifier_contact_phone = contact_phone[:20]
    verification.verifier_contact_email = contact_email[:120] or None
    verification.status = "completed"
    verification.completed_at = utcnow()
    apply_check_to_listing(listing, status)
    db.session.add(
        Notification(
            renter_id=verification.renter_id,
            listing_id=verification.listing_id,
            message=(
                f"Vacancy report ready for {listing.title if listing else 'the unit'}: "
                f"{verification.result_label}."
            )[:255],
            type=services.NOTIFICATION_TYPE,
            url=url_for("premium.request_status", request_id=verification.request_id),
        )
    )
    db.session.commit()
    flash("Verification report submitted.", "success")
    return redirect(url_for("premium.verifier_queue"))


def apply_check_to_listing(listing, verified_status):
    """Show a checker's finding on the listing itself, so every renter benefits.

    "vacant" and "occupied" become the unit's availability. "unavailable"
    means the checker could not confirm (no access, no answer) and changes
    nothing. A unit someone has already reserved with M-Pesa is never changed.
    """
    if listing is None or listing.availability_status == "reserved":
        return
    if verified_status in ("vacant", "occupied"):
        listing.availability_status = verified_status
