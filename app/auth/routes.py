import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import LandlordDetails, RenterDetails, Role, User

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "GET":
        return render_template("auth/register.html", form={})

    form = request.form
    firstname = form.get("firstname", "").strip()
    lastname = form.get("lastname", "").strip()
    email = form.get("email", "").strip().lower()
    phone = form.get("phonenumber", "").strip()
    account_type = form.get("account_type", "Renter")
    password = form.get("password", "")
    confirm = form.get("confirm_password", "")

    errors = []
    if not (firstname and lastname and email and password):
        errors.append("First name, last name, email and password are required.")
    if email and not EMAIL_RE.match(email):
        errors.append("That email address doesn't look right.")
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password needs to be at least {MIN_PASSWORD_LENGTH} characters.")
    if password != confirm:
        errors.append("The two passwords don't match.")
    if account_type not in ("Renter", "Landlord"):
        errors.append("Pick either Renter or Landlord.")
    if email and User.query.filter_by(email=email).first():
        errors.append("There's already an account with that email.")

    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("auth/register.html", form=form), 400

    role = Role.query.filter_by(name=account_type).first()
    if role is None:
        flash("Roles haven't been set up yet. Run init_db.py first.", "danger")
        return render_template("auth/register.html", form=form), 500

    user = User(
        firstname=firstname,
        lastname=lastname,
        email=email,
        phonenumber=phone or None,
        role=role,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()  # need user_id for the details row

    if account_type == "Landlord":
        business = form.get("businessname", "").strip()
        db.session.add(LandlordDetails(landlord_id=user.user_id, businessname=business or None))
    else:
        db.session.add(RenterDetails(renter_id=user.user_id))

    db.session.commit()

    flash("Account created, you can log in now.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        # same message either way so nobody can tell which emails are registered
        if user is None or not user.check_password(password):
            flash("Wrong email or password.", "danger")
            return render_template("auth/login.html", email=email), 401

        if user.status != "active":
            flash("This account has been deactivated.", "danger")
            return render_template("auth/login.html", email=email), 403

        login_user(user)
        flash(f"Welcome back, {user.firstname}.", "success")

        next_page = request.args.get("next", "")
        # only follow relative links, otherwise ?next= could send people to another site
        if not next_page.startswith("/") or next_page.startswith("//") or "\\" in next_page:
            next_page = url_for("main.home")
        return redirect(next_page)

    return render_template("auth/login.html", email="")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.home"))
