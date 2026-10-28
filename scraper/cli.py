"""Command line entry point for the scraper.

    python -m scraper.cli sources              list the configured sites
    python -m scraper.cli run                   scrape every enabled source
    python -m scraper.cli run --source "BuyRentKenya" --pages 2
    python -m scraper.cli import-fixture        load the bundled sample page
    python -m scraper.cli match-notifications   alert renters about new listings
    python -m scraper.cli areas                 list the neighbourhood reference data
"""

import argparse
import logging
import sys

from app import create_app
from app.extensions import db
from app.models import Area, ScrapingSource
from scraper.scraper import import_fixture, run_all


def build_parser():
    parser = argparse.ArgumentParser(prog="scraper", description="Housing Aggregator scraper")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sources", help="list the configured scraping sources")

    run = sub.add_parser("run", help="scrape the enabled sources")
    run.add_argument("--source", help="only scrape the source with this name")
    run.add_argument("--pages", type=int, help="how many pages to read from each site")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and parse but do not write anything to the database",
    )

    sub.add_parser("import-fixture", help="load the bundled sample listings page")
    sub.add_parser("match-notifications", help="alert renters about matching new listings")
    sub.add_parser("areas", help="list the neighbourhood reference data")

    return parser


def cmd_sources():
    sources = ScrapingSource.query.order_by(ScrapingSource.source_id).all()
    if not sources:
        print("No sources configured. Run python init_db.py first.")
        return
    print(f"{'name':<20}{'enabled':<9}{'profile':<14}{'delay':<8}{'pages':<7}last run")
    for source in sources:
        print(
            f"{source.name:<20}{'yes' if source.enabled else 'no':<9}"
            f"{source.profile or 'generic':<14}{source.delay_seconds:<8}"
            f"{source.max_pages:<7}{source.last_run_at or 'never'}"
        )


def cmd_areas():
    areas = Area.query.order_by(Area.city, Area.name).all()
    print(f"{len(areas)} areas")
    for area in areas:
        print(f"  {area.name:<20}{area.city:<12}{area.latitude}, {area.longitude}")


def cmd_match_notifications():
    from app.notifications.services import match_new_listings

    # match every listing that has not been offered to anyone yet
    from app.models import Property

    ids = [
        listing.listing_id
        for listing in Property.query.filter(Property.is_active.is_(True)).all()
    ]
    created = match_new_listings(ids, only_new=False)
    print(f"Created {created} notifications.")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    app = create_app()
    with app.app_context():
        if args.command == "sources":
            cmd_sources()
        elif args.command == "areas":
            cmd_areas()
        elif args.command == "import-fixture":
            print(f"Imported {import_fixture()} sample listings.")
        elif args.command == "match-notifications":
            cmd_match_notifications()
        elif args.command == "run":
            if args.dry_run:
                print("Dry run: nothing will be written to the database.")
            results = run_all(pages=args.pages, only=args.source)
            if not results:
                print("No enabled sources to scrape.")
                return 1
            for source, summary in results:
                print(
                    f"{source.name}: {summary['pages']} pages, "
                    f"{summary['found']} found, {summary['saved']} new, "
                    f"{summary['updated']} updated, {summary['duplicates']} duplicates, "
                    f"{summary['possible']} possible, {summary['errors']} skipped"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
