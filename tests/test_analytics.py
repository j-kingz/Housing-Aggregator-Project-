"""Tests for the price analytics."""

from datetime import date, timedelta

from app.analytics import services
from app.models import Property


def add_listing(title, rent, address="Westlands", city="Nairobi", beds=2, days_ago=0, **extra):
    listing = Property(
        title=title,
        rentamount=rent,
        address=address,
        city=city,
        bedrooms=beds,
        bathrooms=2,
        category="Apartment",
        listingdate=date.today() - timedelta(days=days_ago),
        is_active=True,
        **extra,
    )
    from app.extensions import db

    db.session.add(listing)
    db.session.commit()
    return listing


class TestSummarise:
    def test_empty(self):
        stats = services.summarise([])
        assert stats["count"] == 0
        assert stats["average"] == 0.0

    def test_the_numbers(self, app):
        listings = [add_listing(f"Flat {i}", rent) for i, rent in enumerate([30000, 40000, 50000])]
        stats = services.summarise(listings)

        assert stats["count"] == 3
        assert stats["average"] == 40000
        assert stats["median"] == 40000
        assert stats["min"] == 30000
        assert stats["max"] == 50000


class TestBenchmarks:
    def test_one_row_per_neighbourhood(self, app):
        add_listing("A", 40000, address="Westlands")
        add_listing("B", 60000, address="Westlands")
        add_listing("C", 30000, address="Kilimani")

        rows = services.area_benchmarks()

        assert len(rows) == 2
        assert rows[0]["area"] == "Westlands"
        assert rows[0]["average"] == 50000
        assert rows[1]["area"] == "Kilimani"

    def test_filtered_by_city(self, app):
        add_listing("A", 40000, address="Westlands", city="Nairobi")
        add_listing("B", 30000, address="Mombasa CBD", city="Mombasa")

        rows = services.area_benchmarks(city="Mombasa")
        assert len(rows) == 1
        assert rows[0]["city"] == "Mombasa"


class TestDistribution:
    def test_the_bands_add_up_to_the_listing_count(self, app):
        for index in range(10):
            add_listing(f"Flat {index}", 20000 + index * 1000)

        bands = services.rent_distribution(Property.query.all())

        assert len(bands) == 10
        assert sum(band["count"] for band in bands) == 10

    def test_no_listings(self):
        assert services.rent_distribution([]) == []


class TestTrend:
    def test_listings_are_grouped_by_month(self, app):
        add_listing("A", 40000, days_ago=5)
        add_listing("B", 60000, days_ago=5)
        add_listing("C", 50000, days_ago=40)

        trend = services.price_trend()

        # oldest month first
        assert len(trend) == 2
        assert trend[0]["count"] == 1
        assert trend[0]["average"] == 50000
        assert trend[-1]["count"] == 2
        assert trend[-1]["average"] == 50000


class TestVerdict:
    def test_a_cheap_listing_is_called_out(self, app):
        for _ in range(3):
            add_listing("Normal", 50000)
        listing = add_listing("Cheap one", 30000)

        verdict = services.listing_verdict(listing, services.area_benchmarks())

        assert verdict["verdict"] == "cheap"
        assert verdict["difference_percent"] < -10

    def test_a_dear_listing_is_called_out(self, app):
        for _ in range(3):
            add_listing("Normal", 50000)
        listing = add_listing("Dear one", 90000)

        verdict = services.listing_verdict(listing, services.area_benchmarks())

        assert verdict["verdict"] == "expensive"

    def test_a_listing_at_the_average_is_fair(self, app):
        for _ in range(3):
            add_listing("Normal", 50000)
        listing = add_listing("Same", 50000)

        verdict = services.listing_verdict(listing, services.area_benchmarks())

        assert verdict["verdict"] == "fair"

    def test_no_data_at_all(self, app):
        listing = add_listing("Only one", 50000)
        verdict = services.listing_verdict(listing, services.area_benchmarks())
        assert verdict["verdict"] == "unknown"


class TestSnapshots:
    def test_a_snapshot_is_written(self, app):
        add_listing("A", 40000)
        add_listing("B", 60000)

        snapshot = services.record_snapshot()

        assert snapshot.listing_count == 2
        assert float(snapshot.average_rent) == 50000
