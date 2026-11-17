"""Tests that the pages render and the access rules hold."""

import re

from app.extensions import db
from app.models import Property, RenterDetails, Role, User
from tests.conftest import login, make_user

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
        html = response.get_data(as_text=True)
        # Place and Bedrooms; the county fills itself in from the place
        assert html.count('class="required-star"') == 2
        assert "Please add an input or selection in this field" in html

    def test_registration_explains_and_enforces_password_mixture(self, client):
        html = client.get("/register").get_data(as_text=True)
        assert "at least 8 characters" in html
        assert "uppercase" in html
        assert "special character" in html
        assert 'id="passwordRequirements"' in html
        assert 'data-rule="length"' in html
        assert 'data-rule="special"' in html
        assert 'id="passwordMatchMessage"' in html
        assert "Passwords do not match." in html

        response = client.post(
            "/register",
            data={
                "firstname": "Weak",
                "lastname": "Password",
                "email": "weak@example.com",
                "account_type": "Renter",
                "password": "12345678",
                "confirm_password": "12345678",
            },
        )
        assert response.status_code == 400
        assert b"uppercase letter" in response.data

    def test_registration_accepts_a_mixed_password(self, client):
        response = client.post(
            "/register",
            data={
                "firstname": "Strong",
                "lastname": "Password",
                "email": "strong@example.com",
                "account_type": "Renter",
                "password": "Rent@2026",
                "confirm_password": "Rent@2026",
            },
        )
        assert response.status_code == 302

    def test_forgot_password_sends_a_reset_link_without_revealing_accounts(
        self, client, app, monkeypatch
    ):
        user = make_user("reset@example.com", "Renter")
        sent = []
        monkeypatch.setattr(
            "app.auth.routes.send_password_reset",
            lambda account, reset_url: sent.append((account.email, reset_url)),
        )

        response = client.post(
            "/forgot-password", data={"email": user.email}, follow_redirects=True
        )
        assert response.status_code == 200
        assert "If an active account uses that email" in response.get_data(as_text=True)
        assert sent and sent[0][0] == user.email
        assert "/reset-password/" in sent[0][1]

        response = client.post(
            "/forgot-password",
            data={"email": "missing@example.com"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "If an active account uses that email" in response.get_data(as_text=True)

    def test_reset_password_token_is_single_use_and_requires_strong_password(
        self, client, app, monkeypatch
    ):
        user = make_user("reset-token@example.com", "Renter")
        sent = []
        monkeypatch.setattr(
            "app.auth.routes.send_password_reset",
            lambda account, reset_url: sent.append(reset_url),
        )
        client.post("/forgot-password", data={"email": user.email})
        reset_url = sent[0]

        response = client.get(reset_url.replace("http://localhost", ""))
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'id="passwordRequirements"' in html
        assert 'data-rule="special"' in html
        assert 'id="passwordMatchMessage"' in html
        assert "Passwords do not match." in html

        response = client.post(
            reset_url.replace("http://localhost", ""),
            data={"password": "12345678", "confirm_password": "12345678"},
        )
        assert response.status_code == 200
        assert b"at least 8 characters" in response.data

        response = client.post(
            reset_url.replace("http://localhost", ""),
            data={"password": "Reset@2026", "confirm_password": "Reset@2026"},
        )
        assert response.status_code == 302
        assert user.password_reset_token_hash is None

        response = client.get(reset_url.replace("http://localhost", ""))
        assert response.status_code == 302
        assert "/forgot-password" in response.headers["Location"]

    def test_the_search_page_with_filters(self, client):
        add_listing()
        response = client.get("/?location=Westlands&max_price=60000&bedrooms=2&sort=price_low")
        assert response.status_code == 200

    def test_homepage_search_requires_place_and_bedrooms(self, client):
        response = client.get("/?search=1&county=Kiambu&bedrooms=2")
        assert response.status_code == 302
        response = client.get("/?search=1&location=Westlands&county=Kiambu")
        assert response.status_code == 302

    def test_homepage_search_does_not_need_a_county(self, client):
        # the county is filled in from the place, so a search without one works
        response = client.get("/?search=1&location=Westlands&bedrooms=2")
        assert response.status_code == 200

    def test_homepage_county_box_fills_itself_from_the_place(self, client):
        html = client.get("/").get_data(as_text=True)
        assert "Where in Kenya" not in html
        assert ">Place <" in html
        assert ">County</label>" in html
        # a read-only box the user never types in, backed by a hidden field
        assert 'id="county_display"' in html and "readonly" in html
        assert 'type="hidden" id="county" name="county"' in html
        assert 'data-county-field="#county" data-county-any' in html
        assert '<select id="county"' not in html
        # the county names the browser uses to read a county from an address
        assert '"Mombasa"' in html and '"Nairobi"' in html
        assert "Murang" in html
        assert 'value="0"' in html
        assert "Bedsitter / studio" in html

    def test_a_typed_neighbourhood_fills_the_county_box(self, client, areas):
        html = client.get("/?search=1&location=Westlands&bedrooms=2").get_data(as_text=True)
        assert 'value="Nairobi County"' in html
        assert 'name="county" value="Nairobi"' in html

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
