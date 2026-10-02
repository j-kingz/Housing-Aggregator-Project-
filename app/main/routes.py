from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import Property

main_bp = Blueprint("main", __name__)


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@main_bp.route("/")
def home():
    location = request.args.get("location", "").strip()
    max_price = to_int(request.args.get("max_price"))
    bedrooms = to_int(request.args.get("bedrooms"))

    query = Property.query
    if location:
        like = f"%{location}%"
        query = query.filter(or_(Property.city.ilike(like), Property.address.ilike(like)))
    if max_price:
        query = query.filter(Property.rentamount <= max_price)
    if bedrooms:
        query = query.filter(Property.bedrooms >= bedrooms)

    listings = query.order_by(Property.listingdate.desc(), Property.listing_id.desc()).limit(50).all()

    return render_template(
        "home.html",
        listings=listings,
        location=location,
        max_price=max_price or "",
        bedrooms=bedrooms or "",
    )


@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user

    if request.method == "POST":
        firstname = request.form.get("firstname", "").strip()
        lastname = request.form.get("lastname", "").strip()
        if not firstname or not lastname:
            flash("First and last name can't be empty.", "danger")
            return redirect(url_for("main.profile"))

        user.firstname = firstname
        user.lastname = lastname
        user.phonenumber = request.form.get("phonenumber", "").strip() or None

        if user.renter:
            user.renter.preferredlocation = request.form.get("preferredlocation", "").strip() or None
            user.renter.budgetrange = request.form.get("budgetrange", "").strip() or None
        if user.landlord:
            user.landlord.businessname = request.form.get("businessname", "").strip() or None

        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    return render_template("profile.html", user=user)
