"""Personalised insight views: the budget analyser and distance mapping."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.analytics import services as analytics
from app.extensions import db
from app.insights import services
from app.models import Area, Property

insights_bp = Blueprint("insights", __name__, url_prefix="/insights")


def _renter():
    """The renter details for the signed in account, if there are any."""
    if current_user.is_authenticated:
        return current_user.ensure_renter_details()
    return None


@insights_bp.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    """The budget analyser.

    Renters save their income, budget and workplace here, then see every
    listing that fits with the rent-to-income ratio and the commute cost
    worked out for each one.
    """
    renter = _renter()
    if renter is None:
        flash(
            "The budget analyser is for renter accounts. Switch to a renter account to use it.",
            "warning",
        )
        return redirect(url_for("main.home"))

    areas = Area.query.order_by(Area.city, Area.name).all()

    if request.method == "POST":
        renter.monthlyincome = request.form.get("monthlyincome", "").strip() or None
        renter.preferredlocation = request.form.get("preferredlocation", "").strip() or None
        renter.budgetrange = request.form.get("budgetrange", "").strip() or None
        renter.workplace = request.form.get("workplace", "").strip() or None
        renter.commute_mode = request.form.get("commute_mode", "matatu").strip() or "matatu"

        # the workplace area is picked from the list
        area_id = request.form.get("workplace_area_id", "").strip()
        if area_id.isdigit():
            area = Area.query.get(int(area_id))
            renter.workplace_area_id = area.area_id if area else None
            renter.workplacearea = area.name if area else None
        else:
            renter.workplace_area_id = None
            renter.workplacearea = None

        db.session.commit()
        flash("Your budget profile has been saved.", "success")
        return redirect(url_for("insights.budget"))

    matches = services.matching_listings(renter)
    target = services.commute_targets(renter)

    # the listing closest to the workplace, for the summary card
    closest = None
    with_distance = [m for m in matches if m.get("distance_km") is not None]
    if with_distance:
        closest = min(with_distance, key=lambda m: m["distance_km"])

    min_price, max_price = services.parse_budget_range(renter.budgetrange)
    overall = services.rent_to_income(max_price or 0, renter.monthlyincome)

    # how the matched listings are spread by rent
    distribution = analytics.rent_distribution([entry["listing"] for entry in matches])

    points, target_point = services.map_points(matches, target)

    return render_template(
        "insights/budget.html",
        renter=renter,
        matches=matches,
        closest=closest,
        areas=areas,
        commute_modes=services.COMMUTE_MODES,
        target=target,
        target_point=target_point,
        points=points,
        distribution=distribution,
        budget_min=min_price,
        budget_max=max_price,
        overall=overall,
    )


@insights_bp.route("/listing/<int:listing_id>")
@login_required
def listing_insight(listing_id):
    """The insight card for a single listing, shown on its own page."""
    listing = db.get_or_404(Property, listing_id)
    renter = _renter()
    area_lookup = {area.name.lower(): area for area in Area.query.all()}
    mode = (renter.commute_mode if renter else "matatu") or "matatu"

    result = services.analyse_listing(listing, renter, area_lookup, mode)

    from app.analytics import services as analytics

    verdict = analytics.listing_verdict(listing, analytics.area_benchmarks())

    return render_template(
        "insights/listing.html",
        listing=listing,
        insight=result,
        verdict=verdict,
        commute_mode=mode,
    )
