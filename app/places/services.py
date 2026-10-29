"""Location look-ups behind the type-ahead boxes.

Everything a person can type into a "Where" or "Neighbourhood" box is checked
against places the platform really holds (neighbourhoods and the buildings of
the listings), so a typing mistake never ends in an empty search.
"""

import difflib

from sqlalchemy import func

from app.models import Area, Property

MAX_RESULTS = 8


def _norm(text):
    return " ".join(str(text or "").lower().split())


def _area_item(area):
    return {
        "label": area.name,
        "detail": f"Neighbourhood · {area.city}",
        "type": "area",
        "value": area.name,
        "area_id": area.area_id,
        "lat": float(area.latitude) if area.latitude is not None else None,
        "lng": float(area.longitude) if area.longitude is not None else None,
    }


def _fuzzy(query, names, cutoff=0.6):
    """Names that look like the query even when it has typing mistakes."""
    return difflib.get_close_matches(query, names, n=MAX_RESULTS, cutoff=cutoff)


def suggest_areas(query, limit=MAX_RESULTS):
    """Neighbourhoods for what has been typed so far.

    Names that start with the text come first, then names that contain it,
    then near misses ("westlnds" finds Westlands).
    """
    q = _norm(query)
    areas = Area.query.order_by(Area.name).all()
    if not q:
        return [_area_item(a) for a in areas[:limit]]

    by_name = {_norm(a.name): a for a in areas}
    ordered = []
    for name, area in by_name.items():
        if name.startswith(q):
            ordered.append(area)
    for name, area in by_name.items():
        if q in name and area not in ordered:
            ordered.append(area)
    if len(ordered) < limit:
        for name in _fuzzy(q, list(by_name)):
            area = by_name[name]
            if area not in ordered:
                ordered.append(area)
    return [_area_item(a) for a in ordered[:limit]]


def suggest_places(query, limit=MAX_RESULTS):
    """Neighbourhoods, buildings and streets for the "Where" box."""
    q = _norm(query)
    items = suggest_areas(query, limit)
    if not q:
        return items

    like = f"%{q}%"
    buildings = (
        Property.query.with_entities(
            Property.building_name,
            func.min(Property.address),
            func.min(Property.latitude),
            func.min(Property.longitude),
            func.count(Property.listing_id),
        )
        .filter(Property.is_active.is_(True), Property.building_name.isnot(None))
        .filter(Property.building_name.ilike(like))
        .group_by(Property.building_name)
        .limit(limit)
        .all()
    )
    for name, address, lat, lng, count in buildings:
        items.append(
            {
                "label": name,
                "detail": f"Building · {address or 'Nairobi'} · {count} unit{'s' if count != 1 else ''}",
                "type": "building",
                "value": name,
                "lat": float(lat) if lat is not None else None,
                "lng": float(lng) if lng is not None else None,
            }
        )

    # near misses on building names too
    if len(items) < limit:
        names = [
            row[0]
            for row in Property.query.with_entities(Property.building_name)
            .filter(Property.building_name.isnot(None))
            .distinct()
            .all()
        ]
        lowered = {_norm(n): n for n in names}
        have = {i["label"] for i in items}
        for near in _fuzzy(q, list(lowered)):
            if lowered[near] not in have:
                items.append(
                    {
                        "label": lowered[near],
                        "detail": "Building",
                        "type": "building",
                        "value": lowered[near],
                    }
                )
    return items[:limit]


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
