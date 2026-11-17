from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.analytics import services as analytics
from app.extensions import db
from app.counties import COUNTIES, find_county
from app.models import Area, Favorite, Property, ScrapingSource
from app.places.services import county_for_place, resolve_area

main_bp = Blueprint("main", __name__)

CATEGORIES = ["Apartment", "Bedsitter", "Studio", "Maisonette", "Bungalow", "Townhouse"]

SORTS = {
    "newest": "Newest first",
    "price_low": "Price: low to high",
    "price_high": "Price: high to low",
    "beds": "Most bedrooms",
    "nearest": "Nearest to the place I picked",
}

AVAILABILITY = ("vacant", "reserved", "occupied", "unknown")


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value):
    try:
        return float(value)
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
    county_text = request.args.get("county", "").strip()
    place_lat = to_float(request.args.get("place_lat"))
    place_lng = to_float(request.args.get("place_lng"))
    area = request.args.get("area", "").strip()
    building = request.args.get("building", "").strip()
    floor = to_int(request.args.get("floor"))
    category = request.args.get("category", "").strip()
    max_price = to_int(request.args.get("max_price"))
    bedrooms = to_int(request.args.get("bedrooms"))
    source = request.args.get("source", "").strip()
    availability = request.args.get("availability", "").strip()
    sort = request.args.get("sort", "").strip()
    page = to_int(request.args.get("page")) or 1

    # the county is filled in from the place, so only the place and bedrooms are asked for
    if request.args.get("search") == "1" and (not location or bedrooms is None):
        flash("Choose a place and the number of bedrooms before searching.", "warning")
        return redirect(url_for("main.home"))

    query = Property.query.filter(Property.is_active.is_(True))

    notices = []

    county = ""
    found_county = find_county(county_text) or find_county(location)
    if found_county:
        county = found_county[0]
        # "Nairobi County" in the Where box means the whole county, not a text search
        if find_county(location):
            location = ""
    elif location:
        # the browser could not fill the county in (typed, not picked):
        # use the county of a known neighbourhood or building, if it is one
        county = county_for_place(location) or ""
    if location:
        like = f"%{location}%"
        location_matches = [
            Property.city.ilike(like),
            Property.address.ilike(like),
            Property.building_name.ilike(like),
            Property.buildingnumber.ilike(like),
            Property.title.ilike(like),
        ]
        if place_lat is not None and place_lng is not None:
            # about 2.5 km around the place that was picked on the map
            location_matches.append(
                (Property.latitude.between(place_lat - 0.025, place_lat + 0.025))
                & (Property.longitude.between(place_lng - 0.025, place_lng + 0.025))
            )
        query = query.filter(or_(*location_matches))

    if county:
        # every listing in a neighbourhood of this county, or in a city of that name
        in_county = [a.area_id for a in Area.query.filter(func.lower(Area.county) == county.lower())]
        query = query.filter(or_(Property.area_id.in_(in_county), Property.city.ilike(county)))

    if area:
        # the box suggests real neighbourhoods; if the text is a near miss we
        # use the closest one and say so instead of showing an empty page
        found, corrected = resolve_area(area)
        if found is None:
            notices.append(f"We don't know a neighbourhood called \"{area}\", so it was ignored.")
            area = ""
        else:
            if corrected:
                notices.append(f"Showing {found.name} (you typed \"{area}\").")
            area = found.name
            query = query.filter(
                or_(Property.address.ilike(area), Property.area_id == found.area_id)
            )

    if building:
        query = query.filter(Property.building_name.ilike(f"%{building}%"))
    if floor is not None:
        query = query.filter(Property.floor_number == floor)
    if category:
        query = query.filter(Property.category == category)
    if max_price:
        query = query.filter(Property.rentamount <= max_price)
    area_filter_count = query.order_by(None).count() if area else None
    if bedrooms is not None:
        query = query.filter(Property.bedrooms == bedrooms)
    if source:
        source_id = _source_id(source)
        conditions = [Property.source_name == source]
        if source_id is not None:
            conditions.append(Property.source_id == source_id)
        query = query.filter(or_(*conditions))

    # how many homes are vacant / not confirmed under every other filter (for the tabs)
    counted = dict(
        query.order_by(None)
        .with_entities(Property.availability_status, func.count(Property.listing_id))
        .group_by(Property.availability_status)
        .all()
    )
    avail_counts = {
        "all": sum(counted.values()),
        "vacant": counted.get("vacant", 0),
        "unknown": counted.get("unknown", 0) + counted.get(None, 0),
    }
    if availability in AVAILABILITY:
        query = query.filter(Property.availability_status == availability)

    has_point = place_lat is not None and place_lng is not None
    if sort not in SORTS or (sort == "nearest" and not has_point):
        sort = "nearest" if has_point else "newest"

    if sort == "nearest":
        query = query.filter(Property.latitude.isnot(None)).order_by(
            (Property.latitude - place_lat) * (Property.latitude - place_lat)
            + (Property.longitude - place_lng) * (Property.longitude - place_lng)
        )
    elif sort == "price_low":
        query = query.order_by(Property.rentamount.asc(), Property.listing_id.desc())
    elif sort == "price_high":
        query = query.order_by(Property.rentamount.desc(), Property.listing_id.desc())
    elif sort == "beds":
        query = query.order_by(Property.bedrooms.desc(), Property.rentamount.asc())
    else:
        query = query.order_by(Property.listingdate.desc(), Property.listing_id.desc())

    # every matching home with a GPS point goes on the map, not only this page
    map_rows = (
        query.order_by(None)
        .filter(Property.latitude.isnot(None))
        .with_entities(
            Property.listing_id, Property.title, Property.rentamount,
            Property.latitude, Property.longitude, Property.availability_status,
        )
        .limit(400)
        .all()
    )
    map_points = [
        {
            "lat": float(r.latitude), "lng": float(r.longitude),
            "label": f"{r.title} - KSh {float(r.rentamount):,.0f}"
                     + (" (vacant)" if r.availability_status == "vacant" else ""),
            "url": url_for("listings.detail", listing_id=r.listing_id),
        }
        for r in map_rows
    ]

    pagination = query.paginate(page=page, per_page=12, error_out=False)
    listings = pagination.items
    if not listings and bedrooms is not None and area:
        bedroom_label = "bedsitter/studio" if bedrooms == 0 else (
            f"{bedrooms}-bedroom"
        )
        if area_filter_count:
            notices.append(
                f"No {bedroom_label} homes are currently listed in {area}. "
                "Try another bedroom selection or neighbourhood."
            )
        else:
            notices.append(
                f"No homes are currently listed in {area}. "
                "Try another neighbourhood."
            )

    # the market figures for the whole search, used for the summary line
    benchmarks = analytics.area_benchmarks()
    verdicts = {}
    for listing in listings:
        verdicts[listing.listing_id] = analytics.listing_verdict(listing, benchmarks)

    favorite_ids = set()
    if current_user.is_authenticated:
        favorite_ids = {
            f.listing_id for f in Favorite.query.filter_by(user_id=current_user.user_id).all()
        }

    areas = Area.query.order_by(Area.city, Area.name).all()
    sources = (
        ScrapingSource.query.filter(
            ScrapingSource.enabled.is_(True), ScrapingSource.profile != "fixture"
        )
        .order_by(ScrapingSource.name)
        .all()
    )

    # numbers and shortcuts for the top of the page
    stats = {
        "homes": Property.query.filter(Property.is_active.is_(True)).count(),
        "vacant": Property.query.filter(
            Property.is_active.is_(True), Property.availability_status == "vacant"
        ).count(),
        # websites that really contributed listings (the offline sample is not one)
        "sources": db.session.query(func.count(func.distinct(Property.source_name)))
        .filter(
            Property.is_active.is_(True),
            Property.source_name.isnot(None),
            Property.source_name != "Sample fixture",
        )
        .scalar(),
    }
    popular = (
        db.session.query(Property.address, func.count(Property.listing_id))
        .filter(Property.is_active.is_(True), Property.area_id.isnot(None))
        .group_by(Property.address)
        .order_by(func.count(Property.listing_id).desc())
        .limit(8)
        .all()
    )

    return render_template(
        "home.html",
        stats=stats,
        counties=COUNTIES,
        popular=popular,
        county=county,
        location_label=(county + " County") if county and not location else location,
        avail_counts=avail_counts,
        map_points=map_points,
        favorite_ids=favorite_ids,
        listings=listings,
        pagination=pagination,
        verdicts=verdicts,
        location=location,
        place_lat=place_lat if place_lat is not None else "",
        place_lng=place_lng if place_lng is not None else "",
        area=area,
        building=building,
        floor=floor if floor is not None else "",
        notices=notices,
        category=category,
        categories=CATEGORIES,
        max_price=max_price or "",
        bedrooms=bedrooms if bedrooms is not None else "",
        source=source,
        availability=availability,
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

        if user.landlord:
            user.landlord.businessname = request.form.get("businessname", "").strip() or None

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    return render_template("profile.html", user=user)


@main_bp.route("/how-it-works")
def help():
    """A plain-language guide to what the platform does and how to use it."""
    return render_template("help.html")
