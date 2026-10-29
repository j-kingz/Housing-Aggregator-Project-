"""Personalised insights for a renter.

This covers the "Personalized Profile Insights" requirement (proposal 3.3.1):
rent-to-income comparisons, commuting cost estimates and distance mapping to
a workplace or school.

The travel figures are estimates based on published Nairobi fare bands and
average traffic speeds. They are meant to help a renter compare areas, not
to replace a route planner, and the interface says so.
"""

import math
import re

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


_MONEY_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\b", re.IGNORECASE)
_SUFFIX = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "million": 1_000_000}
_MINIMUM_WORDS = re.compile(r"\b(from|above|over|min|minimum|at least|more than)\b")


def parse_budget_range(text):
    """Read what a person wrote about their budget into (minimum, maximum).

    "20,000 - 30,000"                  -> (20000, 30000)
    "50k", "under 50000" or "25,000"   -> (None, 50000)   one number is a ceiling
    "from 30000"                       -> (30000, None)
    """
    if not text:
        return None, None
    lowered = str(text).lower()
    values = []
    for match in _MONEY_RE.finditer(lowered):
        try:
            number = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        number *= _SUFFIX.get((match.group(2) or "").lower(), 1)
        values.append(number)

    if not values:
        return None, None
    if len(values) == 1:
        if _MINIMUM_WORDS.search(lowered):
            return values[0], None
        return None, values[0]
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


def workplace_point(renter):
    """(latitude, longitude, name) of where the renter works or studies, or None."""
    if renter is None:
        return None
    if renter.workplace_lat is not None and renter.workplace_lng is not None:
        return float(renter.workplace_lat), float(renter.workplace_lng), renter.workplace or "your workplace"
    area = commute_targets(renter)
    if area is not None and area.latitude is not None:
        return float(area.latitude), float(area.longitude), renter.workplace or area.name
    return None


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

    work = workplace_point(renter)
    lat, lon = listing_coordinates(listing, area_lookup)
    if work is not None:
        distance = haversine_km(lat, lon, work[0], work[1])
        if distance is not None:
            result["distance_km"] = distance
            result["commute"] = commute_estimate(distance, commute_mode)
            result["workplace"] = work[2]

    ratio = (result["rent_to_income"] or {}).get("ratio_percent")
    if ratio is not None:
        # a rough rule of thumb: utilities and food take about 30 percent
        result["monthly_total"] = float(listing.rentamount) * 1.3

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


# A working month has about 22 days and each one is a trip there and back
WORKING_DAYS = 22

# Share of income that rent plus travel together should stay under
TOTAL_COMFORT_RATIO = 40.0


def _pool(lo, hi, beds, limit=600):
    """Open units (vacant or not yet confirmed) inside a rent window."""
    query = Property.query.filter(
        Property.is_active.is_(True),
        Property.availability_status.in_(("vacant", "unknown")),
    )
    if lo:
        query = query.filter(Property.rentamount >= lo)
    if hi:
        query = query.filter(Property.rentamount <= hi)
    if beds:
        query = query.filter(Property.bedrooms >= beds)
    return query.order_by(Property.rentamount.asc()).limit(limit).all()


def _reasons(entry, listing, pref_area):
    reasons = []
    r2i = entry["rent_to_income"]
    if r2i and r2i.get("ratio_percent") is not None:
        reasons.append(f"Rent is {r2i['ratio_percent']:.0f}% of your income ({r2i['label'].lower()})")
    if entry["distance_km"] is not None and entry["commute"]:
        trip = f"{entry['distance_km']:.1f} km from {entry.get('workplace') or 'work'}"
        if entry["monthly_commute"]:
            trip += f", about KSh {entry['monthly_commute']:,.0f} a month to travel"
        reasons.append(trip)
    verdict = entry.get("verdict") or {}
    if verdict.get("verdict") == "cheap":
        reasons.append(f"{abs(verdict['difference_percent']):.0f}% below the usual rent in the area")
    elif verdict.get("verdict") == "fair":
        reasons.append("Priced fairly for the area")
    if pref_area is not None:
        reasons.append(
            f"In {pref_area.name}, your preferred area"
            if entry["in_pref"]
            else f"Close to {pref_area.name}"
        )
    if listing.availability_status == "vacant":
        where = []
        if listing.building_name:
            where.append(listing.building_name)
        if listing.floor_number is not None:
            where.append(f"floor {listing.floor_number}")
        if listing.room_number:
            where.append(f"unit {listing.room_number}")
        reasons.append("Vacant now" + (": " + ", ".join(where) if where else ""))
    return reasons


def recommend(renter, beds=None, limit=12):
    """The homes this renter can go for, best first, with the reasons.

    How it decides:
    * the rent ceiling is the renter's own maximum when they gave one,
      otherwise 40% of their income (the most that is still manageable);
    * every open unit under the ceiling is scored on its real monthly cost
      (rent plus travelling to work), distance, whether it is confirmed
      vacant, whether it is cheap for its area and whether it is in the area
      they like;
    * if the preferred area has nothing, nearby areas are used and the page
      says so;
    * if nothing is under the ceiling, the closest options above it are shown
      so the page is never left blank.
    """
    from app.analytics import services as analytics
    from app.places.services import resolve_area

    income = float(renter.monthlyincome) if renter and renter.monthlyincome else None
    user_min, user_max = parse_budget_range(renter.budgetrange if renter else None)
    comfortable_max = income * AFFORDABLE_RATIO / 100 if income else None
    stretch_max = income * STRETCH_RATIO / 100 if income else None

    ceiling = user_max or stretch_max
    notes = []
    if user_max and stretch_max and user_max > stretch_max:
        notes.append(
            f"Your maximum rent of KSh {user_max:,.0f} is more than 40% of your income "
            f"(KSh {stretch_max:,.0f}). That may be hard to manage once travel and food are added."
        )
    if ceiling is None:
        notes.append(
            "Add your income or the most you can pay, so the list can be narrowed to what you can afford."
        )

    pref_area = None
    if renter and renter.preferredlocation:
        pref_area, _ = resolve_area(renter.preferredlocation)
    area_lookup = {a.name.lower(): a for a in Area.query.all()}
    mode = (renter.commute_mode if renter else None) or "matatu"
    benchmarks = analytics.area_benchmarks()

    def build(listing):
        entry = analyse_listing(listing, renter, area_lookup, mode)
        entry["listing"] = listing
        entry["verdict"] = analytics.listing_verdict(listing, benchmarks)
        commute = entry["commute"]
        entry["monthly_commute"] = (
            commute["cost"] * 2 * WORKING_DAYS if commute and commute.get("cost") is not None else 0.0
        )
        entry["total_monthly"] = float(listing.rentamount) + entry["monthly_commute"]
        entry["total_ratio"] = (entry["total_monthly"] / income * 100) if income else None

        in_pref = near_pref = False
        if pref_area is not None:
            in_pref = listing.area_id == pref_area.area_id or (
                (listing.address or "").strip().lower() == pref_area.name.lower()
            )
            if not in_pref:
                lat, lon = listing_coordinates(listing, area_lookup)
                d = haversine_km(lat, lon, pref_area.latitude, pref_area.longitude)
                near_pref = d is not None and d <= 6.0
        entry["in_pref"], entry["near_pref"] = in_pref, near_pref

        # lower score = better fit
        basis = ceiling or entry["total_monthly"] or 1
        score = entry["total_monthly"] / basis * 50
        if entry["distance_km"] is not None:
            score += min(entry["distance_km"], 25) / 25 * 20
        if listing.availability_status != "vacant":
            score += 8
        score += {"cheap": -8, "expensive": 8}.get((entry["verdict"] or {}).get("verdict"), 0)
        if pref_area is not None and not in_pref:
            score += 4 if near_pref else 14
        entry["score"] = score

        if income:
            ratio = entry["rent_to_income"]["ratio_percent"]
            if ratio <= AFFORDABLE_RATIO and (entry["total_ratio"] or 0) <= TOTAL_COMFORT_RATIO:
                entry["tier"] = "comfortable"
            elif ratio <= STRETCH_RATIO:
                entry["tier"] = "stretch"
            else:
                entry["tier"] = "over"
        else:
            entry["tier"] = "within"
        entry["reasons"] = _reasons(entry, listing, pref_area)
        return entry

    entries = [build(l) for l in _pool(user_min, ceiling, beds)]

    if pref_area is not None and entries:
        in_area = [e for e in entries if e["in_pref"]]
        close = [e for e in entries if not e["in_pref"] and e["near_pref"]]
        if in_area or close:
            entries = in_area + close
            if not in_area:
                notes.append(
                    f"Nothing is open in {pref_area.name} within your budget, so nearby areas are shown."
                )
        else:
            notes.append(
                f"Nothing is open in or near {pref_area.name} within your budget, so other areas are shown."
            )
    entries.sort(key=lambda e: e["score"])

    tiers = {"comfortable": [], "stretch": [], "within": []}
    for entry in entries:
        if entry["tier"] in tiers:
            tiers[entry["tier"]].append(entry)

    # nothing under the ceiling: show the nearest options above it
    near_misses = []
    if not entries and ceiling:
        above = (
            Property.query.filter(
                Property.is_active.is_(True),
                Property.availability_status.in_(("vacant", "unknown")),
                Property.rentamount > ceiling,
            )
            .order_by(Property.rentamount.asc())
            .limit(6)
            .all()
        )
        near_misses = [build(l) for l in above]
        if near_misses:
            cheapest = float(near_misses[0]["listing"].rentamount)
            notes.append(
                f"No open unit costs KSh {ceiling:,.0f} or less. The cheapest is KSh {cheapest:,.0f}, "
                f"so you would need about KSh {cheapest - ceiling:,.0f} more a month."
            )

    # areas where this budget gets the most choice
    affordable_areas = []
    if ceiling:
        for row in benchmarks:
            if row["count"] >= 3 and row["average"] <= ceiling:
                affordable_areas.append(
                    {"name": row["area"], "average": row["average"], "count": row["count"]}
                )
        affordable_areas.sort(key=lambda a: -a["count"])

    return {
        "income": income,
        "budget_min": user_min,
        "budget_max": user_max,
        "ceiling": ceiling,
        "comfortable_max": comfortable_max,
        "stretch_max": stretch_max,
        "preferred_area": pref_area,
        "picks": entries[:limit],
        "total_found": len(entries),
        "tiers": tiers,
        "near_misses": near_misses,
        "affordable_areas": affordable_areas[:6],
        "notes": notes,
    }


def matching_listings(renter, limit=40):
    """Listings that fit the renter's saved criteria, with insights attached."""
    if renter is None:
        return []
    return recommend(renter, limit=limit)["picks"]


def map_points(entries, renter=None, url_for=None):
    """Points for the map: the recommended homes and the workplace.

    Returns (points, target). Each point is {lat, lng, label, url}; the target
    is the renter's workplace or school, or None when it is not known.
    """
    area_lookup = {a.name.lower(): a for a in Area.query.all()}
    points = []
    for entry in entries:
        listing = entry["listing"]
        lat, lon = listing_coordinates(listing, area_lookup)
        if lat is None:
            continue
        label = f"{listing.title} - KSh {float(listing.rentamount):,.0f}"
        points.append(
            {
                "lat": lat,
                "lng": lon,
                "label": label,
                "url": url_for("listings.detail", listing_id=listing.listing_id) if url_for else None,
            }
        )

    work = workplace_point(renter)
    target = {"lat": work[0], "lng": work[1], "label": work[2]} if work else None
    return points, target
