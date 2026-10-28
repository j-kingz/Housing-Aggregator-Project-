"""Personalised insights for a renter.

This covers the "Personalized Profile Insights" requirement (proposal 3.3.1):
rent-to-income comparisons, commuting cost estimates and distance mapping to
a workplace or school.

The travel figures are estimates based on published Nairobi fare bands and
average traffic speeds. They are meant to help a renter compare areas, not
to replace a route planner, and the interface says so.
"""

import math

from app.models import Area, Property

EARTH_RADIUS_KM = 6371.0088

# Travel modes: base fare in KSh, cost per kilometre, average speed in km/h.
# These are the assumptions behind every commute estimate the platform shows.
COMMUTE_MODES = {
    "matatu": {
        "label": "Matatu",
        "base_fare": 30.0,
        "per_km": 3.0,
        "speed_kmh": 18.0,
        "note": "Shared taxi, the usual option for most Nairobi routes",
    },
    "bus": {
        "label": "Bus",
        "base_fare": 40.0,
        "per_km": 2.0,
        "speed_kmh": 20.0,
        "note": "City bus, cheapest option during off peak hours",
    },
    "car": {
        "label": "Car",
        "base_fare": 0.0,
        "per_km": 90.0,
        "speed_kmh": 30.0,
        "note": "Fuel and servicing cost per kilometre",
    },
    "boda": {
        "label": "Boda",
        "base_fare": 40.0,
        "per_km": 8.0,
        "speed_kmh": 25.0,
        "note": "Motorbike taxi, fastest option in heavy traffic",
    },
    "walk": {
        "label": "Walking",
        "base_fare": 0.0,
        "per_km": 0.0,
        "speed_kmh": 4.5,
        "note": "On foot",
    },
}

# The share of a monthly income that is considered safe to spend on rent
AFFORDABLE_RATIO = 30.0
STRETCH_RATIO = 40.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Straight line distance between two points in kilometres."""
    if None in (lat1, lon1, lat2, lon2):
        return None

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def commute_estimate(distance_km, mode="matatu"):
    """Estimated cost and travel time for a trip of the given distance."""
    settings = COMMUTE_MODES.get(mode) or COMMUTE_MODES["matatu"]
    if distance_km is None:
        return {
            "mode": mode,
            "label": settings["label"],
            "distance_km": None,
            "cost": None,
            "minutes": None,
            "note": settings["note"],
        }

    # a real route is longer than the straight line, allow for detours
    route_km = distance_km * 1.3
    cost = settings["base_fare"] + settings["per_km"] * route_km
    minutes = (route_km / settings["speed_kmh"]) * 60

    return {
        "mode": mode,
        "label": settings["label"],
        "distance_km": distance_km,
        "route_km": route_km,
        "cost": cost,
        "minutes": minutes,
        "note": settings["note"],
    }


def rent_to_income(rent, income):
    """How much of a monthly income the rent would take.

    Returns the percentage and a plain language verdict. The 30 percent
    figure is the widely used affordability guideline for housing.
    """
    if not income:
        return {
            "ratio_percent": None,
            "verdict": "unknown",
            "label": "Add your income to see this",
            "affordable": None,
        }

    income = float(income)
    rent = float(rent or 0)
    if income <= 0:
        return {
            "ratio_percent": None,
            "verdict": "unknown",
            "label": "Add your income to see this",
            "affordable": None,
        }

    ratio = (rent / income) * 100

    if ratio <= AFFORDABLE_RATIO:
        verdict, label = "affordable", "Comfortable"
    elif ratio <= STRETCH_RATIO:
        verdict, label = "stretch", "A stretch"
    else:
        verdict, label = "expensive", "Beyond reach"

    return {
        "ratio_percent": ratio,
        "verdict": verdict,
        "label": label,
        "affordable": ratio <= AFFORDABLE_RATIO,
        "remaining": income - rent,
    }


def parse_budget_range(text):
    """Read "20,000 - 30,000" into (20000, 30000)."""
    if not text:
        return None, None
    import re

    numbers = re.findall(r"[\d][\d,\.]*", str(text))
    values = []
    for number in numbers:
        cleaned = number.replace(",", "")
        try:
            values.append(float(cleaned))
        except ValueError:
            continue

    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return min(values), max(values)


def _coordinates(area_row):
    if area_row is None or area_row.latitude is None or area_row.longitude is None:
        return None, None
    return float(area_row.latitude), float(area_row.longitude)


def listing_coordinates(listing, area_lookup):
    """Coordinates for a listing: its own, or the ones of its neighbourhood."""
    if listing.latitude is not None and listing.longitude is not None:
        return float(listing.latitude), float(listing.longitude)
    area = area_lookup.get((listing.address or "").strip().lower())
    return _coordinates(area)


def analyse_listing(listing, renter=None, area_lookup=None, commute_mode="matatu"):
    """Everything the platform knows about one listing for one renter."""
    area_lookup = area_lookup or {}
    result = {
        "distance_km": None,
        "commute": None,
        "rent_to_income": None,
        "monthly_total": None,
    }

    if renter is not None:
        result["rent_to_income"] = rent_to_income(listing.rentamount, renter.monthlyincome)

    workplace = None
    if renter is not None:
        if renter.workplace_area_id:
            workplace = Area.query.get(renter.workplace_area_id)
        if workplace is None and renter.workplacearea:
            workplace = area_lookup.get(renter.workplacearea.strip().lower())

    lat, lon = listing_coordinates(listing, area_lookup)
    if workplace is not None:
        work_lat, work_lon = _coordinates(workplace)
        distance = haversine_km(lat, lon, work_lat, work_lon)
        if distance is not None:
            result["distance_km"] = distance
            result["commute"] = commute_estimate(distance, commute_mode)
            result["workplace"] = workplace.name

    if result["rent_to_income"]:
        ratio = result["rent_to_income"].get("ratio_percent")
        if ratio is not None:
            # a rough rule of thumb: utilities and food take about 30 percent
            result["monthly_total"] = float(listing.rentamount) + (float(listing.rentamount) * 0.3)

    return result


def find_area(name):
    """Look an area up by name, case insensitively."""
    if not name:
        return None
    return Area.query.filter(Area.name.ilike(name.strip())).first()


def commute_targets(renter):
    """The workplace area a renter travels to, if we know it."""
    if renter is None:
        return None
    if renter.workplace_area_id:
        area = Area.query.get(renter.workplace_area_id)
        if area is not None:
            return area
    if renter.workplacearea:
        return find_area(renter.workplacearea)
    return None


def matching_listings(renter, limit=40):
    """Listings that fit the renter's saved criteria, with insights attached.

    The criteria come from the renter profile (preferred area and budget
    range) and from their saved search alerts.
    """
    if renter is None:
        return []

    min_price, max_price = parse_budget_range(renter.budgetrange)
    preferred = (renter.preferredlocation or "").strip()

    query = Property.query.filter(Property.is_active.is_(True))

    if max_price:
        query = query.filter(Property.rentamount <= max_price)
    if min_price:
        query = query.filter(Property.rentamount >= min_price)
    if preferred:
        from sqlalchemy import or_

        like = f"%{preferred}%"
        query = query.filter(
            or_(Property.address.ilike(like), Property.city.ilike(like))
        )

    listings = query.order_by(Property.rentamount.asc()).limit(limit).all()

    area_lookup = {area.name.lower(): area for area in Area.query.all()}
    mode = renter.commute_mode or "matatu"

    # the market figures each listing is compared against
    from app.analytics import services as analytics

    benchmarks = analytics.area_benchmarks()

    results = []
    for listing in listings:
        insights = analyse_listing(listing, renter, area_lookup, mode)
        insights["verdict"] = analytics.listing_verdict(listing, benchmarks)
        results.append({"listing": listing, **insights})

    return results


def map_points(listings_with_insights, target_area=None):
    """Points for the distance map, with the workplace as the reference point."""
    points = []
    for entry in listings_with_insights:
        listing = entry["listing"]
        lat, lon = listing_coordinates(listing, {a.name.lower(): a for a in Area.query.all()})
        if lat is None:
            continue
        points.append(
            {
                "latitude": lat,
                "longitude": lon,
                "label": listing.title,
                "listing_id": listing.listing_id,
                "distance_km": entry.get("distance_km"),
                "rent": float(listing.rentamount),
            }
        )

    target = None
    if target_area is not None:
        target_lat, target_lon = _coordinates(target_area)
        if target_lat is not None:
            target = {
                "latitude": target_lat,
                "longitude": target_lon,
                "label": target_area.name,
            }

    return points, target
