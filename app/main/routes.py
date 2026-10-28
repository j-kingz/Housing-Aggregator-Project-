from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.analytics import services as analytics
from app.extensions import db
from app.models import Area, Property, ScrapingSource

main_bp = Blueprint("main", __name__)

CATEGORIES = ["Apartment", "Bedsitter", "Studio", "Maisonette", "Bungalow", "Townhouse"]

SORTS = {
    "newest": "Newest first",
    "price_low": "Price: low to high",
    "price_high": "Price: high to low",
    "beds": "Most bedrooms",
}


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@main_bp.route("/")
def home():
    """The centralized search portal.

    Every listing the platform holds, from every source, filtered by area,
    budget and bedrooms. This is the single view that replaces visiting
    several sites.
    """
    location = request.args.get("location", "").strip()
    area = request.args.get("area", "").strip()
    category = request.args.get("category", "").strip()
    max_price = to_int(request.args.get("max_price"))
    bedrooms = to_int(request.args.get("bedrooms"))
    source = request.args.get("source", "").strip()
    sort = request.args.get("sort", "newest").strip() or "newest"
    page = to_int(request.args.get("page")) or 1

    query = Property.query.filter(Property.is_active.is_(True))

    if location:
        like = f"%{location}%"
        query = query.filter(
            or_(Property.city.ilike(like), Property.address.ilike(like))
        )
    if area:
        query = query.filter(Property.address.ilike(area))
    if category:
        query = query.filter(Property.category == category)
    if max_price:
        query = query.filter(Property.rentamount <= max_price)
    if bedrooms:
        query = query.filter(Property.bedrooms >= bedrooms)
    if source:
        source_id = _source_id(source)
        conditions = [Property.source_name == source]
        if source_id is not None:
            conditions.append(Property.source_id == source_id)
        query = query.filter(or_(*conditions))

    if sort == "price_low":
        query = query.order_by(Property.rentamount.asc(), Property.listing_id.desc())
    elif sort == "price_high":
        query = query.order_by(Property.rentamount.desc(), Property.listing_id.desc())
    elif sort == "beds":
        query = query.order_by(
            Property.bedrooms.desc(), Property.rentamount.asc()
        )
    else:
        query = query.order_by(Property.listingdate.desc(), Property.listing_id.desc())

    pagination = query.paginate(page=page, per_page=12, error_out=False)
    listings = pagination.items

    # the market figures for the whole search, used for the summary line
    benchmarks = analytics.area_benchmarks()
    verdicts = {}
    for listing in listings:
        verdicts[listing.listing_id] = analytics.listing_verdict(listing, benchmarks)

    areas = Area.query.order_by(Area.city, Area.name).all()
    sources = (
        ScrapingSource.query.filter(ScrapingSource.enabled.is_(True))
        .order_by(ScrapingSource.name)
        .all()
    )

    return render_template(
        "home.html",
        listings=listings,
        pagination=pagination,
        verdicts=verdicts,
        location=location,
        area=area,
        category=category,
        categories=CATEGORIES,
        max_price=max_price or "",
        bedrooms=bedrooms or "",
        source=source,
        sources=sources,
        sort=sort,
        sorts=SORTS,
        areas=areas,
    )


def _source_id(name):
    """The id of a scraping source by name, or None."""
    if not name:
        return None
    row = ScrapingSource.query.filter(ScrapingSource.name == name).first()
    return row.source_id if row else None


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """The user's profile, including the budget details used by the analyser."""
    user = current_user

    if request.method == "POST":
        firstname = request.form.get("firstname", "").strip()
        lastname = request.form.get("lastname", "").strip()
        if not firstname or not lastname:
            flash("First and last name can't be empty.", "danger")
            return redirect(url_for("main.profile"))

        user.firstname = firstname
        user.lastname = lastname
        user.phonenumber = request.form.get("phonenumber", "").strip() or None

        if user.renter:
            user.renter.preferredlocation = request.form.get("preferredlocation", "").strip() or None
            user.renter.budgetrange = request.form.get("budgetrange", "").strip() or None
            income = request.form.get("monthlyincome", "").strip()
            if income:
                try:
                    user.renter.monthlyincome = float(income)
                except ValueError:
                    flash("Monthly income has to be a number.", "danger")
                    return redirect(url_for("main.profile"))
            else:
                user.renter.monthlyincome = None
            user.renter.workplace = request.form.get("workplace", "").strip() or None
            user.renter.commute_mode = request.form.get("commute_mode", "matatu").strip() or "matatu"

            # the workplace neighbourhood is picked from the list, and the
            # name is kept alongside it so the text still shows on the page
            workplace_area_id = request.form.get("workplace_area_id", "").strip()
            if workplace_area_id.isdigit():
                area = Area.query.get(int(workplace_area_id))
                user.renter.workplace_area_id = area.area_id if area else None
                user.renter.workplacearea = area.name if area else None
            else:
                user.renter.workplace_area_id = None
                user.renter.workplacearea = None
        if user.landlord:
            user.landlord.businessname = request.form.get("businessname", "").strip() or None

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    areas = Area.query.order_by(Area.city, Area.name).all()
    return render_template("profile.html", user=user, areas=areas)
