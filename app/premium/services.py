"""Choosing verifiers for vacancy checks and enforcing their deadlines.

A check is assigned to the free verifier with the fewest open checks and must
be reported on within VERIFICATION_DEADLINE_HOURS. When that time passes the
check goes to a different verifier (at most VERIFICATION_MAX_REASSIGNMENTS
times); if nobody else is free, or it has been passed on enough times, it
expires and the renter is told they can ask again.

There is no task scheduler, so enforce_deadlines() is called whenever a
premium page is opened and on every run of the background worker. It is safe
to call as often as you like.
"""

from datetime import timedelta

from flask import current_app
from sqlalchemy import func

from app.extensions import db
from app.models import Notification, User, VerificationRequest, utcnow

OPEN_STATUSES = ("assigned", "in_progress")
NOTIFICATION_TYPE = "verification"


def deadline_hours():
    return current_app.config.get("VERIFICATION_DEADLINE_HOURS", 24)


def pick_verifier(listing, renter_id, exclude_ids=()):
    """The free verifier with the fewest open checks, or None.

    Never the renter who asked, never the listing's landlord (the report has
    to be independent) and never anyone in exclude_ids.
    """
    open_jobs = (
        db.session.query(
            VerificationRequest.verifier_id,
            func.count(VerificationRequest.request_id).label("open_count"),
        )
        .filter(VerificationRequest.status.in_(OPEN_STATUSES))
        .group_by(VerificationRequest.verifier_id)
        .subquery()
    )
    excluded = {renter_id, *exclude_ids}
    if listing is not None and listing.landlord_id is not None:
        excluded.add(listing.landlord_id)
    excluded.discard(None)

    return (
        User.query.filter_by(verifier_approved=True, verifier_available=True, status="active")
        .filter(User.user_id.notin_(excluded))
        .outerjoin(open_jobs, open_jobs.c.verifier_id == User.user_id)
        .order_by(func.coalesce(open_jobs.c.open_count, 0), User.user_id)
        .first()
    )


def assign(verification, verifier, now=None):
    """Give a check to a verifier and start its deadline."""
    now = now or utcnow()
    verification.verifier_id = verifier.user_id
    verification.status = "assigned"
    verification.assigned_at = now
    verification.due_at = now + timedelta(hours=deadline_hours())


def _notify(verification, message):
    db.session.add(
        Notification(
            renter_id=verification.renter_id,
            listing_id=verification.listing_id,
            message=message[:255],
            type=NOTIFICATION_TYPE,
            # a plain path: this also runs in the worker, where url_for has no request
            url=f"/premium/requests/{verification.request_id}",
        )
    )


def enforce_deadlines(now=None):
    """Reassign or expire every check whose deadline has passed.

    Returns {"reassigned": n, "expired": n}.
    """
    now = now or utcnow()
    hours = deadline_hours()
    max_reassign = current_app.config.get("VERIFICATION_MAX_REASSIGNMENTS", 2)

    # checks assigned before deadlines existed get one counted from when they
    # were assigned
    for old in VerificationRequest.query.filter(
        VerificationRequest.status == "assigned", VerificationRequest.due_at.is_(None)
    ):
        start = old.assigned_at or old.requested_at or now
        old.due_at = start + timedelta(hours=hours)

    overdue = (
        VerificationRequest.query.filter(
            VerificationRequest.status == "assigned", VerificationRequest.due_at <= now
        )
        .order_by(VerificationRequest.due_at)
        .all()
    )

    counts = {"reassigned": 0, "expired": 0}
    for check in overdue:
        title = check.listing.title if check.listing else "the unit"
        late_verifier = check.verifier_id
        replacement = None
        if (check.reassign_count or 0) < max_reassign:
            replacement = pick_verifier(check.listing, check.renter_id, exclude_ids={late_verifier})

        if replacement is not None:
            assign(check, replacement, now)
            check.reassign_count = (check.reassign_count or 0) + 1
            _notify(
                check,
                f"Your vacancy check for {title} was not done in time, so it has been "
                f"given to another checker, {replacement.full_name}.",
            )
            counts["reassigned"] += 1
        else:
            check.status = "expired"
            check.completed_at = now
            _notify(
                check,
                f"Your vacancy check for {title} could not be done in time and has been "
                "closed. You can request a new check from the listing page.",
            )
            counts["expired"] += 1

    db.session.commit()
    if counts["reassigned"] or counts["expired"]:
        current_app.logger.info(
            "Vacancy check deadlines: %s reassigned, %s expired",
            counts["reassigned"], counts["expired"],
        )
    return counts
