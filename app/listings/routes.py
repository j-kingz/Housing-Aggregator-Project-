from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Property

listings_bp = Blueprint("listings", __name__, url_prefix="/listings")

CATEGORIES = ["Apartment", "Bedsitter", "Studio", "Maisonette", "Bungalow", "Townhouse"]


def landlord_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_landlord:
            flash("Only landlord accounts can manage listings.", "warning")
            return redirect(url_for("main.home"))
        return view(*args, **kwargs)
    return wrapper


def get_own_listing(listing_id):
    listing = db.get_or_404(Property, listing_id)
    if listing.landlord_id != current_user.user_id:
        abort(403)
    return listing


def read_form(form):
    """Returns (data, errors) from the add/edit listing form."""
    errors = []
    data = {
        "title": form.get("title", "").strip(),
        "category": form.get("category", ""),
        "city": form.get("city", "").strip(),
        "address": form.get("address", "").strip(),
        "buildingnumber": form.get("buildingnumber", "").strip() or None,
    }

    if not data["title"]:
        errors.append("Give the listing a title.")
    if not data["city"]:
        errors.append("City is required.")
    if data["category"] not in CATEGORIES:
        errors.append("Pick a category from the list.")

    try:
        rent = Decimal(form.get("rentamount", "").strip())
        # column is DECIMAL(10,2) so anything from 100 million up won't fit
        if not rent.is_finite() or rent <= 0 or rent >= 100_000_000:
            raise InvalidOperation
        data["rentamount"] = rent
    except InvalidOperation:
        errors.append("Rent has to be a number bigger than 0.")

    for field in ("bedrooms", "bathrooms"):
        raw = form.get(field, "").strip()
        if not raw:
            data[field] = None
        elif raw.isdigit() and int(raw) <= 50:
            data[field] = int(raw)
        else:
            errors.append(f"{field.capitalize()} should be a whole number.")

    return data, errors


@listings_bp.route("/<int:listing_id>")
def detail(listing_id):
    listing = db.get_or_404(Property, listing_id)
    return render_template("listings/detail.html", listing=listing)


@listings_bp.route("/mine")
@landlord_required
def my_listings():
    listings = (
        Property.query.filter_by(landlord_id=current_user.user_id)
        .order_by(Property.listingdate.desc())
        .all()
    )
    return render_template("listings/mine.html", listings=listings)


@listings_bp.route("/new", methods=["GET", "POST"])
@landlord_required
def create():
    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("listings/form.html", listing=request.form,
                                   categories=CATEGORIES, editing=False), 400

        listing = Property(landlord_id=current_user.user_id, **data)
        db.session.add(listing)
        db.session.commit()
        flash("Listing added.", "success")
        return redirect(url_for("listings.detail", listing_id=listing.listing_id))

    return render_template("listings/form.html", listing={}, categories=CATEGORIES, editing=False)


@listings_bp.route("/<int:listing_id>/edit", methods=["GET", "POST"])
@landlord_required
def edit(listing_id):
    listing = get_own_listing(listing_id)

    if request.method == "POST":
        data, errors = read_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("listings/form.html", listing=request.form,
                                   categories=CATEGORIES, editing=True, listing_id=listing_id), 400

        for key, value in data.items():
            setattr(listing, key, value)
        db.session.commit()
        flash("Changes saved.", "success")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    return render_template("listings/form.html", listing=listing,
                           categories=CATEGORIES, editing=True, listing_id=listing_id)


@listings_bp.route("/<int:listing_id>/delete", methods=["POST"])
@landlord_required
def delete(listing_id):
    listing = get_own_listing(listing_id)

    if listing.payments:
        flash("This listing has payments attached to it so it can't be deleted.", "warning")
        return redirect(url_for("listings.detail", listing_id=listing_id))

    db.session.delete(listing)
    db.session.commit()
    flash("Listing deleted.", "info")
    return redirect(url_for("listings.my_listings"))
