"""
Checks a site's robots.txt before scraping it, so the engine only
visits pages that the target website explicitly allows automated bots to read.
Use this before pointing the scraper at any real, live website.
"""
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin

USER_AGENT = "HousingAggregatorBot/1.0"


def is_scraping_allowed(base_url, path="/"):
    """
    base_url example: "https://example.com"
    path example: "/listings"
    Returns True only if robots.txt allows our bot to fetch that path.
    """
    parser = RobotFileParser()
    parser.set_url(urljoin(base_url, "/robots.txt"))
    parser.read()
    return parser.can_fetch(USER_AGENT, urljoin(base_url, path))
