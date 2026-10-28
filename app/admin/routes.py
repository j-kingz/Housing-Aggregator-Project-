from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from app.extensions import db
from app.models import LandlordDetails, Property, Role, ScrapingRun, ScrapingSource, User
from scraper import parser as scrape_parser

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


# -- scraping sources ------------------------------------------------
# The administrator manages the sites the scraper reads and the rules it
# follows, which is the "Manage Scraping Sources" and "Configure Scraping
# Rules" use case in the use case diagram.


@admin_bp.route("/sources")
@admin_required
def sources():
    """The list of sites the scraper is allowed to read."""
    all_sources = ScrapingSource.query.order_by(ScrapingSource.source_id).all()

    for source in all_sources:
        source.listing_count = Property.query.filter_by(source_id=source.source_id).count()
        source.run_count = ScrapingRun.query.filter_by(source_id=source.source_id).count()

    return render_template(
        "admin/sources.html",
        sources=all_sources,
        profiles=sorted(scrape_parser.PROFILES.keys()),
    )


@admin_bp.route("/sources/add", methods=["POST"])
@admin_required
def add_source():
    """Register a new site for the scraper."""
    name = request.form.get("name", "").strip()
    base_url = request.form.get("base_url", "").strip()
    listing_url = request.form.get("listing_url", "").strip()
    profile = request.form.get("profile", "generic").strip() or "generic"

    if not name:
        flash("Give the source a name.", "danger")
        return redirect(url_for("admin.sources"))
    if ScrapingSource.query.filter_by(name=name).first():
        flash("A source with that name already exists.", "danger")
        return redirect(url_for("admin.sources"))

    source = ScrapingSource(
        name=name,
        base_url=base_url or None,
        listing_url=listing_url or None,
        profile=profile,
        enabled=bool(request.form.get("enabled")),
        delay_seconds=_number(request.form.get("delay_seconds"), 5.0),
        max_pages=_number(request.form.get("max_pages"), 3),
        respects_robots=bool(request.form.get("respects_robots")),
        notes=request.form.get("notes", "").strip()[:255] or None,
    )
    db.session.add(source)
    db.session.commit()
    flash(f"{name} added to the scraping sources.", "success")
    return redirect(url_for("admin.sources"))


@admin_bp.route("/sources/<int:source_id>/update", methods=["POST"])
@admin_required
def update_source(source_id):
    """Change the settings of a scraping source."""
    source = db.get_or_404(ScrapingSource, source_id)

    source.base_url = request.form.get("base_url", "").strip() or None
    source.listing_url = request.form.get("listing_url", "").strip() or None
    source.profile = request.form.get("profile", source.profile).strip() or "generic"
    source.delay_seconds = _number(request.form.get("delay_seconds"), source.delay_seconds or 5.0)
    source.max_pages = _number(request.form.get("max_pages"), source.max_pages or 3)
    source.respects_robots = bool(request.form.get("respects_robots"))
    source.notes = request.form.get("notes", "").strip()[:255] or None

    db.session.commit()
    flash(f"{source.name} updated.", "success")
    return redirect(url_for("admin.sources"))


@admin_bp.route("/sources/<int:source_id>/toggle", methods=["POST"])
@admin_required
def toggle_source(source_id):
    """Turn a scraping source on or off."""
    source = db.get_or_404(ScrapingSource, source_id)
    source.enabled = not bool(source.enabled)
    db.session.commit()
    flash(f"{source.name} is now {'enabled' if source.enabled else 'disabled'}.", "success")
    return redirect(url_for("admin.sources"))


@admin_bp.route("/sources/<int:source_id>/delete", methods=["POST"])
@admin_required
def delete_source(source_id):
    """Remove a scraping source. The listings it produced are kept."""
    source = db.get_or_404(ScrapingSource, source_id)

    # the listings keep their source_name, we just drop the link
    Property.query.filter_by(source_id=source.source_id).update({"source_id": None})
    ScrapingRun.query.filter_by(source_id=source.source_id).update({"source_id": None})
    db.session.delete(source)
    db.session.commit()
    flash(f"{source.name} removed.", "info")
    return redirect(url_for("admin.sources"))


# -- scraper runs ----------------------------------------------------


@admin_bp.route("/runs")
@admin_required
def runs():
    """The log of scraping runs."""
    all_runs = (
        ScrapingRun.query.order_by(ScrapingRun.run_id.desc()).limit(100).all()
    )
    totals = {
        "runs": ScrapingRun.query.count(),
        "listings": Property.query.count(),
        "active": Property.query.filter(Property.is_active.is_(True)).count(),
        "saved": db.session.query(func.sum(ScrapingRun.listings_saved)).scalar() or 0,
    }
    return render_template("admin/runs.html", runs=all_runs, totals=totals)


@admin_bp.route("/runs/<int:run_id>/delete", methods=["POST"])
@admin_required
def delete_run(run_id):
    """Clear one entry from the run log."""
    run = db.get_or_404(ScrapingRun, run_id)
    db.session.delete(run)
    db.session.commit()
    flash("Run log entry removed.", "info")
    return redirect(url_for("admin.runs"))


@admin_bp.route("/snapshot", methods=["POST"])
@admin_required
def record_snapshot():
    """Write today's market figures to the analytics log."""
    from app.analytics.services import record_snapshot

    snapshot = record_snapshot()
    if snapshot is None:
        flash("There are no active listings to record.", "warning")
    else:
        db.session.add(snapshot)
        db.session.commit()
        flash(
            f"Market snapshot recorded: {snapshot.listing_count} listings, "
            f"average rent KSh {float(snapshot.average_rent):,.0f}.",
            "success",
        )
    return redirect(url_for("admin.runs"))


def _number(value, fallback):
    """Read a number from a form, falling back when it is missing or wrong."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number
