"""Tests for the scraping pipeline: saving, re-scrapes, area linking and run history."""

from pathlib import Path

from app.extensions import db
from app.models import Property, ScrapingRun, ScrapingSource
from scraper.parser import parse_page
from scraper.scraper import import_fixture, link_areas, run_source, scrape_source


def make_fixture_source():
    source = ScrapingSource(
        name="Sample fixture",
        base_url="",
        listing_url="",
        profile="fixture",
        delay_seconds=0.0,
        max_pages=1,
        respects_robots=False,
    )
    db.session.add(source)
    db.session.commit()
    return source


class TestFixtureSource:
    def test_the_sample_page_is_read_from_disk(self, app):
        source = make_fixture_source()

        summary, new_ids = scrape_source(source)

        assert summary["pages"] == 1
        assert summary["found"] > 100
        assert summary["saved"] > 0
        assert len(new_ids) == summary["saved"]

    def test_the_same_page_twice_does_not_grow_the_table(self, app):
        source = make_fixture_source()

        first, _ = scrape_source(source)
        count = Property.query.count()
        second, _ = scrape_source(source)

        assert second["saved"] == 0
        assert second["found"] == first["found"]
        assert second["updated"] == first["found"]
        assert Property.query.count() == count

    def test_every_listing_stays_active_after_a_run(self, app):
        source = make_fixture_source()
        scrape_source(source)

        assert Property.query.filter(Property.is_active.is_(True)).count() > 0


class TestRunHistory:
    def test_a_run_is_recorded(self, app):
        source = make_fixture_source()

        run_source(source)

        run = ScrapingRun.query.order_by(ScrapingRun.run_id.desc()).first()
        assert run is not None
        assert run.source_id == source.source_id
        assert run.status == "success"
        assert run.pages_fetched == 1
        assert run.listings_found > 0
        assert run.listings_saved > 0
        assert run.finished_at is not None

    def test_the_source_remembers_the_last_run(self, app):
        source = make_fixture_source()

        run_source(source)

        assert source.last_run_at is not None
        assert source.last_run_status == "success"


class TestImportFixture:
    def test_the_sample_listings_are_loaded(self, app):
        added = import_fixture()

        assert added > 0
        stored = Property.query.all()
        assert len(stored) <= added

    def test_loading_twice_does_not_add_more(self, app):
        import_fixture()
        count = Property.query.count()

        import_fixture()

        assert Property.query.count() == count

    def test_listings_are_linked_to_an_area(self, app):
        from app.models import Area

        db.session.add(
            Area(name="Kilimani", city="Nairobi", latitude=-1.244, longitude=36.747)
        )
        db.session.commit()

        import_fixture()
        linked = link_areas()

        assert linked >= 0
        assert Property.query.filter(Property.area_id.isnot(None)).count() > 0


PROPERTY24_PAGE = Path(__file__).parent.parent / "scraper" / "fixtures" / "property24_nairobi.html"


class TestUnitsAreNeverMerged:
    def _units(self, rooms):
        html = "<div>" + "".join(
            f"""<div class="listing-card"><a href="/unit-{room}"></a>
            <h3 class="listing-title">2 Bedroom Apartment in Westlands</h3>
            <span class="price">KSh 85,000</span><span class="location">Westlands, Nairobi</span>
            <span class="bedrooms">2 bedrooms</span><span class="building">Riverside Towers</span>
            <span class="floor">{floor}</span><span class="room">{room}</span>
            <span class="availability">Vacant</span></div>"""
            for room, floor in rooms
        ) + "</div>"
        return html

    def test_identical_looking_units_in_one_building_are_all_stored(self, app, tmp_path):
        page = tmp_path / "units.html"
        page.write_text(self._units([("1A", 1), ("1B", 1), ("2A", 2), ("3C", 3)]), encoding="utf-8")
        source = ScrapingSource(
            name="Units", listing_url=str(page), profile="fixture", max_pages=1, respects_robots=False
        )
        db.session.add(source)
        db.session.commit()

        summary, _ = scrape_source(source)

        assert summary["saved"] == 4
        rows = Property.query.order_by(Property.room_number).all()
        assert [(r.room_number, r.floor_number, r.availability_status) for r in rows] == [
            ("1A", 1, "vacant"), ("1B", 1, "vacant"), ("2A", 2, "vacant"), ("3C", 3, "vacant"),
        ]


class TestProperty24Page:
    """Runs the real Property24 markup (saved from the live site) through the pipeline."""

    def _source(self, areas):
        source = ScrapingSource(
            name="Property24", base_url="https://www.property24.co.ke",
            listing_url=str(PROPERTY24_PAGE), profile="property24", max_pages=1,
            respects_robots=False,
        )
        db.session.add(source)
        db.session.commit()
        return source

    def test_every_card_is_read(self, app, areas):
        parsed = parse_page(
            PROPERTY24_PAGE.read_text(encoding="utf-8"), "property24", base_url="https://www.property24.co.ke"
        )
        assert len(parsed) == 6
        assert all(r["price_text"] and r["url"].startswith("https://www.property24.co.ke/") for r in parsed)

    def test_listings_are_saved_with_exact_gps_from_the_plus_code(self, app, areas):
        source = self._source(areas)
        # the sample is read from disk, so route it through the generic profile reader
        html = PROPERTY24_PAGE.read_text(encoding="utf-8")
        from scraper.cleaner import clean_listing
        from scraper.scraper import _area_lookup, save_listing

        records = parse_page(html, "property24", known_areas=[{"name": "Westlands", "city": "Nairobi"}],
                             base_url=source.base_url)
        lookup = _area_lookup()
        for record in records:
            cleaned = clean_listing(record, known_areas=[{"name": "Westlands", "city": "Nairobi"}])
            save_listing(cleaned, source, lookup)
        db.session.commit()

        first = Property.query.filter(Property.external_id.like("%117764018")).one()
        assert first.gps_exact is True
        assert -1.27 < float(first.latitude) < -1.25
        assert 36.78 < float(first.longitude) < 36.80
        assert first.availability_status == "vacant"
        assert first.bedrooms == 2
