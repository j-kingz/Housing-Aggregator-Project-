"""
Scraping engine, step 1: parses real HTML into structured listings.
For now it reads a local sample HTML page (scraper/fixtures/sample_listings.html)
instead of a live website, so we can prove the parsing + database pipeline works
before pointing it at any real, third-party site (which first needs a robots.txt
check — see scraper/robots_checker.py).

Run it from the project root as a module, otherwise Python cannot find the "app" package:
    python -m scraper.scraper
"""
import time
from pathlib import Path
from app import create_app
from app.extensions import db
from app.models import LandlordDetails, Property, User, Role
from scraper.parser import parse_listings

SCRAPE_DELAY_SECONDS = 2  # be polite to real servers once you scrape live sites
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_listings.html"


def fetch_sample_listings():
    """Reads and parses the local mock listings page."""
    html_text = FIXTURE_PATH.read_text(encoding="utf-8")
    return parse_listings(html_text)


def get_or_create_system_landlord():
    """Scraped listings need a landlord owner; use one placeholder account for now."""
    role = Role.query.filter_by(name="Landlord").first()
    if role is None:
        role = Role(name="Landlord", description="Lists properties")
        db.session.add(role)
        db.session.flush()

    user = User.query.filter_by(email="scraper@system.local").first()
    if user is None:
        user = User(
            firstname="System",
            lastname="Scraper",
            email="scraper@system.local",
            role_id=role.role_id,
        )
        user.set_password("not-a-real-login")
        db.session.add(user)
        db.session.flush()

    landlord = db.session.get(LandlordDetails, user.user_id)
    if landlord is None:
        landlord = LandlordDetails(landlord_id=user.user_id, businessname="Scraped Listings")
        db.session.add(landlord)
        db.session.flush()

    return landlord


def run_scrape():
    app = create_app()
    with app.app_context():
        landlord = get_or_create_system_landlord()

        for item in fetch_sample_listings():
            exists = Property.query.filter_by(title=item["title"], city=item["city"]).first()
            if exists:
                continue

            listing = Property(
                landlord_id=landlord.landlord_id,
                title=item["title"],
                rentamount=item["rentamount"],
                bedrooms=item["bedrooms"],
                bathrooms=item["bathrooms"],
                category=item["category"],
                city=item["city"],
                address=item["address"],
            )
            db.session.add(listing)
            time.sleep(SCRAPE_DELAY_SECONDS)

        db.session.commit()
        print("Scrape finished. Sample listings saved to the database.")


if __name__ == "__main__":
    run_scrape()
