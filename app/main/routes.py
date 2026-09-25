from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func
from app.models import Property

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    city = request.args.get("city", "").strip()
    max_price = request.args.get("max_price", "").strip()

    query = Property.query
    if city:
        query = query.filter(Property.city.ilike(f"%{city}%"))
    if max_price.isdigit():
        query = query.filter(Property.rentamount <= int(max_price))

    listings = query.order_by(Property.listingdate.desc()).limit(20).all()
    return render_template("home.html", listings=listings, city=city, max_price=max_price)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    # Average rent per city powers the simple price-analytics view
    averages = (
        Property.query.with_entities(Property.city, func.avg(Property.rentamount))
        .group_by(Property.city)
        .all()
    )
    return render_template("dashboard.html", user=current_user, averages=averages)
