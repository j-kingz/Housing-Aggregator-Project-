"""Price analytics for the housing market.

Everything here answers the "Location-Specific Analytics" requirement in the
proposal (3.3.1): neighbourhood price comparisons, market trends and an
automatic judgement on whether a asking rent is fair for its area.

The functions work on plain rows and dictionaries so they can be unit tested
without touching the database.
"""

from collections import Counter
from datetime import date, timedelta
from statistics import median

from app.models import Area, MarketSnapshot, Property

# How far from the neighbourhood average a listing has to sit before it is
# called out as cheap or expensive
CHEAP_THRESHOLD = -10.0  # percent
DEAR_THRESHOLD = 10.0  # percent

# A price comparison needs a few listings to be worth making. Below this the
# platform says it does not know rather than comparing against noise.
MINIMUM_SAMPLE = 3


def to_bedrooms(value):
    """Parse the selected bedroom count used by the analytics filter."""
    try:
        bedrooms = int(value)
    except (TypeError, ValueError):
        return None
    return bedrooms if 0 <= bedrooms <= 50 else None


def _rent(value):
    return float(value or 0)


def _percentile(sorted_values, fraction):
    """A simple percentile so we do not depend on statistics.quantiles."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarise(listings):
    """Average, median, lowest, highest and spread for a set of listings."""
    rents = sorted(_rent(listing.rentamount) for listing in listings)
    if not rents:
        return {
            "count": 0,
            "average": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p25": 0.0,
            "p75": 0.0,
        }

    average = sum(rents) / len(rents)
    spread = _percentile(rents, 0.75) - _percentile(rents, 0.25)
    return {
        "count": len(rents),
        "average": average,
        "median": median(rents),
        "min": rents[0],
        "max": rents[-1],
        "p25": _percentile(rents, 0.25),
        "p75": _percentile(rents, 0.75),
        "spread": spread,
    }


def area_benchmarks(city=None, minimum=1, listings=None):
    """One benchmark row per neighbourhood.

    Returns a list of dictionaries sorted by average rent, highest first.
    """
    grouped = {}
    if listings is None:
        # only the columns used below; loading whole rows (with the long
        # description text) on every page view gets slow as listings grow
        query = Property.query.filter(Property.is_active.is_(True))
        if city:
            query = query.filter(Property.city == city)
        listings = (
            query.outerjoin(Area, Property.area_id == Area.area_id)
            .with_entities(
                Property.address, Property.city, Property.rentamount,
                Property.bedrooms, Property.category,
                Area.county.label("county"),
            )
            .all()
        )
    for listing in listings:
        key = (listing.address or "Unspecified", listing.city)
        grouped.setdefault(key, []).append(listing)

    results = []
    for (area_name, area_city), listings in grouped.items():
        if len(listings) < minimum:
            continue
        stats = summarise(listings)
        # the county most of the group's listings are in, for the county fallback
        county = Counter(_county_name(item) for item in listings).most_common(1)[0][0]
        # the rents of each kind of home, so a listing is only ever judged
        # against homes like it (a bedsitter never against a 5 bedroom house)
        by_type = {}
        for item in listings:
            rent = _rent(item.rentamount)
            if rent > 0:
                by_type.setdefault(unit_type(item), []).append(rent)
        stats.update({"area": area_name, "city": area_city, "county": county,
                      "by_type": by_type})
        results.append(stats)

    results.sort(key=lambda row: row["average"], reverse=True)
    return results


# ---- price bands ---------------------------------------------------------
# "How rents are spread" groups rents into bands that start at KSh 5,000 and
# widen as they go up: 5k-15k, 15k-35k, 35k-65k, 65k-105k ... (each band is
# 10k wider than the one before), so bedsitters and mansions both land in
# sensible bands. Everything above the last band shares one "and above" band.
BAND_START = 5000
BAND_STEP = 10000
MAX_BANDS = 10


def price_band_edges():
    """[5000, 15000, 35000, 65000, ...]: the edges of every band."""
    edges = [BAND_START]
    width = BAND_STEP
    for _ in range(MAX_BANDS):
        edges.append(edges[-1] + width)
        width += BAND_STEP
    return edges


def format_ksh_short(amount):
    """5000 -> '5k', 1500000 -> '1.5M'."""
    amount = float(amount)
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:,.2f}".rstrip("0").rstrip(".") + "M"
    return f"{amount / 1000:,.0f}k"


def rent_distribution(listings):
    """How the rents are spread across the price bands, for the histogram chart.

    Empty bands in the middle are kept (a gap in the market is information);
    empty bands above the dearest listing are dropped.
    """
    rents = [_rent(listing.rentamount) for listing in listings]
    rents = [rent for rent in rents if rent > 0]
    if not rents:
        return []

    edges = price_band_edges()
    bands = []
    below = sum(1 for rent in rents if rent < edges[0])
    if below:
        bands.append({"label": f"Below {format_ksh_short(edges[0])}", "from": 0,
                      "to": edges[0], "count": below})
    for start, end in zip(edges, edges[1:]):
        bands.append({
            "label": f"{format_ksh_short(start)} - {format_ksh_short(end)}",
            "from": start,
            "to": end,
            "count": sum(1 for rent in rents if start <= rent < end),
        })
    top = edges[-1]
    bands.append({"label": f"{format_ksh_short(top)} and above", "from": top, "to": None,
                  "count": sum(1 for rent in rents if rent >= top)})

    while bands and bands[-1]["count"] == 0:
        bands.pop()
    return bands


def ten_k_bracket(amount):
    """The 10k bracket an amount falls in, counted from 5k: 5k-15k, 15k-25k, 25k-35k ..."""
    amount = float(amount)
    if amount < BAND_START:
        return {"from": 0, "to": BAND_START, "label": f"Below KSh {format_ksh_short(BAND_START)}"}
    start = BAND_START + int((amount - BAND_START) // BAND_STEP) * BAND_STEP
    end = start + BAND_STEP
    return {"from": start, "to": end,
            "label": f"KSh {format_ksh_short(start)} - {format_ksh_short(end)}"}


# ---- home types ------------------------------------------------------------
# Rents are only compared within one kind of home: a bedsitter is never
# averaged together with a mansion.
UNIT_TYPES = [
    "Bedsitter / Studio",
    "1 Bedroom",
    "2 Bedrooms",
    "3+ Bedroom apartment",
    "Apartment (bedrooms not given)",
    "House / Mansion",
]
HOUSE_CATEGORIES = {"maisonette", "townhouse", "bungalow", "villa", "mansion", "house"}


def unit_type(listing):
    """Which of UNIT_TYPES a listing belongs to."""
    category = (listing.category or "").strip().lower()
    bedrooms = listing.bedrooms
    if category in ("bedsitter", "studio") or bedrooms == 0:
        return "Bedsitter / Studio"
    if category in HOUSE_CATEGORIES:
        return "House / Mansion"
    if bedrooms is None:
        return "Apartment (bedrooms not given)"
    if bedrooms == 1:
        return "1 Bedroom"
    if bedrooms == 2:
        return "2 Bedrooms"
    return "3+ Bedroom apartment"


def county_of(listing):
    """The county a listing is in: its neighbourhood's county, else its city."""
    area = getattr(listing, "area", None)
    county = area.county if area is not None else None
    return county or listing.city or "Unspecified"


def _county_name(item):
    """county_of() for a full listing or a light row that carries a county column."""
    if isinstance(item, Property):
        return county_of(item)
    return getattr(item, "county", None) or getattr(item, "city", None) or "Unspecified"


def _by_county(listings):
    """{county: [listings]}, the county with the most listings first."""
    groups = {}
    for listing in listings:
        groups.setdefault(county_of(listing), []).append(listing)
    order = sorted(groups, key=lambda name: (-len(groups[name]), name))
    return {name: groups[name] for name in order}


def counties_of(listings):
    """Counties that have listings, the one with the most listings first."""
    return list(_by_county(listings))


def average_rent_by_type(listings):
    """One row per home type: count, average, the average's 10k bracket, and range."""
    groups = {}
    for listing in listings:
        rent = _rent(listing.rentamount)
        if rent > 0:
            groups.setdefault(unit_type(listing), []).append(rent)
    rows = []
    for name in UNIT_TYPES:
        rents = groups.get(name)
        if not rents:
            continue
        average = sum(rents) / len(rents)
        rows.append({
            "type": name,
            "count": len(rents),
            "average": average,
            "median": median(rents),
            "min": min(rents),
            "max": max(rents),
            "bracket": ten_k_bracket(average)["label"],
        })
    return rows


def average_rent_by_county(listings):
    """{county: rows from average_rent_by_type} for every county with listings."""
    return {name: average_rent_by_type(group) for name, group in _by_county(listings).items()}


def _period(day, granularity):
    if granularity == "month":
        return (day.year, day.month), day.strftime("%b %Y")
    monday = day - timedelta(days=day.weekday())
    return (monday.year, monday.month, monday.day), "Week of " + monday.strftime("%d %b")


def price_trend_by_type(listings, months=12):
    """Average rent per period for each home type, oldest period first.

    Grouped by month. When every listing falls in a single month it is grouped
    by week instead so the chart still shows movement.
    Returns {"granularity", "labels", "series": [{"type", "values", "counts"}]}.
    """
    dated = [item for item in listings if item.listingdate and _rent(item.rentamount) > 0]
    months_seen = {(item.listingdate.year, item.listingdate.month) for item in dated}
    granularity = "month" if len(months_seen) > 1 else "week"

    labels = {}
    cells = {}
    for listing in dated:
        key, label = _period(listing.listingdate, granularity)
        labels[key] = label
        cells.setdefault((unit_type(listing), key), []).append(_rent(listing.rentamount))

    keys = sorted(labels)
    if granularity == "month" and months:
        keys = keys[-months:]
    series = []
    for name in UNIT_TYPES:
        values, counts = [], []
        for key in keys:
            rents = cells.get((name, key))
            values.append(round(sum(rents) / len(rents)) if rents else None)
            counts.append(len(rents) if rents else 0)
        if any(counts):
            series.append({"type": name, "values": values, "counts": counts})
    return {"granularity": granularity, "labels": [labels[k] for k in keys], "series": series}


def price_trend_by_county(listings):
    """{county: price_trend_by_type(...)} for every county with listings."""
    return {name: price_trend_by_type(group) for name, group in _by_county(listings).items()}


def price_trend(city=None, area=None, months=12, listings=None):
    """Average rent per month, oldest first, from the listing dates.

    Pass `listings` to chart a set already chosen (the area page does, so the
    chart covers exactly the listings shown); otherwise they are looked up by
    city and address.
    """
    if listings is None:
        query = Property.query.filter(Property.is_active.is_(True))
        if city:
            query = query.filter(Property.city == city)
        if area:
            query = query.filter(Property.address == area)
        listings = query.with_entities(Property.listingdate, Property.rentamount).all()

    buckets = {}
    for listing in listings:
        if not listing.listingdate:
            continue
        key = (listing.listingdate.year, listing.listingdate.month)
        buckets.setdefault(key, []).append(_rent(listing.rentamount))

    trend = []
    for (year, month), rents in buckets.items():
        trend.append(
            {
                "year": year,
                "month": month,
                "label": f"{year}-{month:02d}",
                "average": sum(rents) / len(rents),
                "count": len(rents),
            }
        )

    trend.sort(key=lambda row: row["label"])
    return trend[-months:] if months else trend


def listing_verdict(listing, benchmarks=None):
    """Judge one listing against similar homes around it.

    Only homes of the same kind are compared (see unit_type: a bedsitter with
    bedsitters, a 2 bedroom with 2 bedrooms ...), first in the neighbourhood,
    then the county, then the city, using the first that has at least
    MINIMUM_SAMPLE such homes. The rent is compared with their median (the
    middle rent). Returns the verdict, how far from the median the rent is,
    and the figures it was compared to.
    """
    if benchmarks is None:
        benchmarks = area_benchmarks()

    kind = unit_type(listing)

    def rents_of(rows):
        rents = []
        for row in rows:
            rents.extend(row.get("by_type", {}).get(kind, []))
        return rents

    area_rows = [row for row in benchmarks
                 if row["area"] == (listing.address or "Unspecified") and row["city"] == listing.city]
    # the county: neighbourhoods with only one or two listings (Ruaka, Juja,
    # Kitengela ...) are compared with their whole county instead of nothing
    county = county_of(listing)
    county_rows = [row for row in benchmarks if row.get("county") == county] \
        if county != "Unspecified" else []
    city_rows = [row for row in benchmarks if row["city"] == listing.city] if listing.city else []

    benchmark = None
    scope = "area"
    for scope, name, rows in (
        ("area", listing.address, area_rows),
        ("county", county, county_rows),
        ("city", listing.city, city_rows),
    ):
        rents = rents_of(rows)
        if len(rents) >= MINIMUM_SAMPLE:
            benchmark = {
                "area": name,
                "average": sum(rents) / len(rents),
                "median": median(rents),
                "count": len(rents),
            }
            break

    if not benchmark or not benchmark["average"]:
        return {
            "verdict": "unknown",
            "label": "Not enough data",
            "difference_percent": None,
            "benchmark_average": None,
            "benchmark_count": 0,
            "unit_type": kind,
            "scope": scope,
        }

    # compared with the median (the middle rent), not the average: a few very
    # dear homes pull the average up and made most ordinary homes look "cheap"
    typical = benchmark["median"] or benchmark["average"]
    difference = ((_rent(listing.rentamount) - typical) / typical) * 100

    if difference <= CHEAP_THRESHOLD:
        verdict, label = "cheap", "Below market"
    elif difference >= DEAR_THRESHOLD:
        verdict, label = "expensive", "Above market"
    else:
        verdict, label = "fair", "Fair price"

    return {
        "verdict": verdict,
        "label": label,
        "difference_percent": difference,
        "benchmark_average": benchmark["average"],
        "benchmark_median": benchmark.get("median"),
        "benchmark_count": benchmark["count"],
        "benchmark_area": benchmark.get("area"),
        "unit_type": kind,
        "scope": scope,
    }


def rent_per_sqft_stats(listings):
    """Rent per square foot figures, when the listings carry a size."""
    values = []
    for listing in listings:
        if listing.size_sqft:
            values.append(_rent(listing.rentamount) / listing.size_sqft)
    if not values:
        return {"count": 0, "average": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    values.sort()
    return {
        "count": len(values),
        "average": sum(values) / len(values),
        "median": median(values),
        "min": values[0],
        "max": values[-1],
    }


def record_snapshot(city=None, area=None, area_id=None):
    """Write today's market figures to the analytics log table.

    The ERD (3.5.1) asks for an analytics logging table that records market
    prices over time so trends survive restarts.
    """
    query = Property.query.filter(Property.is_active.is_(True))
    if city:
        query = query.filter(Property.city == city)
    if area:
        query = query.filter(Property.address == area)

    listings = query.with_entities(Property.rentamount).all()
    if not listings:
        return None

    stats = summarise(listings)
    snapshot = MarketSnapshot(
        area_id=area_id,
        city=city,
        snapshot_date=date.today(),
        listing_count=stats["count"],
        average_rent=stats["average"],
        median_rent=stats["median"],
        min_rent=stats["min"],
        max_rent=stats["max"],
    )
    return snapshot


def snapshot_history(city=None, limit=30):
    """Recorded snapshots, newest first."""
    query = MarketSnapshot.query
    if city:
        query = query.filter(MarketSnapshot.city == city)
    return query.order_by(MarketSnapshot.snapshot_date.desc()).limit(limit).all()
