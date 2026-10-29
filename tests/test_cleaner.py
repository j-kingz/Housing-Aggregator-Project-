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
    parse_bathrooms,
    parse_bedrooms,
    parse_rent,
    parse_size_sqft,
    split_location,
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
    """The fingerprint only recognises the very same advert, it never merges look-alikes."""

    BASE = {
        "title": "2 Bedroom Apartment in Westlands",
        "rentamount": 85000,
        "address": "Westlands",
        "city": "Nairobi",
        "bedrooms": 2,
        "bathrooms": 2,
        "building_name": "Riverside Towers",
        "floor_number": 3,
        "room_number": "3B",
    }

    def test_the_same_advert_gives_the_same_fingerprint(self):
        assert fingerprint(dict(self.BASE)) == fingerprint(dict(self.BASE))

    def test_two_units_in_the_same_building_are_kept_apart(self):
        other = dict(self.BASE, floor_number=4, room_number="4B")
        assert fingerprint(self.BASE) != fingerprint(other)

    def test_a_different_room_on_the_same_floor_is_kept_apart(self):
        assert fingerprint(self.BASE) != fingerprint(dict(self.BASE, room_number="3C"))

    def test_a_different_price_gives_a_different_fingerprint(self):
        assert fingerprint(self.BASE) != fingerprint(dict(self.BASE, rentamount=90000))

    def test_different_wording_is_a_different_listing(self):
        assert fingerprint(self.BASE) != fingerprint(
            dict(self.BASE, title="Modern 2 Bedroom for rent at Westlands")
        )


class TestDollarRent:
    def test_a_dollar_advert_is_converted_to_shillings(self):
        raw = {
            "title": "2 Bedroom Apartment in Westlands",
            "price_text": "KSh 2 200",
            "description": "Furnished 2 bed. Rent $2,200/month inclusive of service charge",
        }
        assert clean_listing(raw)["rentamount"] == 2200 * 129

    def test_a_normal_shilling_advert_is_left_alone(self):
        raw = {
            "title": "2 Bedroom Apartment in Westlands",
            "price_text": "KSh 85,000",
            "description": "Deposit $500 refundable",
        }
        assert clean_listing(raw)["rentamount"] == 85000


class TestPlusCodeAndSize:
    def test_the_plus_code_is_read_from_the_address(self):
        raw = {
            "title": "2 Bedroom Apartment in Westlands",
            "price_text": "KSh 137 500",
            "location_text": "Westlands",
            "address_text": "PQRR+9WG Brookside Grove, Westlands, Nairobi",
        }
        cleaned = clean_listing(raw, known_areas=[{"name": "Westlands", "city": "Nairobi"}])
        assert cleaned["plus_code"] == "PQRR+9WG"
        assert cleaned["city"] == "Nairobi"

    def test_square_metres_with_the_superscript_are_converted(self):
        assert parse_size_sqft("110 m²") == 1184
