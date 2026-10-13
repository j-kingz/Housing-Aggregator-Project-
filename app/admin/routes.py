from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.extensions import db
from app.models import LandlordDetails, Property, Role, User

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


@admin_bp.route("/")
@admin_required
def dashboard():
    role_counts = dict(
        db.session.query(Role.name, func.count(User.user_id))
        .outerjoin(User, User.role_id == Role.role_id)
        .group_by(Role.name)
        .all()
    )

    stats = {
        "users": User.query.count(),
        "renters": role_counts.get("Renter", 0),
        "landlords": role_counts.get("Landlord", 0),
        "inactive": User.query.filter(User.status != "active").count(),
        "listings": Property.query.count(),
        "avg_rent": db.session.query(func.avg(Property.rentamount)).scalar() or 0,
        "pending_landlords": LandlordDetails.query.filter_by(verificationstatus="pending").count(),
    }

    recent_users = User.query.order_by(User.user_id.desc()).limit(5).all()
    recent_listings = Property.query.order_by(Property.listing_id.desc()).limit(5).all()

    return render_template("admin/dashboard.html", stats=stats,
                           recent_users=recent_users, recent_listings=recent_listings)


@admin_bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")

    query = User.query.join(Role)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.firstname.ilike(like), User.lastname.ilike(like), User.email.ilike(like)))
    if role:
        query = query.filter(Role.name == role)

    all_users = query.order_by(User.user_id.desc()).all()
    roles = [r.name for r in Role.query.order_by(Role.role_id).all()]
    return render_template("admin/users.html", users=all_users, q=q, role=role, roles=roles)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.user_id == current_user.user_id:
        flash("You can't deactivate your own account.", "warning")
        return redirect(url_for("admin.users"))

    user.status = "inactive" if user.status == "active" else "active"
    db.session.commit()
    flash(f"{user.full_name} is now {user.status}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/verify", methods=["POST"])
@admin_required
def verify_landlord(user_id):
    landlord = db.get_or_404(LandlordDetails, user_id)
    landlord.verificationstatus = "pending" if landlord.verificationstatus == "verified" else "verified"
    db.session.commit()
    flash(f"{landlord.user.full_name} marked as {landlord.verificationstatus}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/listings")
@admin_required
def listings():
    q = request.args.get("q", "").strip()

    query = Property.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Property.title.ilike(like), Property.city.ilike(like), Property.address.ilike(like)))

    all_listings = query.order_by(Property.listing_id.desc()).all()
    return render_template("admin/listings.html", listings=all_listings, q=q)


@admin_bp.route("/listings/<int:listing_id>/delete", methods=["POST"])
@admin_required
def delete_listing(listing_id):
    listing = db.get_or_404(Property, listing_id)
    if listing.payments:
        flash("That listing has payments linked to it so it can't be deleted.", "warning")
        return redirect(url_for("admin.listings"))

    db.session.delete(listing)
    db.session.commit()
    flash("Listing removed.", "info")
    return redirect(url_for("admin.listings"))
