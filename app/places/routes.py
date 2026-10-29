"""JSON endpoints used by the location type-ahead boxes."""

from flask import Blueprint, jsonify, request

from app.places import services

places_bp = Blueprint("places", __name__, url_prefix="/api")


@places_bp.route("/suggest")
def suggest():
    """Suggestions for what a person has typed so far.

    kind=area  -> neighbourhoods only
    kind=place -> neighbourhoods and buildings
    """
    kind = request.args.get("kind", "place")
    query = request.args.get("q", "").strip()[:80]
    if kind == "area":
        items = services.suggest_areas(query)
    else:
        items = services.suggest_places(query)
    return jsonify({"query": query, "items": items})
