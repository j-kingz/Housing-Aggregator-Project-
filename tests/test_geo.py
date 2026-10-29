"""Tests for the GPS helpers (Plus Codes) and the place suggestions."""

from app.extensions import db
from app.geo import decode_plus_code, find_plus_code
from app.models import Property
from app.places import services as places


class TestPlusCodes:
    def test_a_full_code_is_decoded(self):
        # the reference example from the Open Location Code specification
        lat, lng = decode_plus_code("8FVC9G8F+6W")
        assert round(lat, 4) == 47.3656
        assert round(lng, 4) == 8.5248

    def test_a_short_code_is_completed_from_a_nearby_point(self):
        lat, lng = decode_plus_code("PQRR+9WG", -1.2465, 36.7861)
        assert -1.27 < lat < -1.25
        assert 36.78 < lng < 36.80

    def test_a_short_code_without_a_reference_is_refused(self):
        assert decode_plus_code("PQRR+9WG") is None

    def test_rubbish_is_refused(self):
        assert decode_plus_code("hello") is None
        assert decode_plus_code("") is None

    def test_the_code_is_found_inside_an_address(self):
        assert find_plus_code("PQRR+9WG Brookside Grove, Westlands, Nairobi") == "PQRR+9WG"
        assert find_plus_code("Kilimani, Nairobi") is None


class TestSuggestions:
    def test_names_that_start_with_the_text_come_first(self, app, areas):
        names = [i["label"] for i in places.suggest_areas("kil")]
        assert names[0] == "Kilimani"

    def test_a_typing_mistake_still_finds_the_place(self, app, areas):
        names = [i["label"] for i in places.suggest_areas("westlnds")]
        assert "Westlands" in names

    def test_resolve_area_corrects_a_near_miss(self, app, areas):
        area, corrected = places.resolve_area("kilmani")
        assert area.name == "Kilimani"
        assert corrected is True

    def test_resolve_area_exact_match_is_not_a_correction(self, app, areas):
        area, corrected = places.resolve_area("south b")
        assert area.name == "South B"
        assert corrected is False

    def test_resolve_area_gives_up_on_nonsense(self, app, areas):
        assert places.resolve_area("zzzzqqq") == (None, False)

    def test_buildings_are_suggested_too(self, app, areas):
        db.session.add(
            Property(title="2 bed", rentamount=50000, city="Nairobi", address="Westlands",
                     building_name="Riverside Towers", is_active=True,
                     latitude=-1.26, longitude=36.8)
        )
        db.session.commit()
        items = places.suggest_places("river")
        assert any(i["type"] == "building" and i["label"] == "Riverside Towers" for i in items)

    def test_the_endpoint_returns_json(self, client, areas):
        data = client.get("/api/suggest?kind=area&q=west").get_json()
        assert data["items"][0]["label"] == "Westlands"
        assert data["items"][0]["lat"] is not None
