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
        if not Area.query.filter_by(name=name).first():
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


def add_sources():
    """Register the default scraping sources."""
    added = 0
    for source in DEFAULT_SOURCES:
        if not ScrapingSource.query.filter_by(name=source["name"]).first():
            db.session.add(ScrapingSource(**source))
            added += 1
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
