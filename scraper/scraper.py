# Scraper - still a work in progress.
#
# Right now it reads the mock page in scraper/fixtures/ instead of a real site,
# so the parse -> clean -> save steps can be tested without hitting anyone's server.
# Before pointing it at a live site, check robots.txt first (robots_checker.py)
# and add a delay between requests.
#
# Run from the project folder:  python -m scraper.scraper

from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import Property
from scraper.parser import parse_listings

FIXTURE = Path(__file__).parent / "fixtures" / "sample_listings.html"
SOURCE_NAME = "Sample fixture"


def run():
    html = FIXTURE.read_text(encoding="utf-8")
    listings = parse_listings(html)

    app = create_app()
    with app.app_context():
        added = 0
        for item in listings:
            # crude duplicate check until proper dedup is written
            exists = Property.query.filter_by(
                title=item["title"], city=item["city"], address=item["address"]
            ).first()
            if exists:
                continue

            db.session.add(Property(source_name=SOURCE_NAME, **item))
            added += 1

        db.session.commit()
        print(f"Parsed {len(listings)} listings, saved {added} new ones.")


if __name__ == "__main__":
    run()
