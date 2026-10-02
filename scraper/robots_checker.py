# Checks robots.txt before we scrape anything, so we only read pages a site allows bots on.

from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

USER_AGENT = "HousingAggregatorBot/1.0"


def is_allowed(base_url, path="/"):
    # e.g. is_allowed("https://example.com", "/rentals")
    robots = RobotFileParser()
    robots.set_url(urljoin(base_url, "/robots.txt"))
    robots.read()
    return robots.can_fetch(USER_AGENT, urljoin(base_url, path))
