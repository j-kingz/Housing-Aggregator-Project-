"""Tests for saved homes, counties, vacancy tabs and the "not confirmed" guidance."""

from app.extensions import db
from app.models import Area, Favorite, Property, ScrapingSource
from app.places import services as places
from tests.conftest import login, make_user
from tests.test_units import add_unit


class TestFavorites:
    def test_a_visitor_must_log_in_to_save(self, client, app, areas):
        unit = add_unit()
        response = client.post(f"/favorites/{unit.listing_id}/toggle")
        assert response.status_code == 302 and "/login" in response.headers["Location"]
        assert Favorite.query.count() == 0

    def test_saving_and_removing(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit()
        first = client.post(f"/favorites/{unit.listing_id}/toggle", headers={"Accept": "application/json"})
        assert first.get_json() == {"saved": True, "count": 1}
        second = client.post(f"/favorites/{unit.listing_id}/toggle", headers={"Accept": "application/json"})
        assert second.get_json() == {"saved": False, "count": 0}
        assert Favorite.query.count() == 0

    def test_the_saved_page_lists_only_my_homes(self, client, app, areas):
        make_user("r@example.com", "Renter")
        make_user("other@example.com", "Renter")
        mine = add_unit(title="My favourite flat", room_number="1")
        other = add_unit(title="A neighbour flat", room_number="2")
        login(client, "other@example.com")
        client.post(f"/favorites/{other.listing_id}/toggle")
        client.post("/logout")
        login(client, "r@example.com")
        client.post(f"/favorites/{mine.listing_id}/toggle")
        page = client.get("/favorites/").get_data(as_text=True)
        assert "My favourite flat" in page
        assert "A neighbour flat" not in page

    def test_a_saved_home_shows_a_filled_heart_in_search(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        unit = add_unit()
        client.post(f"/favorites/{unit.listing_id}/toggle")
        page = client.get("/").get_data(as_text=True)
        assert 'class="heart-btn saved"' in page

    def test_saving_a_missing_home_is_a_404(self, client, app):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        assert client.post("/favorites/9999/toggle").status_code == 404


class TestCounties:
    def add_area(self, name, county):
        db.session.add(Area(name=name, city="Nairobi", county=county, latitude=-1.2, longitude=36.8))
        db.session.commit()

    def test_a_county_is_suggested_with_its_neighbourhoods(self, app, areas):
        self.add_area("Ruaka", "Kiambu")
        items = places.suggest_places("kiambu")
        types = [(i["type"], i["label"]) for i in items]
        assert ("county", "Kiambu County") in types
        assert ("area", "Ruaka") in types
        assert types.index(("county", "Kiambu County")) < types.index(("area", "Ruaka"))

    def test_neighbourhoods_can_be_limited_to_a_county(self, app, areas):
        self.add_area("Ruaka", "Kiambu")
        names = [i["label"] for i in places.suggest_areas("", county="Kiambu")]
        assert names == ["Ruaka"]

    def test_places_anywhere_in_kenya_come_from_the_map_service(self, app, areas, monkeypatch):
        monkeypatch.setattr(places, "external_places", lambda q, limit=5: [
            {"label": "Sarit Centre", "detail": "Westlands, Nairobi County", "type": "place",
             "value": "Sarit Centre", "lat": -1.2603, "lng": 36.8019}])
        items = places.suggest_places("sarit")
        assert any(i["type"] == "place" and i["label"] == "Sarit Centre" for i in items)

    def test_the_map_service_can_be_skipped(self, client, app, areas, monkeypatch):
        calls = []
        monkeypatch.setattr(places, "external_places", lambda q, limit=5: calls.append(q) or [])
        client.get("/api/suggest?kind=place&q=sarit&ext=0")
        assert calls == []
        client.get("/api/suggest?kind=place&q=sarit")
        assert calls == ["sarit"]

    def test_a_failing_map_service_returns_nothing_instead_of_an_error(self, app, monkeypatch):
        import requests

        def broken(*args, **kwargs):
            raise requests.ConnectionError()

        monkeypatch.undo()   # use the real function, with a broken network
        monkeypatch.setattr(requests, "get", broken)
        places._cache.clear()
        assert places.external_places("nowhere at all") == []

    def test_search_by_county_finds_every_neighbourhood_in_it(self, client, app, areas):
        self.add_area("Ruaka", "Kiambu")
        ruaka = Area.query.filter_by(name="Ruaka").one()
        add_unit(title="Ruaka flat", address="Ruaka", area_id=ruaka.area_id, room_number="1")
        add_unit(title="Westlands flat", address="Westlands", room_number="2")
        page = client.get("/?county=Kiambu").get_data(as_text=True)
        assert "Ruaka flat" in page and "Westlands flat" not in page

    def test_typing_a_county_name_in_where_searches_the_county(self, client, app, areas):
        self.add_area("Ruaka", "Kiambu")
        ruaka = Area.query.filter_by(name="Ruaka").one()
        add_unit(title="Ruaka flat", address="Ruaka", area_id=ruaka.area_id, room_number="1")
        page = client.get("/?location=Kiambu%20County").get_data(as_text=True)
        assert "Ruaka flat" in page
        assert "Kiambu County" in page      # the box shows the county back


class TestVacancyTabs:
    def test_the_tabs_count_each_kind(self, client, app, areas):
        add_unit(room_number="1", availability_status="vacant")
        add_unit(room_number="2", availability_status="vacant")
        add_unit(room_number="3", availability_status="unknown")
        page = client.get("/").get_data(as_text=True)
        assert "All homes <span>3</span>" in page
        assert "Vacant only <span>2</span>" in page
        assert "Not confirmed <span>1</span>" in page

    def test_vacant_only_lists_just_the_vacant_homes(self, client, app, areas):
        add_unit(room_number="1", title="Free flat", availability_status="vacant")
        add_unit(room_number="2", title="Unknown flat", availability_status="unknown")
        page = client.get("/?availability=vacant").get_data(as_text=True)
        assert "Free flat" in page and "Unknown flat" not in page


class TestNotConfirmedGuidance:
    def test_the_detail_page_sends_the_person_to_the_original_advert(self, client, app, areas):
        unit = add_unit(availability_status="unknown", source_url="https://example.com/ad/1", source_name="Jiji")
        page = client.get(f"/listings/{unit.listing_id}").get_data(as_text=True)
        assert "We could not confirm this unit is free" in page
        assert 'href="https://example.com/ad/1"' in page
        assert "agent" in page

    def test_a_vacant_unit_has_no_warning(self, client, app, areas):
        unit = add_unit(availability_status="vacant", source_url="https://example.com/ad/1")
        page = client.get(f"/listings/{unit.listing_id}").get_data(as_text=True)
        assert "We could not confirm" not in page

    def test_the_search_card_tells_you_to_check(self, client, app, areas):
        add_unit(availability_status="unknown")
        page = client.get("/").get_data(as_text=True)
        assert "Not confirmed. Open this home" in page


class TestMapsShowEverything:
    def test_the_search_map_holds_every_match_not_just_one_page(self, client, app, areas):
        for n in range(15):
            add_unit(room_number=str(n), latitude=-1.26 + n / 1000, longitude=36.80)
        page = client.get("/").get_data(as_text=True)
        assert "All 15 locations on the map" in page


class TestSampleDataIsGone:
    def test_init_db_removes_the_sample_listings_and_source(self, app, areas):
        import init_db

        db.session.add(ScrapingSource(name="Sample fixture", profile="fixture"))
        db.session.commit()
        add_unit(title="Demo flat", source_name="Sample fixture", room_number="1")
        add_unit(title="Real flat", source_name="Jiji", room_number="2")

        assert init_db.remove_sample_data() == 1

        assert Property.query.filter_by(title="Demo flat").count() == 0
        assert Property.query.filter_by(title="Real flat").count() == 1
        assert ScrapingSource.query.filter_by(name="Sample fixture").count() == 0

    def test_the_default_sources_have_no_sample(self):
        from app.seed_data import DEFAULT_SOURCES

        assert all(s["profile"] != "fixture" for s in DEFAULT_SOURCES)
