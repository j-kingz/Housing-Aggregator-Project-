"""The HTTP layer of the scraper.

Everything the scraper requests goes through here so the defensive rules from
the proposal (3.3.2 Ethical Compliance) are applied in one place:

* robots.txt is checked before the first request to a host
* a deliberate delay is left between requests
* requests time out instead of hanging
* a failed request is retried a couple of times and then skipped

The rest of the scraper never calls requests directly.
"""

import logging
import random
import time
from urllib.parse import urlparse

import requests

from scraper import robots_checker

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-KE,en;q=0.9",
    "Connection": "keep-alive",
}


class FetchError(Exception):
    """Raised when a page could not be downloaded."""


class Fetcher:
    """Downloads pages politely and reliably."""

    def __init__(
        self,
        user_agent=robots_checker.USER_AGENT,
        delay=5.0,
        timeout=20,
        max_retries=2,
        respect_robots=True,
    ):
        self.user_agent = user_agent
        self.delay = max(0.0, float(delay))
        self.timeout = timeout
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.session.headers["User-Agent"] = user_agent
        self._last_request_at = None
        self._allowed_hosts = {}

    # -- internals -----------------------------------------------------
    def _sleep_if_needed(self):
        """Wait between requests so we never hammer a site."""
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay - elapsed
        if remaining > 0:
            # a small random jitter makes the traffic less machine-like
            time.sleep(remaining + random.uniform(0, min(1.0, self.delay * 0.1)))

    def _host_allowed(self, url):
        """Ask robots.txt once per host, then remember the answer."""
        parsed = urlparse(url)
        host = parsed.netloc
        if host in self._allowed_hosts:
            return self._allowed_hosts[host]

        base = f"{parsed.scheme}://{host}"
        allowed = True
        if self.respect_robots:
            allowed = robots_checker.is_allowed(base, url, user_agent=self.user_agent)
            if allowed:
                # if the site publishes a crawl delay we take the slower of the two
                site_delay = robots_checker.crawl_delay(base, user_agent=self.user_agent)
                self.delay = max(self.delay, site_delay)
            else:
                log.warning("robots.txt does not allow %s to read %s", self.user_agent, url)
        self._allowed_hosts[host] = allowed
        return allowed

    # -- public api ----------------------------------------------------
    def get(self, url):
        """Download a page and return its HTML. Raises FetchError on failure."""
        if not self._host_allowed(url):
            raise FetchError(f"robots.txt does not allow reading {url}")

        last_error = None
        for attempt in range(self.max_retries + 1):
            self._sleep_if_needed()
            try:
                response = self.session.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()

                if response.status_code in (403, 429):
                    raise FetchError(
                        f"{url} returned {response.status_code}. "
                        "The site is rate limiting or blocking the request."
                    )
                if response.status_code >= 500:
                    raise FetchError(f"{url} returned {response.status_code}")

                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding
                return response.text

            except requests.RequestException as exc:
                last_error = exc
                log.warning("Attempt %s for %s failed: %s", attempt + 1, url, exc)
                time.sleep(min(2 ** attempt, 10))

        raise FetchError(f"Could not download {url}: {last_error}")

    def get_paginated(self, url_template, max_pages=1):
        """Yield (page_number, html) for each page of a paginated listing.

        url_template is a format string such as
        "https://example.com/rent?page={page}". Pages are requested one at a
        time with the configured delay in between.
        """
        page = 1
        while page <= max_pages:
            url = url_template.format(page=page) if "{page}" in url_template else url_template
            try:
                html = self.get(url)
            except FetchError as exc:
                log.warning("Stopping pagination at page %s: %s", page, exc)
                break

            yield page, html
            page += 1
