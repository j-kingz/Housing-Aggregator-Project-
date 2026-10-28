"""The notification engine.

Proposal 3.3.1 "Automated System Notifications": the platform should monitor
newly gathered records and alert users when a listing fits their saved
criteria. This module does the matching; the routes just display the results.
"""

from app.models import Notification, Property, SearchAlert
from app.insights.services import parse_budget_range

MATCHED_TYPE = "listing"
BUDGET_TYPE = "budget"
BENCHMARK_TYPE = "benchmark"


def _area_matches(listing, area_name):
    """Does a listing sit in the neighbourhood the renter asked for?"""
    if not area_name:
        return True
    wanted = area_name.strip().lower()

    listing_area = (listing.address or "").strip().lower()
    if listing_area == wanted:
        return True
    if wanted and wanted in listing_area:
        return True

    listing_city = (listing.city or "").strip().lower()
    return bool(wanted) and wanted in listing_city


def listing_matches_alert(listing, alert):
    """Does a listing satisfy a saved search alert?"""
    if listing.rentamount is None:
        return False

    if alert.maxprice is not None and float(listing.rentamount) > float(alert.maxprice):
        return False

    if alert.minbedrooms is not None:
        bedrooms = listing.bedrooms or 0
        if bedrooms < alert.minbedrooms:
            return False

    if alert.minbathrooms is not None:
        bathrooms = listing.bathrooms or 0
        if bathrooms < alert.minbathrooms:
            return False

    return _area_matches(listing, alert.area)


def listing_matches_profile(listing, renter):
    """Does a listing fit the criteria saved on the renter's profile?"""
    if renter is None:
        return False

    min_price, max_price = parse_budget_range(renter.budgetrange)
    if max_price and float(listing.rentamount) > max_price:
        return False
    if min_price and float(listing.rentamount) < min_price:
        return False

    preferred = (renter.preferredlocation or "").strip()
    if preferred and not _area_matches(listing, preferred):
        return False

    return True


def _already_notified(renter_id, listing_id, notification_type, search_id=None):
    return (
        Notification.query.filter_by(
            renter_id=renter_id,
            listing_id=listing_id,
            type=notification_type,
            search_id=search_id,
        ).first()
        is not None
    )


def create_notification(renter, message, notification_type, listing=None, search_alert=None):
    """Store one notification for a renter."""
    notification = Notification(
        renter_id=renter.renter_id,
        search_id=search_alert.searchalert_id if search_alert else None,
        listing_id=listing.listing_id if listing else None,
        message=message[:255],
        type=notification_type,
        isread=False,
        url=(
            f"/listings/{listing.listing_id}" if listing else None
        ),
    )
    from app.extensions import db

    db.session.add(notification)
    return notification


def match_new_listings(listing_ids, only_new=True):
    """Check new listings against every saved alert and renter profile.

    Returns the number of notifications that were created.
    """
    if not listing_ids:
        return 0

    listings = Property.query.filter(Property.listing_id.in_(list(listing_ids))).all()
    if not listings:
        return 0

    alerts = SearchAlert.query.filter(SearchAlert.isactive.is_(True)).all()
    created = 0

    for listing in listings:
        for alert in alerts:
            if not listing_matches_alert(listing, alert):
                continue
            if _already_notified(
                alert.renter_id, listing.listing_id, MATCHED_TYPE, alert.searchalert_id
            ):
                continue

            message = (
                f"{listing.title} in {listing.address or listing.city or 'your area'} "
                f"for KSh {float(listing.rentamount):,.0f} matches your alert "
                f"({alert.describe()})."
            )
            renter = alert.renter
            create_notification(renter, message, MATCHED_TYPE, listing, alert)
            created += 1

        # profile based alerts, for renters who have not saved a search yet
        for renter in _renters_with_criteria():
            if not listing_matches_profile(listing, renter):
                continue
            if _already_notified(renter.renter_id, listing.listing_id, BUDGET_TYPE):
                continue

            message = (
                f"{listing.title} in {listing.address or listing.city or 'your area'} "
                f"for KSh {float(listing.rentamount):,.0f} fits your saved budget."
            )
            create_notification(renter, message, BUDGET_TYPE, listing)
            created += 1

    from app.extensions import db

    db.session.commit()
    return created


def _renters_with_criteria():
    """Renters who have saved a budget or a preferred area."""
    from app.models import RenterDetails

    return (
        RenterDetails.query.filter(
            (RenterDetails.budgetrange.isnot(None))
            | (RenterDetails.preferredlocation.isnot(None))
        )
        .all()
    )


def unread_count(renter_id):
    """How many unread notifications a renter has."""
    if not renter_id:
        return 0
    return Notification.query.filter_by(renter_id=renter_id, isread=False).count()


def recent_for(renter_id, limit=20):
    """A renter's notifications, newest first."""
    return (
        Notification.query.filter_by(renter_id=renter_id)
        .order_by(Notification.notification_id.desc())
        .limit(limit)
        .all()
    )
