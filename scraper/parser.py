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
        "building_name": [".building", "[class*='building']"],
        "floor_number": [".floor", "[class*='floor']"],
        "room_number": [".room", ".room-number", "[class*='unit']"],
        "availability": [".availability", "[class*='avail']"],
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
        "building_name": [".building", "[class*='building']"],
        "floor_number": [".floor", "[class*='floor']"],
        "room_number": [".room", ".room-number", "[class*='unit']"],
        "availability": [".availability", "[class*='avail']"],
    },
    "property24": {
        # markup checked against https://www.property24.co.ke/property-to-rent-in-nairobi-p95
        "card": [".js_listingTile", ".p24_regularTile", "article"],
        "title": [
            "a[title]@title",
            ".p24_propertyTitle",
            "[itemprop='name']@content",
        ],
        "price": [".p24_price", "[itemprop='price']@content"],
        "bedrooms": [".p24_featureDetails[title='Bedrooms']"],
        "bathrooms": [".p24_featureDetails[title='Bathrooms']"],
        "location": [".p24_location"],
        "address": [".p24_address"],
        "size": [".p24_size"],
        "amenities": [],
        "description": ["[itemprop='description']@content", ".p24_excerpt"],
        "building_name": [],
        "floor_number": [],
        "room_number": [],
        "availability": [".p24_availableBadge"],
        "image": ["link[itemprop='image']@href"],
    },
    "jiji": {
        # markup checked against https://jiji.co.ke/houses-apartments-for-rent (Oct 2026).
        # The card is the link itself, 20 per page.
        "card": [".b-list-advert-base", ".qa-advert-list-item"],
        "title": [".qa-advert-title"],
        "price": [".qa-advert-price"],
        "bedrooms": [],
        "bathrooms": [],
        # Jiji prints "County, Area"; the parser reverses it to "Area, County"
        "location": [".b-list-advert__region"],
        "location_reverse": True,
        "size": [],
        "amenities": [],
        "description": [".b-list-advert-base__description-text"],
        "building_name": [],
        "floor_number": [],
        "room_number": [],
        "availability": [],
        "image": ["img@src"],
    },
    "pigiame": {
        # markup checked against https://www.pigiame.co.ke/apartments-for-rent (Oct 2026)
        "card": ["article.tw-sr-card"],
        "title": [".tw-sr-card__title"],
        "price": [".tw-sr-card__price"],
        "bedrooms": [],
        "bathrooms": [],
        "location": [".tw-sr-card__location"],
        "size": [],
        "amenities": [],
        "description": [".tw-sr-card__description", ".tw-sr-card__title"],
        "building_name": [],
        "floor_number": [],
        "room_number": [],
        "availability": [],
        "image": ["img.tw-sr-card__image@src"],
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
AREA_RE = re.compile(r"(?<![\d.])\d{1,4}\s*(?:sq\.?\s*m|m2|m²|metres|meters)", re.IGNORECASE)
BED_RE = re.compile(r"(\d+)\s*(?:bed\s*rooms?|bedrooms?|bdrms?|beds?\b|\bbr\b)", re.IGNORECASE)
BATH_RE = re.compile(r"(\d+)\s*(?:bath\s*rooms?|bathrooms?|baths?\b|\bwc\b)", re.IGNORECASE)


def _first_text(node, selectors):
    """Return the text of the first selector that matches anything.

    A selector may end in "@attribute" (for example "a[title]@title") to read
    an attribute instead of the visible text.
    """
    if node is None:
        return None
    for selector in selectors:
        attribute = None
        if "@" in selector:
            selector, attribute = selector.rsplit("@", 1)
        try:
            found = node.select_one(selector)
        except (NotImplementedError, ValueError):
            continue
        if found is not None:
            if attribute:
                text = (found.get(attribute) or "").strip()
            else:
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
    address_text = _clean_text(_first_text(card, settings.get("address") or []))

    bedrooms_text = _clean_text(_first_text(card, settings["bedrooms"]))
    bathrooms_text = _clean_text(_first_text(card, settings["bathrooms"]))

    card_text = card.get_text(" ", strip=True)

    # some sites print only the number next to a bed / bath icon
    if bedrooms_text and bedrooms_text.isdigit():
        bedrooms_text = f"{bedrooms_text} bedrooms"
    if bathrooms_text and bathrooms_text.isdigit():
        bathrooms_text = f"{bathrooms_text} bathrooms"

    if bedrooms_text is None:
        match = BED_RE.search(card_text)
        bedrooms_text = match.group(0) if match else None
    if bathrooms_text is None:
        match = BATH_RE.search(card_text)
        bathrooms_text = match.group(0) if match else None

    if not location_text:
        location_text = _find_area_in_text(card_text, known_areas)

    link = card if (card.name == "a" and card.get("href")) else card.find("a", href=True)
    url = _absolute_url(link["href"], base_url) if link else None

    if settings.get("location_reverse") and location_text:
        # "Machakos, Mlolongo" -> "Mlolongo, Machakos"
        location_text = ", ".join(reversed([p.strip() for p in location_text.split(",") if p.strip()]))

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
    building_name = _clean_text(_first_text(card, settings.get("building_name") or []))
    floor_text = _clean_text(_first_text(card, settings.get("floor_number") or []))
    room_number = _clean_text(_first_text(card, settings.get("room_number") or []))
    availability = _clean_text(_first_text(card, settings.get("availability") or []))

    image_url = _absolute_url(_clean_text(_first_text(card, settings.get("image") or [])), base_url)

    return {
        "title": title,
        "price_text": price_text,
        "bedrooms_text": bedrooms_text,
        "bathrooms_text": bathrooms_text,
        "location_text": location_text,
        "address_text": address_text,
        "image_url": image_url,
        "description": description,
        "amenities_text": amenities_text,
        "building_name": building_name,
        "floor_number": floor_text,
        "room_number": room_number,
        "availability_status": _normalise_availability(availability),
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


def _normalise_availability(text):
    lowered = (text or "").lower()
    if re.search(r"\b(vacant|available|to let|for rent)\b", lowered):
        return "vacant"
    if re.search(r"\b(occupied|let out|rented)\b", lowered):
        return "occupied"
    return "unknown"


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
