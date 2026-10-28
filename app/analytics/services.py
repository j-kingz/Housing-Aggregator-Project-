"""Price analytics for the housing market.

Everything here answers the "Location-Specific Analytics" requirement in the
proposal (3.3.1): neighbourhood price comparisons, market trends and an
automatic judgement on whether a asking rent is fair for its area.

The functions work on plain rows and dictionaries so they can be unit tested
without touching the database.
"""

from datetime import date
from statistics import median

from app.models import MarketSnapshot, Property

# How far from the neighbourhood average a listing has to sit before it is
# called out as cheap or expensive
CHEAP_THRESHOLD = -10.0  # percent
DEAR_THRESHOLD = 10.0  # percent

# A price comparison needs a few listings to be worth making. Below this the
# platform says it does not know rather than comparing against noise.
MINIMUM_SAMPLE = 3


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


def area_benchmarks(city=None, minimum=1):
    """One benchmark row per neighbourhood.

    Returns a list of dictionaries sorted by average rent, highest first.
    """
    query = Property.query.filter(Property.is_active.is_(True))
    if city:
        query = query.filter(Property.city == city)

    grouped = {}
    for listing in query.all():
        key = (listing.address or "Unspecified", listing.city)
        grouped.setdefault(key, []).append(listing)

    results = []
    for (area_name, area_city), listings in grouped.items():
        if len(listings) < minimum:
            continue
        stats = summarise(listings)
        stats.update({"area": area_name, "city": area_city})
        results.append(stats)

    results.sort(key=lambda row: row["average"], reverse=True)
    return results


def rent_distribution(listings, buckets=10):
    """How the rents are spread across price bands, for the histogram chart."""
    rents = [_rent(listing.rentamount) for listing in listings]
    rents = [rent for rent in rents if rent > 0]
    if not rents:
        return []

    lowest = min(rents)
    highest = max(rents)
    if lowest == highest:
        return [
            {
                "label": f"KSh {lowest:,.0f}",
                "from": lowest,
                "to": highest,
                "count": len(rents),
            }
        ]

    width = (highest - lowest) / buckets
    bands = []

    for index in range(buckets):
        start = lowest + index * width
        end = start + width
        # the last band includes the highest value
        count = sum(
            1
            for rent in rents
            if (start <= rent < end) or (index == buckets - 1 and rent == highest)
        )
        bands.append(
            {
                "label": f"{start / 1000:.0f}k - {end / 1000:.0f}k",
                "from": start,
                "to": end,
                "count": count,
            }
        )

    return bands


def price_trend(city=None, area=None, months=12):
    """Average rent per month, oldest first, from the listing dates.

    This is the "market trends" chart on the dashboard.
    """
    query = Property.query.filter(Property.is_active.is_(True))
    if city:
        query = query.filter(Property.city == city)
    if area:
        query = query.filter(Property.address == area)

    buckets = {}
    for listing in query.all():
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
    """Judge one listing against the market around it.

    Returns a dictionary with the verdict, how far from the average the rent
    is, and the neighbourhood figures it was compared to. When the area has
    too few listings to be meaningful the city average is used instead.
    """
    if benchmarks is None:
        benchmarks = area_benchmarks()

    by_area = {}
    for row in benchmarks:
        by_area.setdefault((row["area"], row["city"]), row)

    city_rows = [row for row in benchmarks if row["city"] == listing.city]
    city_count = sum(row["count"] for row in city_rows)
    city_average = (
        sum(row["average"] * row["count"] for row in city_rows) / city_count
        if city_rows
        else 0.0
    )

    area_row = by_area.get((listing.address, listing.city))
    benchmark = None
    scope = "city"

    if area_row and area_row["count"] >= MINIMUM_SAMPLE:
        benchmark = area_row
        scope = "area"
    elif city_count >= MINIMUM_SAMPLE:
        benchmark = {
            "area": listing.city,
            "city": listing.city,
            "average": city_average,
            "median": city_average,
            "count": city_count,
        }

    if not benchmark or not benchmark["average"]:
        return {
            "verdict": "unknown",
            "label": "Not enough data",
            "difference_percent": None,
            "benchmark_average": None,
            "benchmark_count": 0,
            "scope": scope,
        }

    difference = ((_rent(listing.rentamount) - benchmark["average"]) / benchmark["average"]) * 100

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

    listings = query.all()
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
