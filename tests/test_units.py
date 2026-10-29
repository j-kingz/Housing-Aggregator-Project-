"""Tests for units (building, floor, room, vacancy), GPS and the search filters."""

from app.extensions import db
from app.models import Property
from tests.conftest import login, make_user


def add_unit(landlord_id=None, **kwargs):
    base = dict(
        title="2 Bedroom in Westlands", rentamount=60000, bedrooms=2, city="Nairobi",
        address="Westlands", building_name="Riverside Towers", is_active=True,
        landlord_id=landlord_id, availability_status="vacant",
    )
    base.update(kwargs)
    unit = Property(**base)
    db.session.add(unit)
    db.session.commit()
    return unit


class TestSearchShowsTheUnit:
    def test_the_card_shows_building_floor_unit_and_vacancy(self, client, app, areas):
        add_unit(floor_number=4, room_number="4B")
        page = client.get("/").get_data(as_text=True)
        assert "Riverside Towers" in page
        assert "Floor <strong>4</strong>" in page
        assert "Unit <strong>4B</strong>" in page
        assert "Vacant" in page

    def test_filter_by_floor(self, client, app, areas):
        add_unit(floor_number=4, room_number="4B", title="Fourth floor flat")
        add_unit(floor_number=1, room_number="1A", title="First floor flat")
        page = client.get("/?floor=4").get_data(as_text=True)
        assert "Fourth floor flat" in page
        assert "First floor flat" not in page

    def test_filter_vacant_only(self, client, app, areas):
        add_unit(room_number="1A", title="Free flat")
        add_unit(room_number="1B", title="Taken flat", availability_status="occupied")
        page = client.get("/?availability=vacant").get_data(as_text=True)
        assert "Free flat" in page
        assert "Taken flat" not in page

    def test_a_misspelt_neighbourhood_is_corrected_not_empty(self, client, app, areas):
        add_unit(title="Westlands flat")
        page = client.get("/?area=westlnds").get_data(as_text=True)
        assert "Westlands flat" in page
        assert "Showing Westlands" in page

    def test_an_unknown_neighbourhood_is_ignored_with_a_message(self, client, app, areas):
        add_unit(title="Westlands flat")
        page = client.get("/?area=zzzzqqq").get_data(as_text=True)
        assert "Westlands flat" in page
        assert "don&#39;t know a neighbourhood" in page or "don't know a neighbourhood" in page

    def test_nearest_sort_puts_the_closest_unit_first(self, client, app, areas):
        add_unit(title="Far flat", latitude=-1.40, longitude=36.90)
        add_unit(title="Near flat", latitude=-1.2601, longitude=36.8001)
        page = client.get("/?location=Westlands&place_lat=-1.26&place_lng=36.80").get_data(as_text=True)
        # compare the cards (the map data above them also names both homes)
        near = page.index('text-truncate">Near flat')
        far = page.index('text-truncate">Far flat')
        assert near < far


class TestBuildingPage:
    def test_units_are_grouped_by_floor_with_vacancy(self, client, app, areas):
        add_unit(floor_number=1, room_number="1A")
        add_unit(floor_number=1, room_number="1B", availability_status="occupied")
        add_unit(floor_number=2, room_number="2A")
        page = client.get("/listings/building?name=Riverside Towers").get_data(as_text=True)
        assert "Floor 2" in page and "Floor 1" in page
        assert page.index("Floor 2") < page.index("Floor 1")
        assert "2 vacant" in page
        assert "Unit 1B" in page

    def test_unknown_building_is_a_404(self, client, app):
        assert client.get("/listings/building?name=Nowhere").status_code == 404


class TestLandlordGps:
    def landlord_form(self, **extra):
        form = {
            "title": "Bedsitter", "rentamount": "15000", "category": "Bedsitter",
            "city": "Nairobi", "address": "Westlands", "building_name": "Riverside Towers",
            "floor_number": "3", "room_number": "3C", "availability_status": "vacant",
        }
        form.update(extra)
        return form

    def test_exact_gps_from_the_form_is_kept_and_marked_exact(self, client, app, areas):
        landlord = make_user("l@example.com", "Landlord")
        login(client, "l@example.com")
        client.post("/listings/new", data=self.landlord_form(latitude="-1.260123", longitude="36.801234"))
        unit = Property.query.filter_by(room_number="3C").one()
        assert float(unit.latitude) == -1.260123
        assert unit.gps_exact is True
        assert unit.landlord_id == landlord.user_id

    def test_without_gps_the_neighbourhood_centre_is_used_and_marked_approximate(self, client, app, areas):
        make_user("l@example.com", "Landlord")
        login(client, "l@example.com")
        client.post("/listings/new", data=self.landlord_form())
        unit = Property.query.filter_by(room_number="3C").one()
        assert unit.latitude is not None
        assert unit.gps_exact is False
        assert unit.area_id is not None

    def test_a_misspelt_neighbourhood_is_snapped_to_the_real_one(self, client, app, areas):
        make_user("l@example.com", "Landlord")
        login(client, "l@example.com")
        client.post("/listings/new", data=self.landlord_form(address="westlnds"))
        assert Property.query.filter_by(room_number="3C").one().address == "Westlands"

    def test_a_half_filled_gps_is_rejected(self, client, app, areas):
        make_user("l@example.com", "Landlord")
        login(client, "l@example.com")
        response = client.post("/listings/new", data=self.landlord_form(latitude="-1.26"))
        assert response.status_code == 400
        assert Property.query.count() == 0
