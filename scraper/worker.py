"""The background scraping worker.

Runs the scraper on a timer so the site always has fresh listings without
the web server having to do any of the work. This is what the scraper
container runs.

    python -m scraper.worker --every 30
"""

import argparse
import logging
import time

from app import create_app
from scraper.scraper import run_all

log = logging.getLogger(__name__)


def run_once():
    """Run every enabled source once and report what happened."""
    app = create_app()
    with app.app_context():
        results = run_all()
        for source, summary in results:
            log.info(
                "%s: %s pages, %s found, %s new, %s duplicates, %s skipped",
                source.name,
                summary["pages"],
                summary["found"],
                summary["saved"],
                summary["duplicates"] + summary["possible"],
                summary["errors"],
            )
        return results


def loop(every_minutes):
    """Keep running the scraper until the container is stopped."""
    interval = max(1, every_minutes) * 60
    log.info("Scraper worker started, running every %s minutes", every_minutes)

    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001 - the worker must not die on one bad run
            log.exception("A scrape run failed, waiting for the next one")

        time.sleep(interval)


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(prog="scraper.worker")
    parser.add_argument(
        "--every", type=int, default=30, help="minutes between runs (default 30)"
    )
    parser.add_argument(
        "--once", action="store_true", help="run once and stop, useful for a cron job"
    )
    args = parser.parse_args(argv)

    if args.once:
        run_once()
    else:
        loop(args.every)


if __name__ == "__main__":
    main()
