from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.analytics import services as analytics
from app.extensions import db
from app.insights import services as insights
from app.models import Area, Favorite, Property
from app.places.services import resolve_area

listings_bp = Blueprint("listings", __name__, url_prefix="/listings")

CATEGORIES = ["Apartment", "Bedsitter", "Studio", "Maisonette", "Bungalow", "Townhouse"]
AVAILABILITY_STATUSES = {
    "vacant": "Vacant",
    "reserved": "Reserved (deposit paid)",
    "occupied": "Occupied",
    "unknown": "Availability unknown",
}


def landlord_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_landlord:
            flash("Only landlord accounts can manage listings.", "warning")
            return redirect(url_for("main.home"))
        # a property points at a landlord row, so make sure one exists
        current_user.ensure_landlord_details()
        return view(*args, **kwargs)
    return wrapper


def get_own_listing(listing_id):
    listing = db.get_or_404(Property, listing_id)
    if listing.landlord_id != current_user.user_id:
        abort(403)
    return listing


def read_form(form):
    """Returns (data, errors) from the add/edit listing form."""
    errors = []
    data = {
        "title": form.get("title", "").strip(),
        "category": form.get("category", ""),
        "city": form.get("city", "").strip(),
        "address": form.get("address", "").strip(),
        "buildingnumber": form.get("buildingnumber", "").strip() or None,
        "building_name": form.get("building_name", "").strip() or None,
        "room_number": form.get("room_number", "").strip() or None,
        "availability_status": form.get("availability_status", "unknown").strip() or "unknown",
    }

    if not data["title"]:
        errors.append("Give the listing a title.")
    if not data["city"]:
        errors.append("City is required.")
    if data["category"] not in CATEGORIES:
        errors.append("Pick a category from the list.")
    if data["availability_status"] not in AVAILABILITY_STATUSES:
        errors.append("Pick a valid availability status.")

    floor_raw = form.get("floor_number", "").strip()
    if not floor_raw:
        data["floor_number"] = None
    elif floor_raw.lstrip("-").isdigit() and -5 <= int(floor_raw) <= 200:
        data["floor_number"] = int(floor_raw)
    else:
        errors.append("Floor should be a whole number between -5 and 200.")

    try:
        rent = Decimal(form.get("rentamount", "").strip())
        # column is DECIMAL(10,2) so anything from 100 million up won't fit
        if not rent.is_finite() or rent <= 0 or rent >= 100_000_000:
            raise InvalidOperation
        data["rentamount"] = rent
    except InvalidOperation:
        errors.append("Rent has to be a number bigger than 0.")

    for field in ("bedrooms", "bathrooms"):
        raw = form.get(field, "").strip()
        if not raw:
            data[field] = None
        elif raw.isdigit() and int(raw) <= 50:
            data[field] = int(raw)
        else:
            errors.append(f"{field.capitalize()} should be a whole number.")

    # GPS: both numbers or neither
    lat_raw = form.get("latitude", "").strip()
    lng_raw = form.get("longitude", "").strip()
    data["latitude"] = data["longitude"] = None
    if lat_raw or lng_raw:
        try:
            lat, lng = Decimal(lat_raw), Decimal(lng_raw)
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise InvalidOperation
            data["latitude"], data["longitude"] = lat.quantize(Decimal("0.000001")), lng.quantize(Decimal("0.000001"))
        except InvalidOperation:
            errors.append("GPS needs a latitude between -90 and 90 and a longitude between -180 and 180.")

    return data, errors


def apply_location(data):
    """Link the listing to a known neighbourhood and settle its GPS point.

    The neighbourhood typed by the landlord is snapped to the closest real one
    so every listing shows up in the right searches and price analysis. An
    exact GPS point (from the map, the device or Google Places) is kept as
    "exact"; without one the centre of the neighbourhood is used and the
    listing is marked as approximate.
    """
    area, _ = resolve_area(data.get("address"))
    data["area_id"] = area.area_id if area else None
    if area is not None:
        data["address"] = area.name
        if not data.get("city"):
            data["city"] = area.city

    if data.get("latitude") is not None:
        data["gps_exact"] = True
    elif area is not None and area.latitude is not None:
        data["latitude"], data["longitude"] = area.latitude, area.longitude
        data["gps_exact"] = False
    else:
        data["gps_exact"] = False
    return data


def building_units(listing):
    """Every active unit in the same building as `listing`, grouped by floor."""
    if not listing.building_name:
        return []
    query = Property.query.filter(
        Property.is_active.is_(True),
        Property.building_name == listing.building_name,
    )
    if listing.area_id:
        query = query.filter(Property.area_id == listing.area_id)
    elif listing.address:
        query = query.filter(Property.address == listing.address)
    return query.order_by(Property.floor_number.desc(), Property.room_number).all()


@listings_bp.route("/building")
def building():
    """All the units of one building, floor by floor, with which are vacant."""
    name = request.args.get("name", "").strip()
    if not name:
        abort(404)
    units = Property.query.filter(
        Property.is_active.is_(True), Property.building_name == name
    ).order_by(Property.floor_number.desc(), Property.room_number).all()
    if not units:
        abort(404)

    floors = {}
    for unit in units:
        floors.setdefault(unit.floor_number, []).append(unit)
    ordered = sorted(
        floors.items(), key=lambda kv: (kv[0] is None, -(kv[0] if kv[0] is not None else 0))
    )
    vacant = sum(1 for u in units if u.availability_status == "vacant")
    first = next((u for u in units if u.latitude is not None), units[0])
    return render_template(
        "listings/building.html",
        name=name,
        floors=ordered,
        units=units,
        vacant=vacant,
        first=first,
    )


@listings_bp.route("/<int:listing_id>")
def detail(listing_id):
    """One listing, with the market context that tells you if it is fairly priced."""
    listing = db.get_or_404(Property, listing_id)

    # what the market around it looks like
    benchmarks = analytics.area_benchmarks()
    verdict = analytics.listing_verdict(listing, benchmarks)

    # the signed in renter's own numbers, when there are any
    insight = None
    renter = getattr(current_user, "renter", None)
    if renter is not None:
        area_lookup = {area.name.lower(): area for area in Area.query.all()}
        insight = insights.analyse_listing(
            listing, renter, area_lookup, renter.commute_mode or "matatu"
        )

    units = building_units(listing)

    # the renter's workplace, so the map can show how far this home is
    work_point = None
    saved = False
    if current_user.is_authenticated:
        saved = Favorite.query.filter_by(
            user_id=current_user.user_id, listing_id=listing.listing_id
        ).first() is not None
        work = insights.workplace_point(renter) if renter is not None else None
        if work is not None:
            work_point = {"lat": work[0], "lng": work[1], "label": work[2]}

    return render_template(
        "listings/detail.html",
        listing=listing,
        verdict=verdict,
        insight=insight,
        units=units,
        work_point=work_point,
        saved=saved,
        can_reserve=bool(listing.is_active) and listing.availability_status in ("vacant", "unknown"),
    )


@listings_bp.route("/mine")
@landlord_required
def my_listings():
    listings = (
        Property.query.filter_by(landlord_id=current_user.user_id)
        .order_by(Property.listingdate.desc())
        .all()
    )
    return render_template("listings/mine.html", listings=listings)


@listings_bp.route("/new", methods=["GET", "POST"])
@landlord_required
def create():
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("listings/form.html", listing=request.form,
                                       categories=CATEGORIES, availability_statuses=AVAILABILITY_STATUSES,
                                       editing=False), 400

        listing = Property(landlord_id=current_user.user_id, **apply_location(data))
        db.session.add(listing)
        db.session.commit()
        flash("Listing added.", "success")
        return redirect(url_for("listings.detail", listing_id=listing.listing_id))

    return render_template("listings/form.html", listing={}, categories=CATEGORIES,
                           availability_statuses=AVAILABILITY_STATUSES, editing=False)


@listings_bp.route("/<int:listing_id>/edit", methods=["GET", "POST"])
@landlord_required
def edit(listing_id):
    listing = get_own_listing(listing_id)

    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("listings/form.html", listing=request.form,
                                   categories=CATEGORIES, availability_statuses=AVAILABILITY_STATUSES,
                                   editing=True, listing_id=listing_id), 400

        for key, value in apply_location(data).items():
            setattr(listing, key, value)
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    return render_template("listings/form.html", listing=listing,
                           categories=CATEGORIES, availability_statuses=AVAILABILITY_STATUSES,
                           editing=True, listing_id=listing_id)


@listings_bp.route("/<int:listing_id>/delete", methods=["POST"])
@landlord_required
def delete(listing_id):
    listing = get_own_listing(listing_id)

    if listing.payments:
        flash("This listing has payments attached to it so it can't be deleted.", "warning")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    db.session.delete(listing)
    db.session.commit()
    flash("Listing deleted.", "info")
    return redirect(url_for("listings.my_listings"))
