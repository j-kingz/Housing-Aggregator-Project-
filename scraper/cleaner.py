"""Turns messy scraped text into clean, comparable numbers.

This is the "2.0 Clean & Store" process in the Level 2 DFD:

* 2.1 Identify a listing -> fingerprint() (nothing is merged or dropped)
* 2.2 Fill missing data  -> match_area() fills in the neighbourhood
* 2.3 Compute pricing    -> parse_rent() turns "KSh 28,000" into a number

Everything in here is a pure function so it can be unit tested without a
database or a network connection.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from app.geo import find_plus_code

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
    return parse_count(text, (r"bed\s*rooms?", r"bdrms?", r"beds?", r"br\b", r"bedroom"))


def parse_bathrooms(text):
    return parse_count(text, (r"bath\s*rooms?", r"baths?", r"bathroom", r"wc\b"))


def parse_size_sqft(text):
    """Read a size from text and return it in square feet.

    Metric sizes are converted because Kenyan listings use both.
    """
    if not text:
        return None
    lowered = str(text).lower()
    match = re.search(r"(\d[\d,\.]*)\s*(sq\s*m|m2|m²|sq\.?\s*m|metres|meters)", lowered)
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
        # "Syokimau, Machakos": the place named first beats the county after it
        first = parts[0].lower()
        for area in known_areas:
            name = area["name"] if isinstance(area, dict) else str(area)
            if name and name.lower() == first:
                area_name = name
                break

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


def fingerprint(listing):
    """A stable identity for a listing, used only to recognise a re-scrape.

    Listings are never merged or dropped because they look alike. Two units in
    the same building have different floors and room numbers, so they get
    different fingerprints and are both kept. The fingerprint is only used to
    tell that the scraper has met the very same advert again, so the existing
    row can be refreshed instead of growing the table on every run.
    """
    def part(value):
        return re.sub(r"\s+", " ", str(value if value is not None else "")).strip().lower()

    rent = listing.get("rentamount")
    if rent is not None:
        try:
            rent = str(Decimal(str(rent)).quantize(Decimal("1")))
        except (InvalidOperation, ValueError):
            rent = ""

    key = "|".join(
        part(x)
        for x in (
            listing.get("title"),
            rent,
            listing.get("address"),
            listing.get("city"),
            listing.get("building_name"),
            listing.get("floor_number"),
            listing.get("room_number"),
            listing.get("bedrooms"),
            listing.get("bathrooms"),
            listing.get("size_sqft"),
            listing.get("source_url") or listing.get("external_id"),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# Some adverts are priced in dollars but the portal still prints the number
# next to "KSh". The advert text gives it away ("Rent $2,200/month").
USD_TO_KES = 129

USD_RE = re.compile(r"(?:\$|usd|us\$)\s*([\d][\d,]*(?:\.\d+)?)", re.IGNORECASE)


def _convert_dollar_rent(rent, raw):
    """Convert a rent that the advert says is in US dollars into shillings."""
    text = " ".join(str(raw.get(k) or "") for k in ("title", "description"))
    for match in USD_RE.finditer(text):
        try:
            dollars = Decimal(match.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        if dollars == rent and rent < 20000:
            return (dollars * USD_TO_KES).quantize(Decimal("1"))
    return rent


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

    rent = _convert_dollar_rent(rent, raw)

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

    location_text = raw.get("location_text")
    address_text = raw.get("address_text")
    plus_code = find_plus_code(address_text)
    if address_text and location_text:
        # "PQRR+9WG Brookside Grove, Westlands, Nairobi": the last part is the
        # city, which the short location label ("Westlands") leaves out
        tail = [p.strip() for p in address_text.split(",") if p.strip()]
        if len(tail) >= 2 and tail[-1].lower() != str(location_text).strip().lower():
            location_text = f"{location_text}, {tail[-1]}"
    address, city, area_name = split_location(location_text, known_areas)
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
        "room_number": _clean_room(raw.get("room_number")),
        "availability_status": raw.get("availability_status", "unknown") or "unknown",
        "city": (city or "").strip()[:50] or None,
        "address": (address or "").strip()[:150] or None,
        "area_name": area_name,
        "description": (raw.get("description") or "").strip()[:2000] or None,
        "amenities": amenities,
        "size_sqft": size_sqft,
        "source_url": source_url[:255] or None,
        "image_url": _clean_image(raw.get("image_url")),
        "plus_code": plus_code,
        "latitude": raw.get("latitude"),
        "longitude": raw.get("longitude"),
        "external_id": (raw.get("external_id") or "")[:100] or None,
    }

    if cleaned["category"] not in CATEGORIES:
        cleaned["category"] = "Apartment"

    cleaned["fingerprint"] = fingerprint(cleaned)
    return cleaned


def _clean_image(value):
    """A photo address, only if it is a plain web link."""
    url = (value or "").strip()
    return url[:500] if url.lower().startswith(("http://", "https://")) else None


def _clean_room(value):
    """A unit number such as "4B", never a count like "2 Bedrooms"."""
    text = (value or "").strip()
    if not text or re.search(r"bed|bath|room[s]?|sq", text, re.IGNORECASE):
        return None
    return text[:30]


def _parse_floor(value):
    if value is None or value == "":
        return None
    match = re.search(r"-?\d+", str(value))
    if not match:
        return None
    number = int(match.group(0))
    return number if -5 <= number <= 200 else None
