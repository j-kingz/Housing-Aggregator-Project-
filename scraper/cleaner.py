"""Turns messy scraped text into clean, comparable numbers.

This is the "2.0 Clean & Store" process in the Level 2 DFD:

* 2.1 Remove duplicates  -> fingerprint()
* 2.2 Fill missing data  -> match_area() fills in the neighbourhood
* 2.3 Compute pricing    -> parse_rent() turns "KSh 28,000" into a number

Everything in here is a pure function so it can be unit tested without a
database or a network connection.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

# Rent strings come in many shapes: "KSh 28,000", "28.5k", "1.2M", "KES 45,500"
CURRENCY_WORDS = (
    r"ksh|kes|shillings|sh\b|s\b|₦|rs\b|rmb|usd|\$|€|£"
)
PERIOD_MULTIPLIERS = {
    "day": 30,
    "daily": 30,
    "week": 52 / 12,
    "weekly": 52 / 12,
    "month": 1,
    "monthly": 1,
    "p/m": 1,
    "pm": 1,
    "year": 1 / 12,
    "yearly": 1 / 12,
    "annual": 1 / 12,
}

# Canonical amenity name -> the words that mean it on a listing
AMENITY_KEYWORDS = {
    "Water": ("water", "borehole", "water tank", "mwc"),
    "Electricity": ("electricity", "power", "prepaid", "token"),
    "Parking": ("parking", "car park", "garage"),
    "Security": ("security", "gated", "guard", "electric fence"),
    "Furnished": ("furnished", "semi-furnished", "fully furnished"),
    "WiFi": ("wifi", "wi-fi", "internet"),
    "Borehole": ("borehole", "water tank"),
    "Backup water": ("backup water", "booster pump"),
    "Lift": ("lift", "elevator"),
    "Balcony": ("balcony", "balconies"),
    "Gym": ("gym", "fitness"),
    "Swimming pool": ("swimming pool", "pool"),
    "Master bedroom": ("master bedroom", "ensuite", "en-suite"),
    "Servant quarters": ("servant quarters", "sq", "dhobi"),
    "Fibre internet": ("fibre", "fiber"),
}

CATEGORIES = ["Apartment", "Bedsitter", "Studio", "Maisonette", "Bungalow", "Townhouse"]


def _to_decimal(text):
    """Best effort conversion of a cleaned numeric string to a Decimal."""
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not value.is_finite():
        return None
    return value


def parse_rent(text):
    """Turn a price string into a monthly rent amount.

    Handles currency words, thousands separators, the "k" and "M" shorthand
    and listings that are priced per day or per week. Returns None when the
    text holds no price at all.
    """
    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return _to_decimal(str(text))

    lowered = str(text).lower().strip()
    if not lowered:
        return None

    # which period is the price quoted in
    multiplier = Decimal(1)
    for word, factor in PERIOD_MULTIPLIERS.items():
        if re.search(rf"(?:/|per\s+)\s*{re.escape(word)}\b", lowered):
            multiplier = Decimal(str(factor))
            break

    # drop the currency words but keep the digits, separators and suffixes
    body = re.sub(CURRENCY_WORDS, " ", lowered)

    # The number may use commas or spaces as thousands separators. Do not
    # stop at the first token in values such as "KSh 500 000+".
    match = re.search(r"(\d[\d,\.\s]*\d|\d)\s*([km])\b", body, re.IGNORECASE)
    if match:
        number = match.group(1)
        suffix = match.group(2).lower()
    else:
        match = re.search(r"(\d[\d,\.\s]*\d|\d)", body)
        if not match:
            return None
        number = match.group(1)
        suffix = None

    amount = _to_decimal(re.sub(r"[,\s]", "", number))
    if amount is None:
        return None

    if suffix == "k":
        amount *= 1000
    elif suffix == "m":
        amount *= 1000000

    amount = amount * multiplier
    amount = amount.quantize(Decimal("0.01"))

    # the column is DECIMAL(10,2) so anything huge will not fit
    if amount <= 0 or amount >= 100_000_000:
        return None
    return amount


def _is_price_only_title(title):
    """Return whether a scraped title contains no listing information."""
    if not title:
        return False
    without_currency = re.sub(CURRENCY_WORDS, " ", title.lower())
    without_suffix = re.sub(r"\b(?:per|monthly|month|pm)\b", " ", without_currency)
    return bool(
        re.fullmatch(r"[\d,\.\s+km]+", without_suffix.strip(), re.IGNORECASE)
    )


def parse_count(text, keywords):
    """Pull a bedroom/bathroom count out of a phrase like "2 Bedrooms"."""
    if not text:
        return None
    if isinstance(text, int):
        return text
    match = re.search(r"(\d+)\s*(?:" + "|".join(keywords) + r")", str(text).lower())
    if not match:
        match = re.search(r"(?:" + "|".join(keywords) + r")\s*[:\-]?\s*(\d+)", str(text).lower())
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return value if 0 <= value <= 50 else None


def parse_bedrooms(text):
    return parse_count(text, (r"bed\s*rooms?", r"beds?", r"br\b", r"bedroom"))


def parse_bathrooms(text):
    return parse_count(text, (r"bath\s*rooms?", r"baths?", r"bathroom", r"wc\b"))


def parse_size_sqft(text):
    """Read a size from text and return it in square feet.

    Metric sizes are converted because Kenyan listings use both.
    """
    if not text:
        return None
    lowered = str(text).lower()
    match = re.search(r"(\d[\d,\.]*)\s*(sq\s*m|m2|sq\.?\s*m|metres|meters)", lowered)
    if match:
        value = _to_decimal(re.sub(r"[,\s]", "", match.group(1)))
        if value is None or value <= 0:
            return None
        return int((value * Decimal("10.7639")).quantize(Decimal("1")))

    match = re.search(r"(\d[\d,\.]*)\s*(sq\s*ft|sq\.?\s*feet|square\s*feet|ft2|ft²)", lowered)
    if match:
        value = _to_decimal(re.sub(r"[,\s]", "", match.group(1)))
        if value is None or value <= 0:
            return None
        return int(value)

    return None


def split_location(text, known_areas=None):
    """Split a location string into (address, city, area_name).

    "Kilimani, Nairobi"          -> ("Kilimani", "Nairobi", "Kilimani")
    "Riverside Drive, Westlands" -> ("Riverside Drive", None, "Westlands")

    known_areas is a list of area names (or dicts with a "name" key). When one
    of them appears in the text it is used as the neighbourhood, which is how
    the scraper fills in missing location data.
    """
    if not text:
        return None, None, None

    parts = [part.strip() for part in str(text).split(",") if part.strip()]
    if not parts:
        return None, None, None

    # find the longest known neighbourhood mentioned anywhere in the string
    area_name = None
    if known_areas:
        lowered = str(text).lower()
        best = None
        for area in known_areas:
            name = area["name"] if isinstance(area, dict) else str(area)
            if name and name.lower() in lowered:
                if best is None or len(name) > len(best):
                    best = name
        area_name = best

    if area_name is not None:
        lowered_parts = [part.lower() for part in parts]
        if area_name.lower() in lowered_parts:
            index = lowered_parts.index(area_name.lower())
            rest = parts[index + 1:]
            address = parts[0] if index > 0 else area_name
            city = rest[-1] if rest else None
            return address, city, area_name
        return parts[0], (parts[-1] if len(parts) > 1 else None), area_name

    # no known area, guess from the shape of the string
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        # "Kilimani, Nairobi" -> the first part is the neighbourhood
        return parts[0], parts[1], parts[0]
    # three or more: street, neighbourhood, city
    return parts[0], parts[-1], parts[-2]


def infer_category(title, bedrooms=None, extra_text=""):
    """Work out the property category from the title and other text."""
    haystack = f"{title or ''} {extra_text or ''}".lower()
    for keyword, category in (
        ("bed sitter", "Bedsitter"),
        ("bedsitter", "Bedsitter"),
        ("studio", "Studio"),
        ("maisonette", "Maisonette"),
        ("townhouse", "Townhouse"),
        ("bungalow", "Bungalow"),
        ("apartment", "Apartment"),
    ):
        if keyword in haystack:
            return category

    if bedrooms is not None:
        if bedrooms == 0:
            return "Bedsitter"
        if bedrooms >= 4:
            return "Maisonette"
    return "Apartment"


def extract_amenities(text, limit=255):
    """Find the amenities a listing mentions. Returns a comma separated string."""
    if not text:
        return None
    lowered = str(text).lower()
    found = []
    for name, keywords in AMENITY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            if name not in found:
                found.append(name)

    if not found:
        return None
    result = ", ".join(found)
    return result[:limit]


# Words that appear in almost every property advert. They are dropped before
# a listing is fingerprinted so the same flat advertised twice with slightly
# different wording still matches.
TITLE_STOPWORDS = {
    "a", "an", "and", "apartment", "apartments", "at", "available", "bed",
    "bedroom", "bedrooms", "beds", "for", "home", "house", "houses", "in",
    "listing", "near", "of", "on", "property", "rent", "rental", "the",
    "to", "with", "sale", "let",
}


def normalise_title(title):
    """The distinctive words in a title, lowercased and sorted."""
    words = re.findall(r"[a-z]+", str(title or "").lower())
    kept = [word for word in words if word not in TITLE_STOPWORDS]
    if not kept:
        # a title made only of generic words, fall back to the whole thing
        kept = words
    return " ".join(sorted(set(kept)))


def title_overlap(first, second):
    """How similar two titles are, from 0 to 1.

    Used to spot the same flat advertised on two sites with slightly
    different wording.
    """
    left = set(normalise_title(first).split())
    right = set(normalise_title(second).split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def fingerprint(listing):
    """A stable hash for a listing, used to spot duplicates.

    The same flat advertised in two different places produces the same
    fingerprint, which is how the platform removes duplicate listings that
    have been copied across sites (proposal 2.2.3).
    """
    title = normalise_title(listing.get("title"))
    rent = listing.get("rentamount")
    if rent is not None:
        try:
            rent = str(Decimal(str(rent)).quantize(Decimal("1")))
        except (InvalidOperation, ValueError):
            rent = ""
    address = re.sub(r"\s+", " ", str(listing.get("address") or "")).strip().lower()
    city = re.sub(r"\s+", " ", str(listing.get("city") or "")).strip().lower()
    bedrooms = listing.get("bedrooms")
    bedrooms = "" if bedrooms is None else str(bedrooms)
    bathrooms = listing.get("bathrooms")
    bathrooms = "" if bathrooms is None else str(bathrooms)
    size = listing.get("size_sqft")
    size = "" if size is None else str(size)

    key = "|".join([title, str(rent), address, city, bedrooms, bathrooms, size])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_duplicate(candidate, listing, price_tolerance=0.10):
    """Is this listing probably the same flat as one we already hold?

    Used for the softer check where two sites advertise the same place with
    slightly different wording or a slightly different asking rent. Those
    are reported rather than silently deleted.
    """
    if candidate.address and listing.get("address"):
        if candidate.address.strip().lower() != str(listing["address"]).strip().lower():
            return False
    if not candidate.address and not listing.get("address"):
        return False

    if candidate.bedrooms != listing.get("bedrooms"):
        return False

    if candidate.rentamount is None or listing.get("rentamount") is None:
        return False

    existing_rent = float(candidate.rentamount)
    new_rent = float(listing["rentamount"])
    if existing_rent <= 0:
        return False
    if abs(existing_rent - new_rent) / existing_rent > price_tolerance:
        return False

    return title_overlap(candidate.title, listing.get("title")) >= 0.6


def clean_listing(raw, known_areas=None, default_city=None):
    """Turn one raw scraped record into a dict that matches the Property columns.

    Returns None when the record is too broken to be useful (no title or no
    price). The caller skips those instead of failing the whole run.
    """
    if not raw:
        return None

    title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
    if not title or _is_price_only_title(title):
        return None

    rent = raw.get("rentamount")
    if rent is None:
        rent = parse_rent(raw.get("price_text") or raw.get("rentamount"))
    elif isinstance(rent, str):
        rent = parse_rent(rent)
    if rent is None:
        return None

    source_url = (raw.get("url") or raw.get("source_url") or "").strip()
    if source_url.lower().startswith(("javascript:", "data:", "#")):
        source_url = ""

    bedrooms = raw.get("bedrooms")
    if bedrooms is None:
        bedrooms = parse_bedrooms(raw.get("bedrooms_text"))
    elif isinstance(bedrooms, str):
        bedrooms = parse_bedrooms(bedrooms)

    bathrooms = raw.get("bathrooms")
    if bathrooms is None:
        bathrooms = parse_bathrooms(raw.get("bathrooms_text"))
    elif isinstance(bathrooms, str):
        bathrooms = parse_bathrooms(bathrooms)

    address, city, area_name = split_location(raw.get("location_text"), known_areas)
    if city is None:
        city = default_city
    if not address:
        address = area_name

    body = " ".join(
        str(raw.get(key) or "")
        for key in ("title", "description", "amenities_text", "extra_text")
    )
    size_sqft = raw.get("size_sqft") or parse_size_sqft(raw.get("size_text"))
    if isinstance(size_sqft, str):
        size_sqft = parse_size_sqft(size_sqft)

    amenities = raw.get("amenities")
    if not amenities:
        amenities = extract_amenities(f"{body} {raw.get('amenities_text') or ''}")

    cleaned = {
        "title": title[:150],
        "rentamount": rent,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "category": raw.get("category") or infer_category(title, bedrooms, body),
        "building_name": (raw.get("building_name") or "").strip()[:150] or None,
        "floor_number": _parse_floor(raw.get("floor_number")),
        "room_number": (raw.get("room_number") or "").strip()[:30] or None,
        "availability_status": raw.get("availability_status", "unknown") or "unknown",
        "city": (city or "").strip()[:50] or None,
        "address": (address or "").strip()[:150] or None,
        "area_name": area_name,
        "description": (raw.get("description") or "").strip()[:2000] or None,
        "amenities": amenities,
        "size_sqft": size_sqft,
        "source_url": source_url[:255] or None,
        "external_id": (raw.get("external_id") or "")[:100] or None,
    }

    if cleaned["category"] not in CATEGORIES:
        cleaned["category"] = "Apartment"

    cleaned["fingerprint"] = fingerprint(cleaned)
    return cleaned


def _parse_floor(value):
    if value is None or value == "":
        return None
    match = re.search(r"-?\d+", str(value))
    if not match:
        return None
    number = int(match.group(0))
    return number if -5 <= number <= 200 else None
