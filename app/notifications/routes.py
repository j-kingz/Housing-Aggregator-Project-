"""Saved search alerts and the notification inbox."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Area, Notification, SearchAlert
from app.notifications import services

notifications_bp = Blueprint("notifications", __name__)


def _renter():
    """The renter details for the signed in account, if there are any."""
    if current_user.is_authenticated:
        return current_user.ensure_renter_details()
    return None


@notifications_bp.route("/notifications")
@login_required
def inbox():
    """The renter's notification inbox."""
    renter = _renter()
    if renter is None:
        flash("Notifications are for renter accounts.", "warning")
        return redirect(url_for("main.home"))

    items = services.recent_for(renter.renter_id, limit=50)
    unread = services.unread_count(renter.renter_id)

    return render_template(
        "notifications/inbox.html", notifications=items, unread=unread
    )


@notifications_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id):
    """Mark one notification as read."""
    renter = _renter()
    notification = db.get_or_404(Notification, notification_id)
    if renter and notification.renter_id == renter.renter_id:
        notification.isread = True
        db.session.commit()
    return redirect(request.referrer or url_for("notifications.inbox"))


@notifications_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_read():
    """Mark every notification as read."""
    renter = _renter()
    if renter:
        Notification.query.filter_by(renter_id=renter.renter_id, isread=False).update(
            {"isread": True}
        )
        db.session.commit()
        flash("All notifications marked as read.", "info")
    return redirect(url_for("notifications.inbox"))


@notifications_bp.route("/alerts", methods=["GET", "POST"])
@login_required
def alerts():
    """Saved searches. A new alert is created from the search page."""
    renter = _renter()
    if renter is None:
        flash("Saved searches are for renter accounts.", "warning")
        return redirect(url_for("main.home"))

    if request.method == "POST":
        area = request.form.get("area", "").strip()
        max_price = request.form.get("maxprice", "").strip()
        min_bedrooms = request.form.get("minbedrooms", "").strip()
        min_bathrooms = request.form.get("minbathrooms", "").strip()
        frequency = request.form.get("frequency", "instant").strip() or "instant"

        errors = []
        if max_price:
            try:
                if float(max_price) <= 0:
                    raise ValueError
            except ValueError:
                errors.append("The maximum price has to be a number above zero.")
        if min_bedrooms and not min_bedrooms.isdigit():
            errors.append("Bedrooms has to be a whole number.")
        if min_bathrooms and not min_bathrooms.isdigit():
            errors.append("Bathrooms has to be a whole number.")

        if errors:
            for error in errors:
                flash(error, "danger")
            return redirect(url_for("notifications.alerts"))

        parts = []
        if area:
            parts.append(f"in {area}")
        if max_price:
            parts.append(f"up to KSh {float(max_price):,.0f}")
        if min_bedrooms:
            parts.append(f"{min_bedrooms}+ bedrooms")
        if min_bathrooms:
            parts.append(f"{min_bathrooms}+ bathrooms")

        alert = SearchAlert(
            renter_id=renter.renter_id,
            area=area or None,
            maxprice=float(max_price) if max_price else None,
            minbedrooms=int(min_bedrooms) if min_bedrooms else None,
            minbathrooms=int(min_bathrooms) if min_bathrooms else None,
            frequency=frequency,
            criteria=", ".join(parts) if parts else "any listing",
            isactive=True,
        )
        db.session.add(alert)
        db.session.commit()
        flash("Search alert saved. You will be told when a matching listing is added.", "success")
        return redirect(url_for("notifications.alerts"))

    saved = (
        SearchAlert.query.filter_by(renter_id=renter.renter_id)
        .order_by(SearchAlert.searchalert_id.desc())
        .all()
    )
    areas = Area.query.order_by(Area.city, Area.name).all()

    # how many listings match each saved alert right now
    for alert in saved:
        from app.models import Property

        query = Property.query.filter(Property.is_active.is_(True))
        if alert.area:
            query = query.filter(Property.address.ilike(f"%{alert.area}%"))
        if alert.maxprice is not None:
            query = query.filter(Property.rentamount <= alert.maxprice)
        if alert.minbedrooms is not None:
            query = query.filter(Property.bedrooms >= alert.minbedrooms)
        if alert.minbathrooms is not None:
            query = query.filter(Property.bathrooms >= alert.minbathrooms)
        alert.match_count = query.count()

    return render_template("notifications/alerts.html", alerts=saved, areas=areas)


@notifications_bp.route("/alerts/<int:alert_id>/delete", methods=["POST"])
@login_required
def delete_alert(alert_id):
    """Delete one of the renter's saved searches."""
    renter = _renter()
    alert = db.get_or_404(SearchAlert, alert_id)
    if renter and alert.renter_id == renter.renter_id:
        db.session.delete(alert)
        db.session.commit()
        flash("Search alert deleted.", "info")
    return redirect(url_for("notifications.alerts"))


@notifications_bp.route("/alerts/<int:alert_id>/toggle", methods=["POST"])
@login_required
def toggle_alert(alert_id):
    """Pause or resume a saved search."""
    renter = _renter()
    alert = db.get_or_404(SearchAlert, alert_id)
    if renter and alert.renter_id == renter.renter_id:
        alert.isactive = not bool(alert.isactive)
        db.session.commit()
        flash("Search alert updated.", "success")
    return redirect(url_for("notifications.alerts"))
