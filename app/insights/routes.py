"""Personalised insight views: the budget analyser and distance mapping."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.analytics import services as analytics
from app.extensions import db
from app.insights import services
from app.models import Area, Property
from app.counties import find_county
from app.places.services import resolve_area

insights_bp = Blueprint("insights", __name__, url_prefix="/insights")


def _renter():
    """The renter details for the signed in account, if there are any."""
    if current_user.is_authenticated:
        return current_user.ensure_renter_details()
    return None


def _money(value):
    """A positive number from a form field, or None."""
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return None
    return number if 0 < number < 1_000_000_000 else None


def _save_profile(renter, form):
    """Store the analyser form on the renter. Returns a list of problems."""
    problems = []

    income_text = form.get("monthlyincome", "").strip()
    income = _money(income_text) if income_text else None
    if income_text and income is None:
        problems.append("Monthly income has to be a number, for example 80000.")
    renter.monthlyincome = income

    low, high = _money(form.get("budget_min")), _money(form.get("budget_max"))
    if low and high and low > high:
        low, high = high, low
    if low and high:
        renter.budgetrange = f"{low:.0f} - {high:.0f}"
    elif high:
        renter.budgetrange = f"{high:.0f}"
    elif low:
        renter.budgetrange = f"from {low:.0f}"
    else:
        renter.budgetrange = None

    # where they want to live: a neighbourhood, a county or any place in Kenya
    preferred = form.get("preferredlocation", "").strip()
    renter.preferred_lat = renter.preferred_lng = renter.preferred_county = None
    if preferred:
        area, _ = resolve_area(preferred)
        county_hit = find_county(form.get("preferred_county") or preferred)
        try:
            lat, lng = float(form.get("preferred_lat", "")), float(form.get("preferred_lng", ""))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                renter.preferred_lat, renter.preferred_lng = lat, lng
        except ValueError:
            pass
        if county_hit:
            renter.preferred_county = county_hit[0]
        elif area is not None:
            preferred = area.name
        elif renter.preferred_lat is None:
            problems.append(
                f"We could not find \"{preferred}\" in Kenya. Pick a county, neighbourhood or place from the suggestions."
            )
            preferred = ""
    renter.preferredlocation = preferred or None

    renter.commute_mode = form.get("commute_mode", "matatu").strip() or "matatu"
    if renter.commute_mode not in services.COMMUTE_MODES:
        renter.commute_mode = "matatu"

    # where they work or study: an exact point when picked from the map
    # suggestions, otherwise the centre of the neighbourhood they named
    workplace = form.get("workplace", "").strip()
    renter.workplace = workplace or None
    renter.workplace_lat = renter.workplace_lng = None
    renter.workplace_area_id = None
    renter.workplacearea = None
    if workplace:
        try:
            lat, lng = float(form.get("workplace_lat", "")), float(form.get("workplace_lng", ""))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                renter.workplace_lat, renter.workplace_lng = lat, lng
        except ValueError:
            pass
        area_id = form.get("workplace_area_id", "").strip()
        area = db.session.get(Area, int(area_id)) if area_id.isdigit() else None
        if area is None:
            area, _ = resolve_area(workplace)
        if area is not None:
            renter.workplace_area_id = area.area_id
            renter.workplacearea = area.name
        if renter.workplace_lat is None and area is None:
            problems.append(
                f"We could not place \"{workplace}\" on the map, so the distance cannot be worked out. "
                "Pick it from the suggestions."
            )
    return problems


@insights_bp.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    """What can I afford?

    The renter says what they earn, what they can pay, where they want to live
    and where they work. The page answers with the homes they can go for, each
    with the reasons, the distance to work, and which unit is vacant.
    """
    renter = _renter()
    if renter is None:
        flash(
            "This page is for renter accounts. Switch to a renter account to use it.",
            "warning",
        )
        return redirect(url_for("main.home"))

    if request.method == "POST":
        problems = _save_profile(renter, request.form)
        db.session.commit()
        for problem in problems:
            flash(problem, "warning")
        if not problems:
            flash("Saved. Here are the homes you can go for.", "success")
        return redirect(url_for("insights.budget"))

    beds = request.args.get("beds", type=int)
    result = services.recommend(renter, beds=beds)
    points, target_point = services.map_points(result["picks"], renter, url_for)
    min_price, max_price = result["budget_min"], result["budget_max"]

    return render_template(
        "insights/budget.html",
        renter=renter,
        result=result,
        beds=beds,
        commute_modes=services.COMMUTE_MODES,
        points=points,
        target_point=target_point,
        budget_min=min_price,
        budget_max=max_price,
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
