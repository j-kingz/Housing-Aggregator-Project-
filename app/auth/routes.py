from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required
from app.extensions import db
from app.models import User, Role, RenterDetails

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        firstname = request.form.get("firstname", "").strip()
        lastname = request.form.get("lastname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not firstname or not lastname or not email or not password:
            flash("Please fill in every field.", "danger")
            return redirect(url_for("auth.register"))

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return redirect(url_for("auth.register"))

        # Every new sign-up is registered as a "Renter" by default
        renter_role = Role.query.filter_by(name="Renter").first()
        if renter_role is None:
            renter_role = Role(name="Renter", description="Searches for housing")
            db.session.add(renter_role)
            db.session.flush()

        user = User(
            firstname=firstname,
            lastname=lastname,
            email=email,
            phonenumber=request.form.get("phonenumber", ""),
            role_id=renter_role.role_id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()  # gets user.user_id before commit

        renter_profile = RenterDetails(renter_id=user.user_id)
        db.session.add(renter_profile)
        db.session.commit()

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Incorrect email or password.", "danger")
            return redirect(url_for("auth.login"))

        login_user(user)
        flash(f"Welcome back, {user.firstname}!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.home"))
