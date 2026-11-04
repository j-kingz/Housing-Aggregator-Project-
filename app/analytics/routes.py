"""Price analytics views: the dashboard and the per area breakdown."""

from flask import Blueprint, render_template, request

from app.analytics import services
from app.models import Area, Property

analytics_bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@analytics_bp.route("/")
def dashboard():
    """The price analytics dashboard.

    Shows the market picture across every neighbourhood the platform knows
    about: the headline numbers, the neighbourhood benchmarks, how rents are
    distributed and how prices have moved over time.
    """
    city = request.args.get("city", "").strip()

    query = Property.query.filter(Property.is_active.is_(True))
    if city:
        query = query.filter(Property.city == city)
    listings = query.all()

    benchmarks = services.area_benchmarks(city=city or None)
    distribution = services.rent_distribution(listings)
    stats = services.summarise(listings)

    # the price trend and the average rents are given per county and per home
    # type (bedsitter, 1 bedroom ... mansion); the page switches county with a
    # dropdown so counties are never mixed together
    all_listings = Property.query.filter(Property.is_active.is_(True)).all()
    trend_by_county = services.price_trend_by_county(all_listings)
    averages_by_county = services.average_rent_by_county(all_listings)
    county_names = list(trend_by_county)
    default_county = city if city in trend_by_county else (county_names[0] if county_names else "")
    per_sqft = services.rent_per_sqft_stats(listings)

    cities = sorted({listing.city for listing in listings if listing.city})
    areas_covered = len({(listing.address, listing.city) for listing in listings})

    # the cheapest and dearest neighbourhoods, each with at least three listings
    solid = [row for row in benchmarks if row["count"] >= 3]
    cheapest = solid[-3:][::-1] if solid else []
    dearest = solid[:3]

    return render_template(
        "analytics/dashboard.html",
        stats=stats,
        per_sqft=per_sqft,
        benchmarks=benchmarks,
        distribution=distribution,
        trend_by_county=trend_by_county,
        averages_by_county=averages_by_county,
        county_names=county_names,
        default_county=default_county,
        unit_types=services.UNIT_TYPES,
        cities=cities,
        city=city,
        cheapest=cheapest,
        dearest=dearest,
        areas_covered=areas_covered,
        snapshots=services.snapshot_history(city=city or None, limit=14),
    )


@analytics_bp.route("/area/<path:area_name>")
def area(area_name):
    """Everything known about one neighbourhood's market."""
    area_row = Area.query.filter(Area.name.ilike(area_name.strip())).first()
    city = request.args.get("city", "").strip()

    query = Property.query.filter(Property.is_active.is_(True))
    if area_row is not None:
        query = query.filter(Property.address == area_row.name)
        if area_row.city and not city:
            city = area_row.city
    else:
        query = query.filter(Property.address.ilike(area_name.strip()))
    if city:
        query = query.filter(Property.city == city)

    listings = query.order_by(Property.rentamount.asc()).all()
    if not listings:
        from flask import abort

        abort(404)

    stats = services.summarise(listings)
    distribution = services.rent_distribution(listings)
    trend = services.price_trend(city=city or None, area=area_row.name if area_row else area_name)

    by_bedrooms = {}
    for listing in listings:
        key = listing.bedrooms if listing.bedrooms is not None else 0
        by_bedrooms.setdefault(key, []).append(listing)
    bedroom_rows = []
    for bedrooms, group in sorted(by_bedrooms.items()):
        group_stats = services.summarise(group)
        bedroom_rows.append({"bedrooms": bedrooms, **group_stats})

    return render_template(
        "analytics/area.html",
        area=area_row,
        listings=listings,
        stats=stats,
        distribution=distribution,
        trend=trend,
        bedroom_rows=bedroom_rows,
        city=city,
    )
