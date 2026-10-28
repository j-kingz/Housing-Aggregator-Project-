"""Tests for the notification engine and the saved search alerts."""

from app.extensions import db
from app.models import Notification, Property, RenterDetails, SearchAlert
from app.notifications import services


def add_listing(title, rent, address="Westlands", city="Nairobi", beds=2, bathrooms=2):
    listing = Property(
        title=title,
        rentamount=rent,
        address=address,
        city=city,
        bedrooms=beds,
        bathrooms=bathrooms,
        category="Apartment",
        is_active=True,
    )
    db.session.add(listing)
    db.session.commit()
    return listing


def make_alert(renter, area=None, maxprice=None, minbedrooms=None, minbathrooms=None):
    alert = SearchAlert(
        renter_id=renter.renter.renter_id,
        area=area,
        maxprice=maxprice,
        minbedrooms=minbedrooms,
        minbathrooms=minbathrooms,
        isactive=True,
        criteria="test alert",
    )
    db.session.add(alert)
    db.session.commit()
    return alert


class TestMatching:
    def test_an_area_match(self, app, renter):
        alert = make_alert(renter, area="Westlands")
        listing = add_listing("A flat", 50000)

        assert services.listing_matches_alert(listing, alert) is True

    def test_a_different_area_does_not_match(self, app, renter):
        alert = make_alert(renter, area="Westlands")
        listing = add_listing("A flat", 50000, address="Karen")

        assert services.listing_matches_alert(listing, alert) is False

    def test_a_price_over_the_limit_does_not_match(self, app, renter):
        alert = make_alert(renter, maxprice=40000)
        listing = add_listing("A flat", 50000)

        assert services.listing_matches_alert(listing, alert) is False

    def test_a_price_inside_the_limit_matches(self, app, renter):
        alert = make_alert(renter, maxprice=60000)
        listing = add_listing("A flat", 50000)

        assert services.listing_matches_alert(listing, alert) is True

    def test_too_few_bedrooms(self, app, renter):
        alert = make_alert(renter, minbedrooms=3)
        listing = add_listing("A flat", 50000, beds=2)

        assert services.listing_matches_alert(listing, alert) is False

    def test_an_empty_alert_matches_everything(self, app, renter):
        alert = make_alert(renter)
        listing = add_listing("A flat", 50000)

        assert services.listing_matches_alert(listing, alert) is True


class TestProfileMatching:
    def test_within_the_budget(self, app, renter):
        renter.renter.budgetrange = "30,000 - 60,000"
        db.session.commit()
        listing = add_listing("A flat", 45000)

        assert services.listing_matches_profile(listing, renter.renter) is True

    def test_over_the_budget(self, app, renter):
        renter.renter.budgetrange = "30,000 - 60,000"
        db.session.commit()
        listing = add_listing("A flat", 90000)

        assert services.listing_matches_profile(listing, renter.renter) is False


class TestCreateNotifications:
    def test_a_matching_listing_creates_a_notification(self, app, renter):
        make_alert(renter, area="Westlands")
        listing = add_listing("A flat in Westlands", 50000)

        created = services.match_new_listings([listing.listing_id])

        assert created == 1
        assert Notification.query.count() == 1
        note = Notification.query.first()
        assert note.type == "listing"
        assert note.listing_id == listing.listing_id
        assert "Westlands" in note.message

    def test_the_same_listing_is_not_announced_twice(self, app, renter):
        make_alert(renter, area="Westlands")
        listing = add_listing("A flat in Westlands", 50000)

        services.match_new_listings([listing.listing_id])
        created_again = services.match_new_listings([listing.listing_id])

        assert created_again == 0
        assert Notification.query.count() == 1

    def test_a_listing_that_does_not_match_creates_nothing(self, app, renter):
        make_alert(renter, area="Karen")
        listing = add_listing("A flat in Westlands", 50000)

        assert services.match_new_listings([listing.listing_id]) == 0
        assert Notification.query.count() == 0

    def test_no_listings_gives_no_notifications(self, app, renter):
        assert services.match_new_listings([]) == 0

    def test_the_unread_count(self, app, renter):
        make_alert(renter, area="Westlands")
        listing = add_listing("A flat in Westlands", 50000)
        services.match_new_listings([listing.listing_id])

        assert services.unread_count(renter.renter.renter_id) == 1

        note = Notification.query.first()
        note.isread = True
        db.session.commit()
        assert services.unread_count(renter.renter.renter_id) == 0


class TestDescribe:
    def test_the_summary_reads_back(self, app, renter):
        alert = make_alert(renter, area="Westlands", maxprice=50000, minbedrooms=2)
        described = alert.describe()

        assert "Westlands" in described
        assert "50,000" in described
        assert "2+ bedrooms" in described
