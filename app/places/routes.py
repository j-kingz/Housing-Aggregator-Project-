"""JSON endpoints used by the location type-ahead boxes."""

from flask import Blueprint, jsonify, request

from app.places import services

places_bp = Blueprint("places", __name__, url_prefix="/api")


@places_bp.route("/suggest")
def suggest():
    """Suggestions for what a person has typed so far.

    kind=area   neighbourhoods only (optionally inside ?county=Nairobi)
    kind=place  counties, neighbourhoods, buildings and places across Kenya
    ext=0       skip the OpenStreetMap lookup (the page already uses Google)
    """
    kind = request.args.get("kind", "place")
    query = request.args.get("q", "").strip()[:80]
    county = request.args.get("county", "").strip()[:60] or None
    external = request.args.get("ext", "1") != "0"
    if kind == "area":
        items = services.suggest_areas(query, county=county)
    else:
        items = services.suggest_places(query, county=county, external=external)
    return jsonify({"query": query, "items": items})
