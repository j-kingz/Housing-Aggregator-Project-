"""Tests for the price analytics."""

from datetime import date, timedelta

from app.analytics import services
from app.models import Property


def add_listing(title, rent, address="Westlands", city="Nairobi", beds=2, days_ago=0,
                category="Apartment", **extra):
    listing = Property(
        title=title,
        rentamount=rent,
        address=address,
        city=city,
        bedrooms=beds,
        bathrooms=2,
        category=category,
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
    def test_bands_start_at_5k_and_widen(self, app):
        for rent in (6000, 14000, 20000, 34000, 40000, 70000):
            add_listing(f"Flat {rent}", rent)

        bands = services.rent_distribution(Property.query.all())

        assert [b["label"] for b in bands] == ["5k - 15k", "15k - 35k", "35k - 65k", "65k - 105k"]
        assert [b["count"] for b in bands] == [2, 2, 1, 1]

    def test_very_high_and_very_low_rents_get_their_own_bands(self, app):
        add_listing("Cheap", 3000)
        add_listing("Mansion", 5_000_000)

        bands = services.rent_distribution(Property.query.all())

        assert bands[0]["label"] == "Below 5k" and bands[0]["count"] == 1
        assert bands[-1]["label"].endswith("and above") and bands[-1]["count"] == 1
        assert sum(b["count"] for b in bands) == 2

    def test_no_listings(self):
        assert services.rent_distribution([]) == []


class TestBrackets:
    def test_ten_k_brackets_from_5k(self):
        assert services.ten_k_bracket(5000)["label"] == "KSh 5k - 15k"
        assert services.ten_k_bracket(14999)["label"] == "KSh 5k - 15k"
        assert services.ten_k_bracket(28000)["label"] == "KSh 25k - 35k"
        assert services.ten_k_bracket(4000)["label"] == "Below KSh 5k"


class TestUnitTypes:
    def test_each_kind_of_home_is_kept_apart(self, app):
        def kind(beds, category="Apartment"):
            return services.unit_type(add_listing("x", 10000, beds=beds, category=category))

        assert kind(0, "Bedsitter") == "Bedsitter / Studio"
        assert kind(None, "Studio") == "Bedsitter / Studio"
        assert kind(1) == "1 Bedroom"
        assert kind(2) == "2 Bedrooms"
        assert kind(3) == "3+ Bedroom apartment"
        assert kind(None) == "Apartment (bedrooms not given)"
        assert kind(5, "Maisonette") == "House / Mansion"

    def test_averages_are_per_county_and_per_type(self, app):
        add_listing("Bedsitter 1", 8000, beds=0, category="Bedsitter")
        add_listing("Bedsitter 2", 12000, beds=0, category="Bedsitter")
        add_listing("Mansion", 500000, beds=6, category="Maisonette")
        add_listing("Mombasa flat", 25000, beds=1, address="Mombasa CBD", city="Mombasa")

        result = services.average_rent_by_county(Property.query.all())

        assert list(result) == ["Nairobi", "Mombasa"]
        nairobi = {row["type"]: row for row in result["Nairobi"]}
        assert nairobi["Bedsitter / Studio"]["average"] == 10000
        assert nairobi["Bedsitter / Studio"]["bracket"] == "KSh 5k - 15k"
        assert nairobi["House / Mansion"]["average"] == 500000
        assert [row["type"] for row in result["Mombasa"]] == ["1 Bedroom"]


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

    def test_the_trend_is_per_county_with_a_line_per_home_type(self, app):
        add_listing("Flat now", 40000, beds=2, days_ago=0)
        add_listing("Flat before", 30000, beds=2, days_ago=40)
        add_listing("Bedsitter", 9000, beds=0, category="Bedsitter", days_ago=0)
        add_listing("Mombasa", 20000, beds=2, address="Mombasa CBD", city="Mombasa")

        trends = services.price_trend_by_county(Property.query.all())

        nairobi = trends["Nairobi"]
        assert nairobi["granularity"] == "month"
        assert len(nairobi["labels"]) == 2
        series = {s["type"]: s for s in nairobi["series"]}
        assert series["2 Bedrooms"]["values"] == [30000, 40000]
        assert series["Bedsitter / Studio"]["values"] == [None, 9000]
        # the Mombasa flat is never mixed into Nairobi
        assert trends["Mombasa"]["series"][0]["values"] == [20000]

    def test_a_single_month_is_shown_by_week(self, app):
        add_listing("A", 40000, beds=2, days_ago=0)
        trend = services.price_trend_by_type(Property.query.all())
        assert trend["granularity"] == "week"

    def test_the_dashboard_requires_a_place_and_bedroom_selection(self, client, app):
        add_listing("A", 40000, beds=2)
        add_listing("B", 20000, beds=1, address="Mombasa CBD", city="Mombasa")
        html = client.get("/analytics/").get_data(as_text=True)
        assert 'name="area"' in html and 'name="bedrooms"' in html
        assert "Selected-room price analytics" in html

    def test_dashboard_only_uses_the_selected_place_and_bedrooms(self, client, app):
        add_listing("Westlands two", 40000, address="Westlands", beds=2)
        add_listing("Westlands one", 20000, address="Westlands", beds=1)
        add_listing("Kilimani two", 30000, address="Kilimani", beds=2)

        html = client.get("/analytics/?area=Westlands&bedrooms=2").get_data(as_text=True)
        assert "KSh 40,000" in html
        assert "KSh 20,000" not in html
        assert "KSh 30,000" not in html


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


# -- places whose listings carry a different city than their neighbourhood ----
from app.extensions import db  # noqa: E402
from app.models import Area  # noqa: E402


def _area(name, city, county):
    area = Area(name=name, city=city, county=county, latitude=-1.3, longitude=36.9)
    db.session.add(area)
    db.session.commit()
    return area


class TestAreaPageFindsEveryListing:
    def test_listings_whose_city_differs_from_the_neighbourhood_are_shown(self, client, app):
        # the neighbourhood says Nairobi, the scraped listings say Machakos
        syokimau = _area("Syokimau", "Nairobi", "Machakos")
        for rent in (30000, 40000, 50000):
            add_listing(f"Flat {rent}", rent, address="Syokimau", city="Machakos",
                        area_id=syokimau.area_id)
        response = client.get("/analytics/area/Syokimau?city=Nairobi")
        assert response.status_code == 200
        assert "Flat 30000" in response.get_data(as_text=True)

    def test_a_listing_linked_to_the_area_with_another_address_is_shown(self, client, app):
        machakos = _area("Machakos", "Machakos", "Machakos")
        add_listing("Town flat", 20000, address="Machakos Town", city="Machakos",
                    area_id=machakos.area_id)
        response = client.get("/analytics/area/Machakos")
        assert response.status_code == 200
        assert "Town flat" in response.get_data(as_text=True)

    def test_an_unknown_place_with_no_listings_is_still_not_found(self, client, app):
        assert client.get("/analytics/area/Nowhere").status_code == 404

    def test_the_trend_covers_the_listings_shown(self, app):
        syokimau = _area("Syokimau", "Nairobi", "Machakos")
        listings = [add_listing("A", 30000, address="Syokimau", city="Machakos",
                                area_id=syokimau.area_id, days_ago=40),
                    add_listing("B", 50000, address="Syokimau", city="Machakos",
                                area_id=syokimau.area_id)]
        trend = services.price_trend(listings=listings)
        assert sum(row["count"] for row in trend) == 2


class TestVerdictFallsBackToTheCounty:
    def test_a_small_neighbourhood_is_compared_with_its_county(self, app):
        ruaka = _area("Ruaka", "Nairobi", "Kiambu")
        juja = _area("Juja", "Juja", "Kiambu")
        ruiru = _area("Ruiru", "Ruiru", "Kiambu")
        add_listing("Juja flat", 30000, address="Juja", city="Kiambu", area_id=juja.area_id)
        add_listing("Ruiru flat", 30000, address="Ruiru", city="Kamakis", area_id=ruiru.area_id)
        add_listing("Ruaka flat", 30000, address="Ruaka", city="Kiambu", area_id=ruaka.area_id)
        listing = add_listing("Dear Ruaka flat", 60000, address="Ruaka", city="Kiambu",
                              area_id=ruaka.area_id)

        verdict = services.listing_verdict(listing, services.area_benchmarks())

        assert verdict["scope"] == "county"
        assert verdict["benchmark_area"] == "Kiambu"
        assert verdict["benchmark_count"] == 4
        assert verdict["verdict"] == "expensive"

    def test_the_only_listing_in_a_county_is_still_unknown(self, app):
        nanyuki = _area("Nanyuki", "Nanyuki", "Laikipia")
        listing = add_listing("Nanyuki house", 40000, address="Nanyuki", city="Laikipia",
                              area_id=nanyuki.area_id)
        verdict = services.listing_verdict(listing, services.area_benchmarks())
        assert verdict["verdict"] == "unknown"

    def test_the_listing_page_names_the_county(self, client, app):
        ruaka = _area("Ruaka", "Nairobi", "Kiambu")
        juja = _area("Juja", "Juja", "Kiambu")
        add_listing("Juja flat", 30000, address="Juja", city="Kiambu", area_id=juja.area_id)
        add_listing("Juja flat 2", 30000, address="Juja", city="Kiambu", area_id=juja.area_id)
        listing = add_listing("Ruaka flat", 30000, address="Ruaka", city="Kiambu",
                              area_id=ruaka.area_id)
        page = client.get(f"/listings/{listing.listing_id}").get_data(as_text=True)
        assert "in Kiambu County" in page


class TestTrendChartsStartAtZero:
    def test_the_dashboard_trend_axis_starts_at_zero(self, client, app):
        westlands = _area("Westlands", "Nairobi", "Nairobi")
        add_listing("A", 30000, area_id=westlands.area_id, days_ago=40)
        add_listing("B", 50000, area_id=westlands.area_id)
        html = client.get("/analytics/?area=Westlands&bedrooms=2").get_data(as_text=True)
        assert "trendChart" in html
        assert "axis.min = 0;" in html
        assert "beginAtZero: true" in html

    def test_the_area_trend_axis_starts_at_zero(self, client, app):
        westlands = _area("Westlands", "Nairobi", "Nairobi")
        add_listing("A", 30000, area_id=westlands.area_id, days_ago=40)
        add_listing("B", 50000, area_id=westlands.area_id)
        html = client.get("/analytics/area/Westlands").get_data(as_text=True)
        assert "beginAtZero: true, min: 0" in html


class TestVerdictComparesLikeWithLike:
    def test_a_bedsitter_is_not_compared_with_big_houses(self, app):
        # three dear family homes and three bedsitters in the same area
        for rent in (200000, 220000, 250000):
            add_listing("House", rent, beds=5, category="Maisonette")
        for rent in (15000, 15000, 16000):
            add_listing("Bedsitter", rent, beds=0, category="Bedsitter")
        listing = add_listing("My bedsitter", 15500, beds=0, category="Bedsitter")

        verdict = services.listing_verdict(listing, services.area_benchmarks())

        assert verdict["verdict"] == "fair"            # was "cheap" against the mixed average
        assert verdict["unit_type"] == "Bedsitter / Studio"
        assert verdict["benchmark_count"] == 4         # only the bedsitters

    def test_too_few_similar_homes_is_unknown(self, app):
        for rent in (50000, 52000, 54000):
            add_listing("2 bed", rent, beds=2)
        listing = add_listing("Bedsitter", 15000, beds=0, category="Bedsitter")
        verdict = services.listing_verdict(listing, services.area_benchmarks())
        assert verdict["verdict"] == "unknown"

    def test_one_very_dear_home_does_not_make_the_rest_look_cheap(self, app):
        for rent in (40000, 41000, 42000):
            add_listing("Normal", rent)
        add_listing("Penthouse", 400000)              # pulls the average far up
        listing = add_listing("Mine", 41000)
        verdict = services.listing_verdict(listing, services.area_benchmarks())
        assert verdict["verdict"] == "fair"            # the median is 42,000

    def test_the_listing_page_explains_the_comparison(self, client, app):
        for rent in (40000, 41000, 42000):
            add_listing("Normal", rent)
        listing = add_listing("Mine", 20000)
        page = client.get(f"/listings/{listing.listing_id}").get_data(as_text=True)
        assert "Similar homes (2 Bedrooms) typically rent for" in page
        assert "% below market" in page and "-" not in page.split("% below market")[0][-4:]
