"""Reads listing pages and pulls the property details out of them.

Real estate sites change their layout often, so the parser works in two
stages:

1. A profile for the site we know (the CSS selectors it uses today).
2. A heuristic fallback that finds the price, the title and the location in
   any listing grid, even if the site's own markup has changed.

The heuristic fallback is what keeps the pipeline alive when a site redesigns
its pages, which the proposal calls out as a reliability requirement
(3.3.2 "Backend scraping methods must tolerate unclean real-world data and
unexpected third-party layout changes").
"""

import re

from bs4 import BeautifulSoup, Tag

# Each profile lists several selectors and the first one that matches is used.
# The extra candidates make the profiles survive small changes to a site's
# markup without needing a code change.
PROFILES = {
    "fixture": {
        "card": [".listing-card"],
        "title": [".listing-title", "h2", "h3"],
        "price": [".price"],
        "bedrooms": [".bedrooms"],
        "bathrooms": [".bathrooms"],
        "location": [".location"],
        "size": [".size"],
        "amenities": [".amenities"],
        "description": [".description"],
    },
    "buyrentkenya": {
        "card": [
            ".property-listing",
            ".listing-card",
            "[data-qa='property-listing']",
            "article.property",
        ],
        "title": [
            "[data-qa='listing-title']",
            ".property-listing-title",
            "h2 a",
            "h2",
            "h3",
            "a[title]",
        ],
        "price": [
            "[data-qa='listing-price']",
            ".property-listing-price",
            ".price",
            "[class*='price']",
        ],
        "bedrooms": [".property-listing-features", "[class*='bed']", ".features"],
        "bathrooms": [".property-listing-features", "[class*='bath']", ".features"],
        "location": [
            "[data-qa='listing-location']",
            ".property-listing-location",
            ".location",
            "[class*='location']",
        ],
        "size": [".size", "[class*='size']"],
        "amenities": [".amenities", "[class*='amenit']"],
        "description": [".description", "[class*='description']"],
    },
    "property24": {
        "card": [
            "[data-qa='ListingCard']",
            ".listing-card",
            ".PropertyCard",
            "article",
        ],
        "title": [
            "[data-qa='ListingCardTitle']",
            ".listing-card-title",
            "h2 a",
            "h2",
            "h3",
            "a[title]",
        ],
        "price": [
            "[data-qa='ListingCardPrice']",
            ".listing-card-price",
            ".price",
            "[class*='price']",
        ],
        "bedrooms": ["[class*='bed']", "[class*='Bedroom']"],
        "bathrooms": ["[class*='bath']", "[class*='Bathroom']"],
        "location": [
            "[data-qa='ListingCardSubtitle']",
            ".listing-card-location",
            ".location",
            "[class*='location']",
        ],
        "size": [".size", "[class*='size']"],
        "amenities": [".amenities", "[class*='amenit']"],
        "description": [".description", "[class*='description']"],
    },
    "generic": {
        "card": [],
        "title": [],
        "price": [],
        "bedrooms": [],
        "bathrooms": [],
        "location": [],
        "size": [],
        "amenities": [],
        "description": [],
    },
}

PRICE_RE = re.compile(
    r"(?:ksh|kes|sh\.?|shillings)\s*\d(?:[\d,\.\s]*\d)?(?:\s*[km])?",
    re.IGNORECASE,
)
AREA_RE = re.compile(r"(?<![\d.])\d{1,4}\s*(?:sq\.?\s*m|m2|metres|meters)\b", re.IGNORECASE)
BED_RE = re.compile(r"(\d+)\s*(?:bed\s*rooms?|bedrooms?|beds?\b|\bbr\b)", re.IGNORECASE)
BATH_RE = re.compile(r"(\d+)\s*(?:bath\s*rooms?|bathrooms?|baths?\b|\bwc\b)", re.IGNORECASE)


def _first_text(node, selectors):
    """Return the text of the first selector that matches anything."""
    if node is None:
        return None
    for selector in selectors:
        try:
            found = node.select_one(selector)
        except (NotImplementedError, ValueError):
            continue
        if found is not None:
            text = found.get_text(" ", strip=True)
            if text:
                return text
    return None


def _clean_text(text):
    if not text:
        return None
    return re.sub(r"\s+", " ", str(text)).strip() or None


def _card_candidates(soup, selectors):
    """The listing cards on the page."""
    for selector in selectors:
        try:
            found = soup.select(selector)
        except (NotImplementedError, ValueError):
            continue
        if found:
            return found
    return []


def _external_id_from_url(url):
    """Pull a stable identifier out of a listing URL."""
    if not url:
        return None
    cleaned = re.sub(r"[?#].*$", "", url).rstrip("/")
    if not cleaned:
        return None
    tail = cleaned.rsplit("/", 1)[-1]
    return tail[:100] or None


def _absolute_url(url, base_url):
    if not url:
        return None
    if url.lower().startswith(("javascript:", "data:", "#")):
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not base_url:
        return url
    return f"{base_url.rstrip('/')}/{url.lstrip('/')}"


def parse_profile(soup, profile, known_areas=None, base_url=None):
    """Parse a page using one of the named site profiles."""
    settings = PROFILES.get(profile) or PROFILES["generic"]
    cards = _card_candidates(soup, settings["card"])
    results = []

    for card in cards:
        record = _record_from_card(card, settings, known_areas, base_url)
        if record:
            results.append(record)

    return results


def _record_from_card(card, settings, known_areas, base_url):
    title = _clean_text(_first_text(card, settings["title"]))
    price_text = _clean_text(_first_text(card, settings["price"]))

    if not price_text:
        # the profile did not find the price, search the card text for one
        price_text = _find_price_in_text(card.get_text(" ", strip=True))

    location_text = _clean_text(_first_text(card, settings["location"]))

    bedrooms_text = _clean_text(_first_text(card, settings["bedrooms"]))
    bathrooms_text = _clean_text(_first_text(card, settings["bathrooms"]))

    card_text = card.get_text(" ", strip=True)

    if bedrooms_text is None:
        match = BED_RE.search(card_text)
        bedrooms_text = match.group(0) if match else None
    if bathrooms_text is None:
        match = BATH_RE.search(card_text)
        bathrooms_text = match.group(0) if match else None

    if not location_text:
        location_text = _find_area_in_text(card_text, known_areas)

    link = card.find("a", href=True)
    url = _absolute_url(link["href"], base_url) if link else None

    if not title and link:
        title = _clean_text(link.get_text(" ", strip=True))
    if not title:
        heading = card.find(["h1", "h2", "h3", "h4"])
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else None

    if not title or not price_text:
        return None

    size_text = None
    size_match = AREA_RE.search(card_text)
    if size_match:
        size_text = size_match.group(0)

    size_from_profile = _clean_text(_first_text(card, settings.get("size") or []))
    if size_from_profile:
        size_text = size_from_profile

    description = _clean_text(_first_text(card, settings.get("description") or []))
    if not description:
        description = _clean_text(card_text)[:2000]

    amenities_text = _clean_text(_first_text(card, settings.get("amenities") or []))

    return {
        "title": title,
        "price_text": price_text,
        "bedrooms_text": bedrooms_text,
        "bathrooms_text": bathrooms_text,
        "location_text": location_text,
        "description": description,
        "amenities_text": amenities_text,
        "size_text": size_text,
        "url": url,
        "external_id": _external_id_from_url(url),
    }


def _find_price_in_text(text):
    """First price in a block of text."""
    if not text:
        return None
    match = PRICE_RE.search(text)
    return match.group(0).strip() if match else None


def _find_area_in_text(text, known_areas):
    """Look for a known neighbourhood name inside a block of text."""
    if not text or not known_areas:
        return None
    lowered = text.lower()
    best = None
    for area in known_areas:
        name = area["name"] if isinstance(area, dict) else str(area)
        if name and name.lower() in lowered:
            if best is None or len(name) > len(best):
                best = name
    return best


def _price_nodes(soup):
    """The innermost elements that look like they hold a price."""
    found = []
    for element in soup.find_all(string=PRICE_RE):
        parent = element.parent
        if not isinstance(parent, Tag):
            continue
        # keep the innermost match so we do not report a whole card as a price
        if parent.find(string=PRICE_RE) is not None and parent.find(string=PRICE_RE) is not element:
            continue
        found.append(parent)
    return found


def _card_for(element, soup):
    """Walk up from a price element until we reach something that looks like a card."""
    node = element
    for _ in range(10):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            return element.parent
        links = node.find_all("a", href=True)
        if links:
            prices = PRICE_RE.findall(node.get_text(" ", strip=True))
            if len(prices) <= 3:
                return node
    return element.parent


def parse_heuristic(soup, known_areas=None, base_url=None):
    """Find the listings on a page without relying on the site's own markup.

    Accepts either a BeautifulSoup object or the raw HTML.
    """
    if isinstance(soup, str):
        soup = BeautifulSoup(soup, "html.parser")

    records = []
    seen_cards = set()

    for price_node in _price_nodes(soup):
        card = _card_for(price_node, soup)
        if id(card) in seen_cards:
            continue
        seen_cards.add(id(card))

        price_text = _find_price_in_text(price_node.get_text(" ", strip=True))
        card_text = card.get_text(" ", strip=True)

        heading = card.find(["h1", "h2", "h3", "h4"])
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else None

        link = card.find("a", href=True)
        url = _absolute_url(link["href"], base_url) if link else None
        if not title and link:
            title = _clean_text(link.get_text(" ", strip=True))
        if not title:
            title = _clean_text(card_text)[:150]

        bed_match = BED_RE.search(card_text)
        bath_match = BATH_RE.search(card_text)
        size_match = AREA_RE.search(card_text)

        records.append(
            {
                "title": title,
                "price_text": price_text,
                "bedrooms_text": bed_match.group(0) if bed_match else None,
                "bathrooms_text": bath_match.group(0) if bath_match else None,
                "location_text": _find_area_in_text(card_text, known_areas),
                "description": _clean_text(card_text)[:2000] or None,
                "size_text": size_match.group(0) if size_match else None,
                "url": url,
                "external_id": _external_id_from_url(url),
            }
        )

    return records


def parse_page(html, profile="generic", known_areas=None, base_url=None):
    """Parse one page of listings.

    Returns a list of raw records. The cleaner turns those into rows for the
    properties table.
    """
    soup = BeautifulSoup(html, "html.parser")

    records = []
    if profile and profile != "generic":
        records = parse_profile(soup, profile, known_areas, base_url)

    if not records:
        # either the site has no profile or the profile no longer matches the
        # page, so fall back to reading the page by eye
        records = parse_heuristic(soup, known_areas, base_url)

    return [r for r in records if r.get("title") and r.get("price_text")]


def parse_listings(html):
    """Parse the bundled sample page (kept for backwards compatibility)."""
    from scraper.cleaner import clean_listing

    raw = parse_page(html, profile="fixture")
    cleaned = []
    for item in raw:
        result = clean_listing(item)
        if result:
            cleaned.append(
                {
                    "title": result["title"],
                    "rentamount": result["rentamount"],
                    "bedrooms": result["bedrooms"],
                    "bathrooms": result["bathrooms"],
                    "category": result["category"],
                    "city": result["city"],
                    "address": result["address"],
                }
            )
    return cleaned
