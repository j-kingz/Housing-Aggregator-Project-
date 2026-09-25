from datetime import date, datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


def utcnow():
    """Naive UTC timestamp; replaces the deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Role(db.Model):
    __tablename__ = "role"

    role_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    status = db.Column(db.String(20), default="active")

    users = db.relationship("User", back_populates="role")


class User(db.Model, UserMixin):
    __tablename__ = "user"

    user_id = db.Column(db.Integer, primary_key=True)
    firstname = db.Column(db.String(50), nullable=False)
    lastname = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    phonenumber = db.Column(db.String(20))
    role_id = db.Column(db.Integer, db.ForeignKey("role.role_id"))
    status = db.Column(db.String(20), default="active")

    role = db.relationship("Role", back_populates="users")
    renter_profile = db.relationship("RenterDetails", back_populates="user", uselist=False)
    landlord_profile = db.relationship("LandlordDetails", back_populates="user", uselist=False)

    def set_password(self, raw_password):
        self.password = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password, raw_password)

    # Flask-Login expects an id property
    def get_id(self):
        return str(self.user_id)


class RenterDetails(db.Model):
    __tablename__ = "renter_details"

    renter_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), primary_key=True)
    preferredlocation = db.Column(db.String(100))
    budgetrange = db.Column(db.String(50))

    user = db.relationship("User", back_populates="renter_profile")
    search_alerts = db.relationship("SearchAlert", back_populates="renter")
    notifications = db.relationship("Notification", back_populates="renter")
    payments = db.relationship("Payment", back_populates="renter")


class LandlordDetails(db.Model):
    __tablename__ = "landlord_details"

    landlord_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), primary_key=True)
    businessname = db.Column(db.String(100))
    verificationstatus = db.Column(db.String(20), default="pending")

    user = db.relationship("User", back_populates="landlord_profile")
    properties = db.relationship("Property", back_populates="landlord")


class Property(db.Model):
    __tablename__ = "properties"

    listing_id = db.Column(db.Integer, primary_key=True)
    landlord_id = db.Column(db.Integer, db.ForeignKey("landlord_details.landlord_id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    rentamount = db.Column(db.Numeric(10, 2), nullable=False)
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    listingdate = db.Column(db.Date, default=date.today)
    category = db.Column(db.String(50))
    buildingnumber = db.Column(db.String(20))
    city = db.Column(db.String(50))
    address = db.Column(db.String(150))

    landlord = db.relationship("LandlordDetails", back_populates="properties")
    payments = db.relationship("Payment", back_populates="property")


class SearchAlert(db.Model):
    __tablename__ = "search_alert"

    searchalert_id = db.Column(db.Integer, primary_key=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("renter_details.renter_id"), nullable=False)
    datecreated = db.Column(db.Date, default=date.today)
    criteria = db.Column(db.String(255))
    frequency = db.Column(db.String(20))

    renter = db.relationship("RenterDetails", back_populates="search_alerts")
    notifications = db.relationship("Notification", back_populates="search_alert")


class Notification(db.Model):
    __tablename__ = "notification"

    notification_id = db.Column(db.Integer, primary_key=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("renter_details.renter_id"), nullable=False)
    search_id = db.Column(db.Integer, db.ForeignKey("search_alert.searchalert_id"), nullable=True)
    date = db.Column(db.DateTime, default=utcnow)
    message = db.Column(db.String(255))
    type = db.Column(db.String(50))

    renter = db.relationship("RenterDetails", back_populates="notifications")
    search_alert = db.relationship("SearchAlert", back_populates="notifications")


class Payment(db.Model):
    __tablename__ = "payment"

    payment_id = db.Column(db.Integer, primary_key=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("renter_details.renter_id"), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("properties.listing_id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    date = db.Column(db.DateTime, default=utcnow)
    modeofpayment = db.Column(db.String(50))
    status = db.Column(db.String(20), default="pending")

    renter = db.relationship("RenterDetails", back_populates="payments")
    property = db.relationship("Property", back_populates="payments")
