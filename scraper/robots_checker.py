# Checks robots.txt before we scrape anything, so we only read pages a site allows bots on.
#
# The proposal (3.7.5) makes robots.txt compliance a hard requirement of the
# project, so this module is used by the fetcher before every single request.

import logging
import threading
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

USER_AGENT = "HousingAggregatorBot/1.0 (+academic project; contact via repository)"
DEFAULT_TIMEOUT = 10

# robots.txt files are cached per host so a multi-page run only fetches them once
_cache = {}
_lock = threading.Lock()


def _robots_for(base_url, user_agent=USER_AGENT, timeout=DEFAULT_TIMEOUT):
    """Fetch and parse the robots.txt for a host. Returns a RobotFileParser."""
    robots_url = urljoin(base_url, "/robots.txt")
    with _lock:
        cached = _cache.get(robots_url)
    if cached is not None:
        return cached

    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = requests.get(
            robots_url, timeout=timeout, headers={"User-Agent": user_agent}
        )
        if response.status_code >= 400:
            # no robots.txt means no restrictions published
            parser.parse(["User-agent: *", "Allow: /"])
        else:
            parser.parse(response.text.splitlines())
    except requests.RequestException as exc:
        # if we cannot read robots.txt we treat the site as disallowed and
        # skip it rather than guessing
        log.warning("Could not read %s (%s). Treating the site as off limits.", robots_url, exc)
        parser.parse(["User-agent: *", "Disallow: /"])

    with _lock:
        _cache[robots_url] = parser
    return parser


def is_allowed(base_url, path="/", user_agent=USER_AGENT, timeout=DEFAULT_TIMEOUT):
    """Is this user agent allowed to fetch this path?

    e.g. is_allowed("https://example.com", "/rentals")
    """
    parser = _robots_for(base_url, user_agent=user_agent, timeout=timeout)
    return parser.can_fetch(user_agent, urljoin(base_url, path))


def crawl_delay(base_url, user_agent=USER_AGENT, timeout=DEFAULT_TIMEOUT):
    """The Crawl-delay the site asks for, in seconds. 0 when the site is silent."""
    parser = _robots_for(base_url, user_agent=user_agent, timeout=timeout)
    delay = parser.crawl_delay(user_agent)
    try:
        return float(delay) if delay is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def clear_cache():
    """Forget the cached robots.txt files. Used by the tests."""
    with _lock:
        _cache.clear()


def host_of(url):
    return urlparse(url).netloc


def wait_a_moment(seconds):
    """Sleep helper so callers do not have to import time themselves."""
    if seconds > 0:
        time.sleep(seconds)
