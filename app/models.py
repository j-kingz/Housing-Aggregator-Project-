from datetime import date, datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db

# Tables follow the "Database Schema" page in the drawio file.
# The Area, ScrapingSource, ScrapingRun and MarketSnapshot tables were added
# for the analytics, scraping and notification modules (see README).


def utcnow():
    """The current UTC time as a plain datetime.

    The date and time columns do not store a timezone, so the value is
    stripped of its offset before it is written.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    def is_renter(self):
        return self.role is not None and self.role.name == "Renter"

    @property
    def is_admin(self):
        return self.role is not None and self.role.name == "Administrator"

    @property
    def full_name(self):
        return f"{self.firstname} {self.lastname}"

    def ensure_renter_details(self):
        """Return the renter row, creating it when it is missing.

        Accounts made outside the website (an admin promoted with
        create_admin.py, for example) may not have one yet.
        """
        from app.extensions import db

        if self.renter is None and self.is_renter:
            details = RenterDetails(renter_id=self.user_id)
            db.session.add(details)
            db.session.commit()
            self.renter = details
        return self.renter

    def ensure_landlord_details(self):
        """Return the landlord row, creating it when it is missing.

        A property has to point at a landlord row, so this is needed before
        a landlord can add a listing.
        """
        from app.extensions import db

        if self.landlord is None and self.is_landlord:
            details = LandlordDetails(landlord_id=self.user_id)
            db.session.add(details)
            db.session.commit()
            self.landlord = details
        return self.landlord

    def __repr__(self):
        return f"<User {self.email}>"


class Area(db.Model):
    """Neighbourhood lookup used for search indexing and distance mapping.

    This is the "D5 Location" store in the Level 2 DFD. Coordinates are
    approximate centroids, good enough for the distance and commute estimates
    the platform shows.
    """

    __tablename__ = "area"

    area_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    city = db.Column(db.String(50), nullable=False, default="Nairobi", index=True)
    county = db.Column(db.String(50))
    latitude = db.Column(db.Numeric(10, 6))
    longitude = db.Column(db.Numeric(10, 6))
    description = db.Column(db.String(255))

    properties = db.relationship("Property", back_populates="area")
    snapshots = db.relationship("MarketSnapshot", back_populates="area")

    def __repr__(self):
        return f"<Area {self.name}>"


class RenterDetails(db.Model):
    __tablename__ = "renter_details"

    renter_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), primary_key=True)
    preferredlocation = db.Column(db.String(100))
    budgetrange = db.Column(db.String(50))
    # inputs for the personalised insights (rent-to-income, commute estimates)
    monthlyincome = db.Column(db.Numeric(10, 2))
    workplace = db.Column(db.String(100))
    workplacearea = db.Column(db.String(100))
    workplace_area_id = db.Column(db.Integer, db.ForeignKey("area.area_id"))
    commute_mode = db.Column(db.String(30), default="matatu")

    user = db.relationship("User", back_populates="renter")
    workplace_area = db.relationship("Area", foreign_keys=[workplace_area_id])
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


class ScrapingSource(db.Model):
    """A site the scraper is allowed to read.

    The administrator can add, enable and configure these from the admin area,
    which is the "Manage Scraping Sources" and "Configure Scraping Rules"
    use cases in the diagrams.
    """

    __tablename__ = "scraping_source"

    source_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    base_url = db.Column(db.String(255))
    listing_url = db.Column(db.String(255))
    # which parsing profile the scraper should use for this site
    profile = db.Column(db.String(50), default="generic")
    enabled = db.Column(db.Boolean, default=True)
    # defensive scraping settings (proposal 3.7.5)
    delay_seconds = db.Column(db.Float, default=5.0)
    max_pages = db.Column(db.Integer, default=3)
    user_agent = db.Column(db.String(255))
    respects_robots = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    last_run_status = db.Column(db.String(30))
    notes = db.Column(db.String(255))

    properties = db.relationship("Property", back_populates="source")
    runs = db.relationship("ScrapingRun", back_populates="source")

    def __repr__(self):
        return f"<ScrapingSource {self.name}>"


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
    building_name = db.Column(db.String(150), index=True)
    floor_number = db.Column(db.Integer)
    room_number = db.Column(db.String(30), index=True)
    availability_status = db.Column(db.String(20), default="unknown", index=True)
    city = db.Column(db.String(50), index=True)
    address = db.Column(db.String(150))
    # where a scraped listing originally came from (proposal 1.7)
    source_name = db.Column(db.String(100))
    source_url = db.Column(db.String(255))

    # ---- additions for the scraping and analytics modules ----
    # link to the neighbourhood the listing sits in
    area_id = db.Column(db.Integer, db.ForeignKey("area.area_id"), index=True)
    # link to the scraping source that produced the listing
    source_id = db.Column(db.Integer, db.ForeignKey("scraping_source.source_id"))
    # identifier used by the source site, used for de-duplication
    external_id = db.Column(db.String(100), index=True)
    # hash of the normalised listing, used for cross-source de-duplication
    fingerprint = db.Column(db.String(64), index=True)
    description = db.Column(db.Text)
    amenities = db.Column(db.String(255))
    size_sqft = db.Column(db.Integer)
    latitude = db.Column(db.Numeric(10, 6))
    longitude = db.Column(db.Numeric(10, 6))
    scraped_at = db.Column(db.DateTime, default=utcnow)
    # stale listings are flagged instead of being deleted straight away
    is_active = db.Column(db.Boolean, default=True, index=True)

    landlord = db.relationship("LandlordDetails", back_populates="properties")
    area = db.relationship("Area", back_populates="properties")
    source = db.relationship("ScrapingSource", back_populates="properties")
    payments = db.relationship("Payment", back_populates="listing")
    notifications = db.relationship("Notification", back_populates="listing")

    @property
    def price_per_sqft(self):
        """Rent per square foot, used by the analytics dashboard."""
        if not self.size_sqft:
            return None
        return float(self.rentamount) / self.size_sqft

    def __repr__(self):
        return f"<Property {self.listing_id} {self.title}>"


class ScrapingRun(db.Model):
    """Log of a single scrape run, so the administrator can see what happened."""

    __tablename__ = "scraping_run"

    run_id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("scraping_source.source_id"), index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="running")
    pages_fetched = db.Column(db.Integer, default=0)
    listings_found = db.Column(db.Integer, default=0)
    listings_saved = db.Column(db.Integer, default=0)
    duplicates_skipped = db.Column(db.Integer, default=0)
    errors_skipped = db.Column(db.Integer, default=0)
    message = db.Column(db.String(255))

    source = db.relationship("ScrapingSource", back_populates="runs")

    def __repr__(self):
        return f"<ScrapingRun {self.run_id} {self.status}>"


class MarketSnapshot(db.Model):
    """Analytics log of the market for one area on one day.

    The ERD calls for an analytics logging table that records market prices
    over time so trends can be plotted on the dashboard.
    """

    __tablename__ = "market_snapshot"

    snapshot_id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.area_id"), index=True)
    city = db.Column(db.String(50), index=True)
    snapshot_date = db.Column(db.Date, default=date.today, index=True)
    listing_count = db.Column(db.Integer, default=0)
    average_rent = db.Column(db.Numeric(10, 2))
    median_rent = db.Column(db.Numeric(10, 2))
    min_rent = db.Column(db.Numeric(10, 2))
    max_rent = db.Column(db.Numeric(10, 2))

    area = db.relationship("Area", back_populates="snapshots")

    def __repr__(self):
        return f"<MarketSnapshot {self.area_id} {self.snapshot_date}>"


class SearchAlert(db.Model):
    __tablename__ = "search_alert"

    searchalert_id = db.Column(db.Integer, primary_key=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("renter_details.renter_id"), nullable=False)
    datecreated = db.Column(db.Date, default=date.today)
    criteria = db.Column(db.String(255))
    frequency = db.Column(db.String(20))

    # the actual filter the matcher runs against
    area = db.Column(db.String(100))
    maxprice = db.Column(db.Numeric(10, 2))
    minbedrooms = db.Column(db.Integer)
    minbathrooms = db.Column(db.Integer)
    isactive = db.Column(db.Boolean, default=True)
    lastchecked = db.Column(db.Date)

    renter = db.relationship("RenterDetails", back_populates="search_alerts")
    notifications = db.relationship("Notification", back_populates="search_alert")

    def describe(self):
        """Human readable summary, used in the alerts page and notifications."""
        bits = []
        if self.area:
            bits.append(f"in {self.area}")
        if self.maxprice:
            bits.append(f"up to KSh {float(self.maxprice):,.0f}")
        if self.minbedrooms:
            bits.append(f"{self.minbedrooms}+ bedrooms")
        return ", ".join(bits) if bits else "any listing"


class Notification(db.Model):
    __tablename__ = "notification"

    notification_id = db.Column(db.Integer, primary_key=True)
    renter_id = db.Column(db.Integer, db.ForeignKey("renter_details.renter_id"), nullable=False)
    search_id = db.Column(db.Integer, db.ForeignKey("search_alert.searchalert_id"))
    date = db.Column(db.Date, default=date.today)
    message = db.Column(db.String(255))
    type = db.Column(db.String(50))

    listing_id = db.Column(db.Integer, db.ForeignKey("properties.listing_id"))
    isread = db.Column(db.Boolean, default=False)
    url = db.Column(db.String(255))

    renter = db.relationship("RenterDetails", back_populates="notifications")
    search_alert = db.relationship("SearchAlert", back_populates="notifications")
    listing = db.relationship("Property", back_populates="notifications")


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
