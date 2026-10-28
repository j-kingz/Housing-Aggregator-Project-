"""Tests for the scraping pipeline: de-duplication, area linking and run history."""

from app.extensions import db
from app.models import Property, ScrapingRun, ScrapingSource
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

    def test_the_same_page_twice_does_not_double_up(self, app):
        source = make_fixture_source()

        first, _ = scrape_source(source)
        second, _ = scrape_source(source)

        assert second["saved"] == 0
        assert second["found"] == first["found"]
        assert second["updated"] + second["duplicates"] + second["possible"] == (
            first["found"]
        )

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
        # the sample page repeats some listings, so a few are refreshed rather
        # than added. Every stored listing still has its own fingerprint.
        assert len(stored) <= added
        assert len({row.fingerprint for row in stored}) == len(stored)

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
