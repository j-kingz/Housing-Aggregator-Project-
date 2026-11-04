"""Tests that the pages render and the access rules hold."""

import re

from app.extensions import db
from app.models import Property, RenterDetails, Role, User
from tests.conftest import login

def add_listing(**extra):
    fields = {
        "title": "A flat in Westlands",
        "rentamount": 55000,
        "address": "Westlands",
        "city": "Nairobi",
        "bedrooms": 2,
        "bathrooms": 2,
        "category": "Apartment",
        "is_active": True,
    }
    fields.update(extra)
    listing = Property(**fields)
    db.session.add(listing)
    db.session.commit()
    return listing


class TestPublicPages:
    def test_the_home_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"navbar-expand-lg" in response.data

    def test_the_search_page_with_filters(self, client):
        add_listing()
        response = client.get("/?location=Westlands&max_price=60000&bedrooms=2&sort=price_low")
        assert response.status_code == 200

    def test_search_can_filter_by_building_unit_and_vacancy(self, client):
        add_listing(
            building_name="Riverside Towers",
            floor_number=4,
            room_number="4B",
            availability_status="vacant",
        )
        response = client.get("/?location=Riverside&availability=vacant")
        assert response.status_code == 200
        assert b"Riverside Towers" in response.data

    def test_the_analytics_dashboard(self, client):
        add_listing()
        assert client.get("/analytics/").status_code == 200

    def test_the_area_analysis(self, client):
        add_listing()
        assert client.get("/analytics/area/Westlands").status_code == 200

    def test_the_listing_page(self, client):
        listing = add_listing()
        assert client.get(f"/listings/{listing.listing_id}").status_code == 200

    def test_a_missing_listing_is_a_404(self, client):
        assert client.get("/listings/999999").status_code == 404


class TestAccessRules:
    def test_the_budget_analyser_needs_a_login(self, client):
        response = client.get("/insights/budget")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_the_admin_area_needs_a_login(self, client):
        response = client.get("/admin/")
        assert response.status_code == 302

    def test_a_renter_cannot_reach_the_admin_area(self, client, renter):
        login(client, renter.email)
        assert client.get("/admin/").status_code == 403

    def test_a_landlord_cannot_reach_the_budget_analyser(self, client, landlord):
        login(client, landlord.email)
        response = client.get("/insights/budget")
        assert response.status_code == 302

    def test_an_admin_can_reach_the_admin_area(self, client, admin):
        login(client, admin.email)
        assert client.get("/admin/").status_code == 200

    def test_a_renter_can_use_the_budget_analyser(self, client, renter):
        login(client, renter.email)
        assert client.get("/insights/budget").status_code == 200

    def test_budget_form_includes_csrf_token(self, client, renter):
        login(client, renter.email)
        response = client.get("/insights/budget")
        assert response.status_code == 200
        assert re.search(rb'name="csrf_token"[^>]+value="[^"]+"', response.data)


class TestRenterPages:
    def test_the_notification_inbox(self, client, renter):
        login(client, renter.email)
        assert client.get("/notifications").status_code == 200

    def test_the_alerts_page(self, client, renter):
        login(client, renter.email)
        assert client.get("/alerts").status_code == 200

    def test_an_alert_can_be_saved(self, client, renter):
        login(client, renter.email)
        response = client.post(
            "/alerts",
            data={"area": "Westlands", "maxprice": "60000", "minbedrooms": "2"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Saved" in response.data


class TestLandlordPages:
    def test_a_landlord_can_add_a_listing(self, client, landlord):
        login(client, landlord.email)
        response = client.post(
            "/listings/new",
            data={
                "title": "A new flat in Westlands",
                "rentamount": "55000",
                "category": "Apartment",
                "bedrooms": "2",
                "bathrooms": "2",
                "city": "Nairobi",
                "address": "Westlands",
                "building_name": "Riverside Towers",
                "floor_number": "4",
                "room_number": "4B",
                "availability_status": "vacant",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert Property.query.count() == 1
        listing = Property.query.first()
        assert listing.building_name == "Riverside Towers"
        assert listing.floor_number == 4
        assert listing.room_number == "4B"
        assert listing.availability_status == "vacant"

    def test_a_landlord_cannot_edit_someone_elses_listing(self, client, landlord, renter):
        listing = add_listing()
        login(client, landlord.email)
        response = client.post(
            f"/listings/{listing.listing_id}/edit",
            data={
                "title": "Hijacked",
                "rentamount": "1000",
                "category": "Apartment",
                "city": "Nairobi",
                "address": "Westlands",
            },
        )
        assert response.status_code == 403


class TestAdminPages:
    def test_an_admin_can_remove_another_admin(self, client, admin):
        target_role = Role.query.filter_by(name="Administrator").first()
        target = User(
            firstname="Second",
            lastname="Admin",
            email="second-admin@example.com",
            role=target_role,
        )
        target.set_password("password123")
        db.session.add(target)
        db.session.commit()

        login(client, admin.email)
        response = client.post(
            f"/admin/users/{target.user_id}/demote",
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert target.role.name == "Renter"
        assert target.renter is not None
        assert target.is_admin is False

    def test_the_sources_page(self, client, admin):
        login(client, admin.email)
        assert client.get("/admin/sources").status_code == 200

    def test_the_runs_page(self, client, admin):
        login(client, admin.email)
        assert client.get("/admin/runs").status_code == 200

    def test_a_source_can_be_added(self, client, admin):
        login(client, admin.email)
        response = client.post(
            "/admin/sources/add",
            data={
                "name": "Test source",
                "base_url": "https://example.com",
                "listing_url": "https://example.com/rent?page={page}",
                "profile": "generic",
                "delay_seconds": "5",
                "max_pages": "2",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Test source" in response.data
