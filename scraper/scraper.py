# Scraper - harvests public listings and stores them in the database.
#
# The pipeline is:  fetch -> parse -> clean -> save (listings are never dropped as duplicates)
#
# Run from the project folder:
#     python -m scraper.cli sources          list the configured sites
#     python -m scraper.cli run               scrape every enabled source
#     python -m scraper.cli run --source "BuyRentKenya" --pages 2
#     python -m scraper.cli import-fixture    load the bundled sample page
#
# Before pointing it at a live site, robots.txt is checked (robots_checker.py)
# and a delay is left between requests so we don't hammer anyone's server.

import logging
from datetime import datetime, timedelta
from pathlib import Path

from app import create_app
from app.extensions import db
from app.geo import decode_plus_code
from app.models import Area, Property, ScrapingRun, ScrapingSource, utcnow
from scraper import robots_checker
from scraper.cleaner import clean_listing
from scraper.fetcher import Fetcher, FetchError
from scraper.parser import parse_page

log = logging.getLogger(__name__)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_listings.html"
SAMPLE_FIXTURE = FIXTURE
NAIROBI_FIXTURE = Path(__file__).parent / "fixtures" / "nairobi_listings.html"
SOURCE_NAME = "Sample fixture"

# listings that have not been seen for this long are marked as no longer active
STALE_AFTER_DAYS = 60


def known_areas():
    """The neighbourhood list, used to fill in missing location data."""
    return [{"name": area.name, "city": area.city} for area in Area.query.all()]


def _area_lookup():
    """Map of area name -> Area row."""
    return {area.name.lower(): area for area in Area.query.all()}


def _find_area(area_name, area_lookup):
    if not area_name:
        return None
    return area_lookup.get(area_name.strip().lower())


def _existing_matches(cleaned, source):
    """Find the row this very advert was stored as on an earlier run.

    This is not de-duplication. Listings that merely look alike are all kept,
    including every unit of the same building. The only thing recognised is
    the same advert from the same source being met again, so that row is
    refreshed instead of the table growing on every run.
    """
    source_id = source.source_id if source is not None else None
    if cleaned.get("external_id") and source_id is not None:
        match = Property.query.filter_by(
            source_id=source_id, external_id=cleaned["external_id"]
        ).first()
        if match:
            return match

    query = Property.query.filter_by(fingerprint=cleaned["fingerprint"])
    if source_id is not None:
        query = query.filter_by(source_id=source_id)
    return query.first()


def _city_reference(city):
    """Any neighbourhood of the city, used as the anchor for a short Plus Code."""
    if not city:
        return None
    return Area.query.filter(Area.city.ilike(city), Area.latitude.isnot(None)).first()


def _merged_availability(current, scraped):
    """The availability to keep when a listing is scraped again.

    A unit reserved through an M-Pesa payment stays reserved, and a status the
    platform knows (from a vacancy check or an earlier advert) is not wiped out
    by an advert that simply does not say.
    """
    scraped = scraped or "unknown"
    if current == "reserved":
        return current
    if scraped == "unknown" and current in ("vacant", "occupied"):
        return current
    return scraped


def _apply(cleaned, listing, area):
    """Copy the cleaned values onto a Property row."""
    listing.title = cleaned["title"]
    listing.rentamount = cleaned["rentamount"]
    listing.bedrooms = cleaned["bedrooms"]
    listing.bathrooms = cleaned["bathrooms"]
    listing.category = cleaned["category"]
    listing.building_name = cleaned["building_name"]
    listing.floor_number = cleaned["floor_number"]
    listing.room_number = cleaned["room_number"]
    listing.availability_status = _merged_availability(
        listing.availability_status, cleaned["availability_status"]
    )
    listing.city = cleaned["city"]
    listing.address = cleaned["address"]
    if not listing.city and area is not None:
        listing.city = area.city
    listing.description = cleaned["description"]
    listing.amenities = cleaned["amenities"]
    listing.size_sqft = cleaned["size_sqft"]
    listing.source_url = cleaned["source_url"]
    listing.external_id = cleaned["external_id"]
    listing.fingerprint = cleaned["fingerprint"]
    if cleaned.get("image_url"):
        listing.image_url = cleaned["image_url"]
    listing.area_id = area.area_id if area else None

    # GPS: the exact point the advert gave us wins, otherwise the centre of
    # the neighbourhood is used and the listing is marked as approximate.
    if cleaned.get("latitude") is not None and cleaned.get("longitude") is not None:
        listing.latitude = cleaned["latitude"]
        listing.longitude = cleaned["longitude"]
        listing.gps_exact = True
    elif area is not None:
        listing.latitude = area.latitude
        listing.longitude = area.longitude
        listing.gps_exact = False


def save_listing(cleaned, source, area_lookup):
    """Save one cleaned listing. Returns ("saved" | "updated", the row)."""
    area = _find_area(cleaned.get("area_name"), area_lookup)
    existing = _existing_matches(cleaned, source)

    # an exact GPS point can be printed in the advert as a Plus Code
    if cleaned.get("latitude") is None and cleaned.get("plus_code"):
        reference = area or _city_reference(cleaned.get("city"))
        point = decode_plus_code(
            cleaned["plus_code"],
            reference.latitude if reference is not None else None,
            reference.longitude if reference is not None else None,
        )
        if point:
            cleaned["latitude"], cleaned["longitude"] = point

    if existing is not None:
        _apply(cleaned, existing, area)
        existing.scraped_at = utcnow()
        existing.is_active = True
        existing.listingdate = existing.listingdate or utcnow().date()
        return "updated", existing

    listing = Property(
        source_name=source.name if source else SOURCE_NAME,
        source_id=source.source_id if source else None,
        listingdate=utcnow().date(),
        scraped_at=utcnow(),
        is_active=True,
    )
    _apply(cleaned, listing, area)
    db.session.add(listing)
    return "saved", listing


def link_areas():
    """Fill in the neighbourhood link for listings that are missing one.

    This is the "2.2 Fill missing data" step in the Level 2 DFD. It runs over
    listings already in the database so older rows get their area and
    coordinates too.
    """
    area_lookup = _area_lookup()
    linked = 0

    for listing in Property.query.filter(Property.area_id.is_(None)).all():
        area = None
        for name, row in area_lookup.items():
            if not name:
                continue
            address = (listing.address or "").strip().lower()
            if address and (address == name or address.startswith(name)):
                area = row
                break
        if area is None:
            continue

        listing.area_id = area.area_id
        listing.latitude = area.latitude
        listing.longitude = area.longitude
        if not listing.city:
            listing.city = area.city
        linked += 1

    if linked:
        db.session.commit()
    return linked


def mark_stale(source, days=STALE_AFTER_DAYS):
    """Hide listings from a source that have not been seen for a while."""
    cutoff = utcnow().date() - timedelta(days=days)
    if source is None:
        return 0
    stale = Property.query.filter(
        Property.source_id == source.source_id,
        Property.is_active.is_(True),
        Property.scraped_at.isnot(None),
        Property.scraped_at < datetime.combine(cutoff, datetime.min.time()),
    ).all()
    for listing in stale:
        listing.is_active = False
    if stale:
        db.session.commit()
    return len(stale)


def _fixture_pages(source):
    """Read the bundled sample page from disk instead of the internet."""
    path = Path(source.listing_url) if source.listing_url else NAIROBI_FIXTURE
    if not path.is_file():
        path = NAIROBI_FIXTURE
    yield 1, path.read_text(encoding="utf-8")


def scrape_source(source, pages=None, fetcher=None, run=None):
    """Run the pipeline for one source. Returns a summary dict."""
    areas = known_areas()
    area_lookup = _area_lookup()
    max_pages = pages if pages is not None else (source.max_pages or 1)

    if fetcher is None:
        fetcher = Fetcher(
            user_agent=source.user_agent or robots_checker.USER_AGENT,
            delay=source.delay_seconds or 0,
            respect_robots=bool(source.respects_robots),
        )

    summary = {
        "pages": 0,
        "found": 0,
        "saved": 0,
        "updated": 0,
        "errors": 0,
    }
    new_listing_ids = []

    if (source.profile or "").lower() == "fixture":
        source_pages = _fixture_pages(source)
    else:
        source_pages = fetcher.get_paginated(source.listing_url, max_pages)

    try:
        for page_number, html in source_pages:
            summary["pages"] += 1
            records = parse_page(
                html,
                profile=source.profile or "generic",
                known_areas=areas,
                base_url=source.base_url,
            )
            summary["found"] += len(records)

            for record in records:
                try:
                    cleaned = clean_listing(record, known_areas=areas)
                    if not cleaned:
                        summary["errors"] += 1
                        log.info("Skipped a listing with missing title or price")
                        continue

                    outcome, listing = save_listing(cleaned, source, area_lookup)
                    if outcome == "saved":
                        summary["saved"] += 1
                        db.session.flush()
                        new_listing_ids.append(listing.listing_id)
                    else:
                        summary["updated"] += 1
                except Exception as exc:  # noqa: BLE001 - one bad record must not stop the run
                    summary["errors"] += 1
                    log.warning("Skipped a listing that could not be saved: %s", exc)

            db.session.commit()

    except FetchError as exc:
        log.warning("Source %s could not be read: %s", source.name, exc)
        if run is not None:
            run.message = str(exc)[:255]

    if summary["saved"]:
        summary["stale"] = mark_stale(source)
    else:
        summary["stale"] = 0

    return summary, new_listing_ids


def run_source(source, pages=None, notify=True):
    """Scrape one source and record the run in the database."""
    run = ScrapingRun(source_id=source.source_id, status="running", started_at=utcnow())
    db.session.add(run)
    db.session.commit()

    log.info("Scraping %s", source.name)
    summary, new_listing_ids = scrape_source(source, pages=pages, run=run)

    run.finished_at = utcnow()
    run.pages_fetched = summary["pages"]
    run.listings_found = summary["found"]
    run.listings_saved = summary["saved"]
    run.duplicates_skipped = 0
    run.errors_skipped = summary["errors"]
    run.status = "success" if summary["pages"] else "failed"
    if summary["saved"]:
        run.message = f"{summary['saved']} new, {summary['updated']} updated"
    elif summary["updated"]:
        run.message = f"{summary['updated']} refreshed, nothing new"

    source.last_run_at = utcnow()
    source.last_run_status = run.status
    db.session.commit()

    if notify and new_listing_ids:
        from app.notifications.services import match_new_listings

        created = match_new_listings(new_listing_ids)
        log.info("Created %s notifications for new listings", created)

    return summary


def run_all(pages=None, only=None):
    """Scrape every enabled source. Returns a list of (source, summary) pairs."""
    results = []
    query = ScrapingSource.query
    if only:
        query = query.filter(ScrapingSource.name == only)
    for source in query.filter(ScrapingSource.enabled.is_(True)).all():
        summary = run_source(source, pages=pages)
        results.append((source, summary))
    return results


def import_fixture(path=None):
    """Load a bundled sample listings page into the database.

    Defaults to the larger Nairobi sample page. Returns the number of
    listings that were added or refreshed.
    """
    areas = known_areas()
    area_lookup = _area_lookup()

    path = Path(path) if path else NAIROBI_FIXTURE
    html = path.read_text(encoding="utf-8")
    records = parse_page(html, profile="fixture", known_areas=areas)

    source = ScrapingSource.query.filter_by(name=SOURCE_NAME).first()
    if source is None:
        source = ScrapingSource(name=SOURCE_NAME, profile="fixture", enabled=True)
        db.session.add(source)
        db.session.flush()

    added = 0
    for record in records:
        try:
            cleaned = clean_listing(record, known_areas=areas)
            if not cleaned:
                continue
            outcome, _ = save_listing(cleaned, source, area_lookup)
            if outcome in ("saved", "updated"):
                added += 1
        except Exception as exc:  # noqa: BLE001 - keep going through the sample file
            log.warning("Skipped a sample listing: %s", exc)

    db.session.commit()
    link_areas()
    return added


def build_app():
    """Create the Flask application (kept separate so scripts can reuse it)."""
    return create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    app = build_app()
    with app.app_context():
        print(f"Imported {import_fixture()} sample listings.")
