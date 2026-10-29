"""Saved homes: the heart button."""

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Favorite, Property

favorites_bp = Blueprint("favorites", __name__, url_prefix="/favorites")


@favorites_bp.route("/")
@login_required
def index():
    """Every home the signed-in person has saved, newest first."""
    rows = (
        Favorite.query.filter_by(user_id=current_user.user_id)
        .join(Property, Favorite.listing_id == Property.listing_id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    return render_template("favorites/index.html", listings=[r.listing for r in rows])


@favorites_bp.route("/<int:listing_id>/toggle", methods=["POST"])
@login_required
def toggle(listing_id):
    """Save the home, or remove it if it was already saved."""
    db.get_or_404(Property, listing_id)
    existing = Favorite.query.filter_by(user_id=current_user.user_id, listing_id=listing_id).first()
    if existing:
        db.session.delete(existing)
        saved = False
    else:
        db.session.add(Favorite(user_id=current_user.user_id, listing_id=listing_id))
        saved = True
    db.session.commit()

    if request.headers.get("Accept", "").startswith("application/json"):
        count = Favorite.query.filter_by(user_id=current_user.user_id).count()
        return jsonify({"saved": saved, "count": count})
    return redirect(request.referrer or url_for("favorites.index"))
