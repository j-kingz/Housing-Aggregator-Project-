"""Tests for reading listings out of a page of HTML."""

from pathlib import Path

from scraper.parser import parse_heuristic, parse_listings, parse_page

FIXTURES = Path(__file__).resolve().parent.parent / "scraper" / "fixtures"

SIMPLE_PAGE = """
<html><body>
  <div class="property">
    <h2><a href="/rent/123">Spacious 3 Bedroom in Lavington</a></h2>
    <span class="price">KSh 140,000</span>
    <span class="location">Lavington, Nairobi</span>
    <p>3 Bedrooms, 2 Bathrooms, 180 sqm, water tank and parking</p>
  </div>
</body></html>
"""

UNKNOWN_LAYOUT = """
<html><body>
  <article class="card">
    <h3>Bright One Bedroom in Kilimani</h3>
    <div class="price-tag">KES 65,000</div>
    <div>1 bedroom, 1 bathroom</div>
    <div>Kilimani, Nairobi</div>
  </article>
</body></html>
"""


class TestFixtureParser:
    def test_reads_the_sample_page(self):
        html = (FIXTURES / "sample_listings.html").read_text(encoding="utf-8")
        records = parse_page(html, profile="fixture")

        assert len(records) == 3
        assert records[0]["title"] == "Bright 2 Bedroom Apartment"
        assert records[0]["price_text"] == "KSh 28,000"
        assert records[0]["location_text"] == "Kilimani, Nairobi"

    def test_the_old_helper_still_works(self):
        html = (FIXTURES / "sample_listings.html").read_text(encoding="utf-8")
        listings = parse_listings(html)

        assert len(listings) == 3
        assert listings[0]["rentamount"] == 28000
        assert listings[0]["city"] == "Nairobi"

    def test_reads_the_larger_nairobi_sample(self):
        html = (FIXTURES / "nairobi_listings.html").read_text(encoding="utf-8")
        records = parse_page(html, profile="fixture")
        assert len(records) > 100


class TestProfileParser:
    def test_reads_a_page_with_known_selectors(self):
        records = parse_page(SIMPLE_PAGE, profile="buyrentkenya")

        assert len(records) == 1
        assert records[0]["title"] == "Spacious 3 Bedroom in Lavington"
        assert records[0]["price_text"] == "KSh 140,000"
        assert records[0]["url"].endswith("/rent/123")
        assert records[0]["external_id"] == "123"

    def test_bedrooms_are_read_from_the_card_text(self):
        from scraper.cleaner import parse_bathrooms, parse_bedrooms

        records = parse_page(SIMPLE_PAGE, profile="buyrentkenya")
        assert parse_bedrooms(records[0]["bedrooms_text"]) == 3
        assert parse_bathrooms(records[0]["bathrooms_text"]) == 2


class TestHeuristicParser:
    def test_heuristic_parser_keeps_spaced_thousands(self):
        html = """
        <html><body>
          <article class="card">
            <h3>Large family home in Kilimani</h3>
            <div>KSh 500 000+ per month</div>
            <div>Kilimani, Nairobi</div>
          </article>
        </body></html>
        """
        records = parse_heuristic(html)
        assert records[0]["price_text"] == "KSh 500 000"

    def test_finds_a_listing_on_an_unknown_layout(self):
        records = parse_heuristic(UNKNOWN_LAYOUT)

        assert len(records) == 1
        assert records[0]["price_text"] == "KES 65,000"
        assert records[0]["title"].startswith("Bright One Bedroom")

    def test_falls_back_when_the_profile_finds_nothing(self):
        # the buyrentkenya profile does not match this markup, so the
        # heuristic takes over
        records = parse_page(UNKNOWN_LAYOUT, profile="buyrentkenya")
        assert len(records) == 1

    def test_known_areas_are_used_to_find_the_location(self):
        records = parse_heuristic(UNKNOWN_LAYOUT, known_areas=[{"name": "Kilimani"}])
        assert records[0]["location_text"] == "Kilimani"

    def test_a_page_with_no_prices_gives_nothing(self):
        records = parse_page("<html><body><p>Sorry, no listings today</p></body></html>")
        assert records == []


class TestRobustness:
    def test_javascript_links_are_not_saved_as_listing_urls(self):
        html = """
        <html><body>
          <div class="listing-card">
            <h2 class="listing-title">A flat in Kilimani</h2>
            <span class="price">KSh 28,000</span>
            <a href="javascript:;">View listing</a>
          </div>
        </body></html>
        """
        records = parse_page(html, profile="fixture", base_url="https://example.com")
        assert records[0]["url"] is None

    def test_a_card_missing_its_price_is_skipped(self):
        html = """
        <html><body>
          <div class="listing-card">
            <h2 class="listing-title">A flat with no price</h2>
            <span class="location">Kilimani, Nairobi</span>
          </div>
        </body></html>
        """
        records = parse_page(html, profile="fixture")
        assert records == []

    def test_an_empty_page_does_not_crash(self):
        assert parse_page("") == []
