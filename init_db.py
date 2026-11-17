# Sets up the MySQL database for the project.
#
#   python init_db.py           create/upgrade the database + tables and seed them
#   python init_db.py --reset   drop everything and start again (asks first)
#   python init_db.py --sample  also load the bundled sample listings
#
# The command is safe to run on an existing database: missing tables and
# columns are added, nothing already stored is lost.

import sys

import pymysql

from config import Config
from app import create_app
from app.extensions import db
from app.migrations import run_migrations
from app.models import Area, Role, ScrapingSource
from app.seed_data import AREAS, DEFAULT_SOURCES

ROLES = [
    ("Renter", "Searches for housing and views price analytics"),
    ("Landlord", "Adds and manages their own property listings"),
    ("Administrator", "Manages user accounts and scraping sources"),
    ("Verifier", "Performs paid vacancy checks for renters"),
]


def make_database(reset=False):
    conn = pymysql.connect(
        host=Config.DB_HOST,
        port=Config.DB_PORT,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
    )
    with conn.cursor() as cur:
        if reset:
            cur.execute(f"DROP DATABASE IF EXISTS `{Config.DB_NAME}`")
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{Config.DB_NAME}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.close()


def add_roles():
    """Make sure the three roles exist."""
    added = 0
    for name, description in ROLES:
        if not Role.query.filter_by(name=name).first():
            db.session.add(Role(name=name, description=description))
            added += 1
    if added:
        db.session.commit()
    return added


def add_areas():
    """Load the neighbourhood list used for search filters and distances."""
    added = 0
    for name, city, county, lat, lon, description in AREAS:
        existing = Area.query.filter_by(name=name).first()
        if existing is not None:
            # keep the stored centre point in step with the corrected seed list
            if (
                existing.latitude is None
                or abs(float(existing.latitude) - lat) > 1e-6
                or abs(float(existing.longitude) - lon) > 1e-6
            ):
                existing.latitude, existing.longitude = lat, lon
                added += 1
        else:
            db.session.add(
                Area(
                    name=name,
                    city=city,
                    county=county,
                    latitude=lat,
                    longitude=lon,
                    description=description,
                )
            )
            added += 1
    if added:
        db.session.commit()
    return added


def refresh_listing_gps():
    """Point listings that only have an approximate location at the corrected area centre."""
    from app.models import Property

    moved = 0
    rows = Property.query.filter(
        Property.area_id.isnot(None), Property.gps_exact.isnot(True)
    ).all()
    for listing in rows:
        area = listing.area
        if area is not None and area.latitude is not None:
            listing.latitude, listing.longitude = area.latitude, area.longitude
            listing.gps_exact = False
            moved += 1
    if moved:
        db.session.commit()
    return moved


def clean_bad_unit_numbers():
    """Remove unit numbers that were really "2 Bedrooms" read by an older parser."""
    from sqlalchemy import or_

    from app.models import Property

    rows = Property.query.filter(
        or_(Property.room_number.ilike("%bed%"), Property.room_number.ilike("%bath%"))
    ).all()
    for row in rows:
        row.room_number = None
    if rows:
        db.session.commit()
    return len(rows)


def remove_sample_data():
    """Delete the old bundled demo listings so only real scraped or landlord listings remain."""
    from app.models import Favorite, Notification, Payment, Property, ScrapingRun

    sample = ScrapingSource.query.filter_by(name="Sample fixture").first()
    ids = [
        row.listing_id
        for row in Property.query.filter(Property.source_name == "Sample fixture").all()
    ]
    if ids:
        # anything that points at those listings goes first
        Notification.query.filter(Notification.listing_id.in_(ids)).delete(synchronize_session=False)
        Favorite.query.filter(Favorite.listing_id.in_(ids)).delete(synchronize_session=False)
        Payment.query.filter(Payment.listing_id.in_(ids)).delete(synchronize_session=False)
        Property.query.filter(Property.listing_id.in_(ids)).delete(synchronize_session=False)
    if sample is not None:
        ScrapingRun.query.filter_by(source_id=sample.source_id).delete(synchronize_session=False)
        db.session.delete(sample)
    db.session.commit()
    return len(ids)


def add_sources():
    """Register the default scraping sources."""
    added = 0
    for source in DEFAULT_SOURCES:
        existing = ScrapingSource.query.filter_by(name=source["name"]).first()
        if existing is None:
            db.session.add(ScrapingSource(**source))
            added += 1
        else:
            # the address and profile of a site can change, so refresh them
            for field in ("base_url", "listing_url", "profile", "notes"):
                setattr(existing, field, source[field])
    if added:
        db.session.commit()
    return added


def load_sample_listings():
    """Load the bundled sample listings so the search page is not empty."""
    from scraper.scraper import import_fixture

    return import_fixture()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    want_sample = "--sample" in sys.argv

    if reset:
        answer = input(f"This deletes ALL data in '{Config.DB_NAME}'. Type yes to continue: ")
        if answer.strip().lower() != "yes":
            print("Cancelled.")
            sys.exit()

    make_database(reset)

    app = create_app()
    with app.app_context():
        added_columns, backfilled = run_migrations()
        roles = add_roles()
        areas = add_areas()
        sources = add_sources()
        removed_sample = remove_sample_data()
        if removed_sample:
            print(f"  sample listings removed: {removed_sample}")
        refresh_listing_gps()
        cleaned_units = clean_bad_unit_numbers()
        if cleaned_units:
            print(f"  unit numbers cleaned: {cleaned_units}")

        print(f"'{Config.DB_NAME}' is ready.")
        if added_columns:
            print(f"  columns added: {', '.join(added_columns)}")
        if backfilled:
            print(f"  rows given default values: {backfilled}")
        if roles:
            print(f"  roles added: {roles}")
        if areas:
            print(f"  areas added: {areas}")
        if sources:
            print(f"  scraping sources added: {sources}")

    if want_sample:
        from scraper.scraper import import_fixture

        with app.app_context():
            saved = import_fixture()
        print(f"  sample listings imported: {saved}")
