"""Tests for the data cleaning rules.

These are the functions that turn the text on a listing page into the
numbers stored in the database, so they get the most attention.
"""

from decimal import Decimal

from scraper.cleaner import (
    clean_listing,
    extract_amenities,
    fingerprint,
    infer_category,
    looks_like_duplicate,
    normalise_title,
    parse_bathrooms,
    parse_bedrooms,
    parse_rent,
    parse_size_sqft,
    split_location,
    title_overlap,
)


class TestParseRent:
    def test_plain_amount(self):
        assert parse_rent("KSh 28,000") == Decimal("28000.00")

    def test_lowercase_and_extra_words(self):
        assert parse_rent("ksh 45,500 per month") == Decimal("45500.00")

    def test_thousand_shorthand(self):
        assert parse_rent("KSh 28.5k") == Decimal("28500.00")

    def test_million_shorthand(self):
        assert parse_rent("KSh 1.2M") == Decimal("1200000.00")

    def test_spaced_thousands_are_kept_together(self):
        assert parse_rent("KSh 500 000+") == Decimal("500000.00")

    def test_no_currency_word(self):
        assert parse_rent("32,000") == Decimal("32000.00")

    def test_daily_price_is_converted_to_monthly(self):
        assert parse_rent("KSh 2,000 per day") == Decimal("60000.00")

    def test_weekly_price_is_converted_to_monthly(self):
        assert parse_rent("KSh 10,000 per week") == Decimal("43333.33")

    def test_slash_month_is_not_mistaken_for_a_suffix(self):
        # "p/m" must not be read as the million suffix
        assert parse_rent("KSh 45,500 p/m") == Decimal("45500.00")

    def test_no_price(self):
        assert parse_rent("Price on request") is None
        assert parse_rent("") is None
        assert parse_rent(None) is None

    def test_zero_price_is_rejected(self):
        assert parse_rent("KSh 0") is None

    def test_price_too_large_for_the_column(self):
        assert parse_rent("KSh 500,000,000") is None

    def test_number_already_as_a_value(self):
        assert parse_rent(28000) == Decimal("28000")


class TestCounts:
    def test_bedrooms(self):
        assert parse_bedrooms("2 Bedrooms") == 2
        assert parse_bedrooms("3 bed") == 3
        assert parse_bedrooms("Studio") is None

    def test_bedrooms_zero_is_kept(self):
        assert parse_bedrooms("0 Bedrooms") == 0

    def test_bathrooms(self):
        assert parse_bathrooms("2 Bathrooms") == 2
        assert parse_bathrooms("1 bath") == 1

    def test_out_of_range_is_rejected(self):
        assert parse_bedrooms("90 Bedrooms") is None


class TestSize:
    def test_square_metres_are_converted(self):
        assert parse_size_sqft("450 sqm") == 4844

    def test_square_feet_are_kept(self):
        assert parse_size_sqft("1,200 sqft") == 1200

    def test_no_size(self):
        assert parse_size_sqft("no size given") is None


class TestLocation:
    def test_area_and_city(self):
        address, city, area = split_location("Kilimani, Nairobi")
        assert (address, city, area) == ("Kilimani", "Nairobi", "Kilimani")

    def test_known_area_is_used(self):
        known = [{"name": "Westlands"}, {"name": "Kilimani"}]
        address, city, area = split_location("Riverside Drive, Westlands, Nairobi", known)
        assert area == "Westlands"
        assert city == "Nairobi"
        assert address == "Riverside Drive"

    def test_longest_known_area_wins(self):
        known = [{"name": "Nairobi"}, {"name": "Nairobi CBD"}]
        _, _, area = split_location("Nairobi CBD, Nairobi", known)
        assert area == "Nairobi CBD"

    def test_single_value(self):
        address, city, area = split_location("Westlands")
        assert address == "Westlands"
        assert city is None

    def test_empty(self):
        assert split_location("") == (None, None, None)


class TestCategory:
    def test_bedsitter(self):
        assert infer_category("Affordable Bedsitter") == "Bedsitter"

    def test_townhouse(self):
        assert infer_category("Executive 3 Bedroom Townhouse") == "Townhouse"

    def test_studio(self):
        assert infer_category("Studio near the CBD") == "Studio"

    def test_default(self):
        assert infer_category("Some flat in Westlands", 2) == "Apartment"

    def test_many_bedrooms(self):
        assert infer_category("Four bedroom house", 4) == "Maisonette"


class TestAmenities:
    def test_finds_known_amenities(self):
        found = extract_amenities("Water tank, prepaid electricity, parking, wifi")
        assert "Water" in found
        assert "Parking" in found
        assert "WiFi" in found

    def test_nothing_found(self):
        assert extract_amenities("a nice quiet place") is None


class TestFingerprint:
    def test_the_same_flat_gives_the_same_fingerprint(self):
        first = {
            "title": "Modern 2 Bedroom Apartment in Westlands with balcony",
            "rentamount": 85000,
            "address": "Westlands",
            "city": "Nairobi",
            "bedrooms": 2,
            "bathrooms": 2,
        }
        second = {
            "title": "Modern 2 Bedroom for rent at Westlands balcony",
            "rentamount": 85000,
            "address": "Westlands",
            "city": "Nairobi",
            "bedrooms": 2,
            "bathrooms": 2,
        }
        assert fingerprint(first) == fingerprint(second)

    def test_a_different_price_gives_a_different_fingerprint(self):
        first = {"title": "Flat in Westlands", "rentamount": 85000, "address": "Westlands"}
        second = {"title": "Flat in Westlands", "rentamount": 90000, "address": "Westlands"}
        assert fingerprint(first) != fingerprint(second)

    def test_generic_words_are_dropped(self):
        assert normalise_title("Modern 2 Bedroom Apartment in Westlands") == "modern westlands"

    def test_title_overlap(self):
        assert title_overlap("Modern flat in Westlands", "Modern flat at Westlands") > 0.6
        assert title_overlap("Modern flat in Westlands", "Bungalow near Karen") < 0.4


class TestLooksLikeDuplicate:
    def test_same_flat_with_a_slightly_different_price(self):
        class Existing:
            title = "Modern 2 Bedroom Apartment in Westlands"
            address = "Westlands"
            bedrooms = 2
            rentamount = 85000

        candidate = {
            "title": "Modern 2 Bedroom for rent at Westlands",
            "address": "Westlands",
            "bedrooms": 2,
            "rentamount": 87000,
        }
        assert looks_like_duplicate(Existing, candidate) is True

    def test_a_different_flat_is_not_a_duplicate(self):
        class Existing:
            title = "Modern 2 Bedroom Apartment in Westlands"
            address = "Westlands"
            bedrooms = 2
            rentamount = 85000

        candidate = {
            "title": "Bungalow with garden in Karen",
            "address": "Karen",
            "bedrooms": 3,
            "rentamount": 200000,
        }
        assert looks_like_duplicate(Existing, candidate) is False


class TestCleanListing:
    def test_a_full_record(self):
        raw = {
            "title": "Bright 2 Bedroom Apartment",
            "price_text": "KSh 28,000",
            "bedrooms_text": "2 Bedrooms",
            "bathrooms_text": "2 Bathrooms",
            "location_text": "Kilimani, Nairobi",
            "description": "A nice flat with water and parking.",
            "size_text": "120 sqm",
            "url": "https://example.com/listing/1",
            "external_id": "1",
        }
        result = clean_listing(raw, known_areas=[{"name": "Kilimani"}])

        assert result["title"] == "Bright 2 Bedroom Apartment"
        assert result["rentamount"] == Decimal("28000.00")
        assert result["bedrooms"] == 2
        assert result["bathrooms"] == 2
        assert result["city"] == "Nairobi"
        assert result["address"] == "Kilimani"
        assert result["area_name"] == "Kilimani"
        assert result["size_sqft"] == 1292
        assert result["external_id"] == "1"
        assert result["fingerprint"]

    def test_a_record_without_a_price_is_dropped(self):
        raw = {"title": "Some flat", "price_text": "Ask for price"}
        assert clean_listing(raw) is None

    def test_a_record_without_a_title_is_dropped(self):
        raw = {"title": "", "price_text": "KSh 20,000"}
        assert clean_listing(raw) is None

    def test_a_price_only_title_is_dropped(self):
        raw = {"title": "KSh 500 000+", "price_text": "KSh 500 000+"}
        assert clean_listing(raw) is None

    def test_javascript_source_urls_are_removed(self):
        raw = {
            "title": "Bright 2 Bedroom Apartment",
            "price_text": "KSh 28,000",
            "url": "javascript:;",
        }
        result = clean_listing(raw)
        assert result["source_url"] is None

    def test_the_default_city_is_used(self):
        raw = {"title": "A flat", "price_text": "KSh 20,000", "location_text": "Kilimani"}
        result = clean_listing(raw, default_city="Nairobi")
        assert result["city"] == "Nairobi"
