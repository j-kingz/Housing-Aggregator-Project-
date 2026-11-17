"""Location look-ups behind the type-ahead boxes.

A person typing into "Where" gets, in this order:

1. counties of Kenya ("Nairobi County"), and when a county is typed, the
   neighbourhoods inside it;
2. neighbourhoods the platform knows;
3. buildings that have listings;
4. any other place in Kenya (towns, malls, universities, estates), from
   OpenStreetMap through Photon, so it behaves like a map search.

Everything except step 4 comes from the platform's own data, so a typing
mistake still finds the right place even without internet.
"""

import difflib
import threading
import time

import requests
from sqlalchemy import func

from app.counties import COUNTIES, find_county
from app.models import Area, Property

MAX_RESULTS = 8

PHOTON_URL = "https://photon.komoot.io/api/"
# the box around Kenya, so results from other countries never appear
KENYA_BBOX = "33.5,-4.9,42.0,5.5"
PHOTON_TIMEOUT = 4
# kinds of place worth offering. Roads, rivers, car parks and bus stops are not.
PLACE_KINDS = {
    "city", "town", "village", "suburb", "neighbourhood", "hamlet", "locality", "quarter",
    "administrative", "county", "state", "university", "college", "school", "mall",
    "supermarket", "hospital", "clinic", "apartments", "building", "hotel", "office",
    "commercial", "retail", "house", "yes", "marketplace", "bank", "residential_building",
}

_cache = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = 600


def _norm(text):
    return " ".join(str(text or "").lower().split())


def _county_key(text):
    """Lower case, hyphens as spaces: "Taita-Taveta" and "taita taveta" match."""
    return " " + _norm(str(text or "").replace("-", " ").replace(",", " ")) + " "


_COUNTY_KEYS = [(_county_key(name), name) for name, _, _ in COUNTIES]


def county_in_text(*texts):
    """The county named in any of the texts ("Westlands, Nairobi County" -> "Nairobi").

    Whole words only, so a county name hidden inside another word never matches.
    Addresses run from the street to the county, so the county named furthest
    right wins ("Kiambu Rd, Nairobi" is in Nairobi); on a tie the longer name.
    Returns None when no county is named.
    """
    for text in texts:
        if not text:
            continue
        exact = find_county(text)
        if exact:
            return exact[0]
        key = _county_key(text)
        hits = [(key.rfind(county_key), len(name), name)
                for county_key, name in _COUNTY_KEYS if county_key in key]
        if hits:
            return max(hits)[2]
    return None


def county_for_place(text):
    """The county of a place typed into the search box, when it can be known for sure.

    A county name, a neighbourhood the platform knows or a building with
    listings. Anything else returns None (no guessing from distance, which
    would put places near a county border in the wrong county).
    """
    exact = find_county(text)
    if exact:
        return exact[0]
    q = _norm(text)
    if not q:
        return None
    area = Area.query.filter(func.lower(Area.name) == q).first()
    if area is not None:
        return county_in_text(area.county, area.city)
    row = (
        Property.query.outerjoin(Area, Property.area_id == Area.area_id)
        .with_entities(func.min(Area.county), func.min(Property.city))
        .filter(Property.is_active.is_(True), func.lower(Property.building_name) == q)
        .first()
    )
    if row is not None:
        return county_in_text(row[0], row[1])
    return None


def _area_item(area, label_county=True):
    county = area.county or area.city
    return {
        "label": area.name,
        "detail": f"{county} County" if label_county else area.city,
        "type": "area",
        "value": area.name,
        # only a real county name; a town such as "Thika" is not a county
        "county": county_in_text(area.county, area.city),
        "area_id": area.area_id,
        "lat": float(area.latitude) if area.latitude is not None else None,
        "lng": float(area.longitude) if area.longitude is not None else None,
    }


def _county_item(name, lat, lng):
    return {
        "label": f"{name} County",
        "detail": "County",
        "type": "county",
        "value": name,
        "county": name,
        "lat": lat,
        "lng": lng,
    }


def _fuzzy(query, names, cutoff=0.6):
    """Names that look like the query even when it has typing mistakes."""
    return difflib.get_close_matches(query, names, n=MAX_RESULTS, cutoff=cutoff)


def suggest_counties(query, limit=4):
    """Counties that start with, contain or nearly match what was typed."""
    q = _norm(query)
    if q.endswith(" county"):
        q = q[: -len(" county")]
    if not q:
        return []
    names = {name.lower(): (name, lat, lng) for name, lat, lng in COUNTIES}
    ordered = [v for k, v in names.items() if k.startswith(q)]
    ordered += [v for k, v in names.items() if q in k and v not in ordered]
    if not ordered:
        ordered = [names[k] for k in _fuzzy(q, list(names), cutoff=0.75)]
    return [_county_item(*c) for c in ordered[:limit]]


def areas_in_county(county, limit=MAX_RESULTS):
    """Neighbourhoods inside a county, biggest first (most listings)."""
    rows = (
        Area.query.outerjoin(Property, Property.area_id == Area.area_id)
        .filter(func.lower(Area.county) == county.lower())
        .group_by(Area.area_id)
        .order_by(func.count(Property.listing_id).desc(), Area.name)
        .limit(limit)
        .all()
    )
    return [_area_item(a) for a in rows]


def suggest_areas(query, limit=MAX_RESULTS, county=None):
    """Neighbourhoods for what has been typed so far (optionally inside one county).

    Names that start with the text come first, then names that contain it,
    then near misses ("westlnds" finds Westlands).
    """
    q = _norm(query)
    areas = Area.query.order_by(Area.name).all()
    if county:
        areas = [a for a in areas if _norm(a.county) == _norm(county)]
    if not q:
        return [_area_item(a) for a in areas[:limit]]

    by_name = {_norm(a.name): a for a in areas}
    ordered = [a for n, a in by_name.items() if n.startswith(q)]
    ordered += [a for n, a in by_name.items() if q in n and a not in ordered]
    if len(ordered) < limit:
        for name in _fuzzy(q, list(by_name)):
            if by_name[name] not in ordered:
                ordered.append(by_name[name])
    return [_area_item(a) for a in ordered[:limit]]


def _buildings(q, limit):
    like = f"%{q}%"
    rows = (
        Property.query.outerjoin(Area, Property.area_id == Area.area_id)
        .with_entities(
            Property.building_name,
            func.min(Property.address),
            func.min(Property.latitude),
            func.min(Property.longitude),
            func.count(Property.listing_id),
            func.min(Area.county),
            func.min(Property.city),
        )
        .filter(Property.is_active.is_(True), Property.building_name.isnot(None))
        .filter(Property.building_name.ilike(like))
        .group_by(Property.building_name)
        .limit(limit)
        .all()
    )
    items = []
    for name, address, lat, lng, count, area_county, city in rows:
        items.append(
            {
                "label": name,
                "detail": f"Building · {address or 'Kenya'} · {count} unit{'s' if count != 1 else ''}",
                "type": "building",
                "value": name,
                "county": county_in_text(area_county, city),
                "lat": float(lat) if lat is not None else None,
                "lng": float(lng) if lng is not None else None,
            }
        )
    return items


def external_places(query, limit=5):
    """Places anywhere in Kenya from OpenStreetMap (Photon). Never raises.

    Answers are cached for ten minutes so repeated typing does not hammer the
    free service. If it cannot be reached the list is simply empty.
    """
    q = _norm(query)
    if len(q) < 3:
        return []
    now = time.time()
    with _cache_lock:
        hit = _cache.get(q)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]

    items = []
    try:
        response = requests.get(
            PHOTON_URL,
            params={"q": query, "limit": 10, "lang": "en", "bbox": KENYA_BBOX},
            headers={"User-Agent": "HousingAggregator-academic/1.0"},
            timeout=PHOTON_TIMEOUT,
        )
        response.raise_for_status()
        seen = set()
        for feature in response.json().get("features", []):
            props = feature.get("properties", {})
            name = props.get("name")
            if not name or props.get("osm_value") not in PLACE_KINDS:
                continue
            lng, lat = feature["geometry"]["coordinates"]
            where = ", ".join(
                dict.fromkeys(
                    x for x in (props.get("district"), props.get("city") or props.get("locality"),
                                props.get("state") or props.get("county")) if x
                )
            )
            key = (name.lower(), where)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "label": name,
                    "detail": where or "Kenya",
                    "type": "place",
                    "value": name,
                    "county": county_in_text(
                        props.get("county"), props.get("state"),
                        props.get("city"), props.get("locality"),
                    ),
                    "lat": round(lat, 6),
                    "lng": round(lng, 6),
                }
            )
            if len(items) >= limit:
                break
    except (requests.RequestException, ValueError, KeyError):
        return []

    with _cache_lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[q] = (now, items)
    return items


def suggest_places(query, limit=MAX_RESULTS, county=None, external=True):
    """Counties, neighbourhoods, buildings and then places anywhere in Kenya."""
    q = _norm(query)
    if not q:
        return [_county_item(n, la, lo) for n, la, lo in COUNTIES[-1:]] + suggest_areas("", limit)

    items = suggest_counties(query)

    # a county was typed in full: show the neighbourhoods inside it
    exact = find_county(query)
    if exact:
        items += areas_in_county(exact[0], limit)
    else:
        items += suggest_areas(query, limit, county=county)

    items += _buildings(q, 4)

    if external and len(items) < limit + 4:
        items += external_places(query)

    # the same place can come from two sources; keep the first
    unique, seen = [], set()
    for item in items:
        key = (item["type"], item["label"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[: limit + 6]


def resolve_area(text):
    """Turn typed text into a real Area.

    Returns (area, corrected). `corrected` is True when the text was not an
    exact name and the nearest known neighbourhood was used instead.
    """
    q = _norm(text)
    if not q:
        return None, False
    areas = Area.query.all()
    by_name = {_norm(a.name): a for a in areas}
    if q in by_name:
        return by_name[q], False
    starts = [a for n, a in by_name.items() if n.startswith(q)]
    if len(starts) == 1:
        return starts[0], True
    near = _fuzzy(q, list(by_name), cutoff=0.7)
    if near:
        return by_name[near[0]], True
    return None, False
