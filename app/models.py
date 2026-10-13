from datetime import date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

# Tables follow the "Database Schema" page in the drawio file.


class Role(db.Model):
    __tablename__ = "role"

    role_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255))
    status = db.Column(db.String(20), default="active")

    users = db.relationship("User", back_populates="role")

    def __repr__(self):
        return f"<Role {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "user"

    user_id = db.Column(db.Integer, primary_key=True)
    firstname = db.Column(db.String(50), nullable=False)
    lastname = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # hash only, never plain text
    phonenumber = db.Column(db.String(20))
    role_id = db.Column(db.Integer, db.ForeignKey("role.role_id"), nullable=False)
    status = db.Column(db.String(20), default="active")

    role = db.relationship("Role", back_populates="users")
    renter = db.relationship("RenterDetails", back_populates="user", uselist=False)
    landlord = db.relationship("LandlordDetails", back_populates="user", uselist=False)

    def get_id(self):
        return str(self.user_id)

    def set_password(self, plain):
        self.password = generate_password_hash(plain)

    def check_password(self, plain):
        return check_password_hash(self.password, plain)

    @property
    def is_landlord(self):
        return self.role is not None and self.role.name == "Landlord"

    @property
    def is_admin(self):
        return self.role is not None and self.role.name == "Administrator"

    @property
    def full_name(self):
        return f"{self.firstname} {self.lastname}"

    def __repr__(self):
        return f"<User {self.email}>"


class RenterDetails(db.Model):
    __tablename__ = "renter_details"

    renter_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), primary_key=True)
    preferredlocation = db.Column(db.String(100))
    budgetrange = db.Column(db.String(50))

    user = db.relationship("User", back_populates="renter")
    search_alerts = db.relationship("SearchAlert", back_populates="renter")
    notifications = db.relationship("Notification", back_populates="renter")
    payments = db.relationship("Payment", back_populates="renter")


class LandlordDetails(db.Model):
    __tablename__ = "landlord_details"

    landlord_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), primary_key=True)
    businessname = db.Column(db.String(100))
    verificationstatus = db.Column(db.String(20), default="pending")

    user = db.relationship("User", back_populates="landlord")
    properties = db.relationship("Property", back_populates="landlord")


class Property(db.Model):
    __tablename__ = "properties"

    listing_id = db.Column(db.Integer, primary_key=True)
    # null for listings that came in through the scraper instead of a landlord
    landlord_id = db.Column(db.Integer, db.ForeignKey("landlord_details.landlord_id"))
    title = db.Column(db.String(150), nullable=False)
    rentamount = db.Column(db.Numeric(10, 2), nullable=False, index=True)
    bedrooms = db.Column(db.Integer)
    bathrooms = db.Column(db.Integer)
    listingdate = db.Column(db.Date, default=date.today)
    category = db.Column(db.String(50))
    buildingnumber = db.Column(db.String(20))
    city = db.Column(db.String(50), index=True)
    address = db.Column(db.String(150))
    # where a scraped listing originally came from (proposal 1.7)
    source_name = db.Column(db.String(100))
    source_url = db.Column(db.String(255))

    landlord = db.relationship("LandlordDetails", back_populates="properties")
    payments = db.relationship("Payment", back_populates="listing")

    def __repr__(self):
        return f"<Property {self.listing_id} {self.title}>"


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
    search_id = db.Column(db.Integer, db.ForeignKey("search_alert.searchalert_id"))
    date = db.Column(db.Date, default=date.today)
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
    date = db.Column(db.Date, default=date.today)
    modeofpayment = db.Column(db.String(50))
    status = db.Column(db.String(20), default="pending")

    renter = db.relationship("RenterDetails", back_populates="payments")
    listing = db.relationship("Property", back_populates="payments")
