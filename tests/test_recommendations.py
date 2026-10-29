"""Tests for the "What can I afford?" recommendations."""

from app.extensions import db
from app.insights import services
from app.models import RenterDetails
from tests.conftest import login, make_user
from tests.test_units import add_unit


def renter_with(**fields):
    user = make_user("r@example.com", "Renter")
    renter = db.session.get(RenterDetails, user.user_id)
    for key, value in fields.items():
        setattr(renter, key, value)
    db.session.commit()
    return renter


class TestRecommend:
    def test_income_alone_is_enough_to_get_recommendations(self, app, areas):
        add_unit(rentamount=20000, room_number="1A")
        add_unit(rentamount=90000, room_number="1B")
        renter = renter_with(monthlyincome=80000)

        result = services.recommend(renter)

        rents = [float(p["listing"].rentamount) for p in result["picks"]]
        assert rents == [20000]        # 90,000 is above 40% of 80,000
        assert result["ceiling"] == 32000

    def test_single_number_budget_is_a_ceiling_not_an_exact_price(self, app, areas):
        add_unit(rentamount=20000, room_number="1A")
        add_unit(rentamount=45000, room_number="1B")
        renter = renter_with(budgetrange="50k")

        result = services.recommend(renter)

        assert len(result["picks"]) == 2

    def test_a_misspelt_preferred_area_still_works(self, app, areas):
        add_unit(rentamount=20000, address="Kilimani", title="Kilimani flat")
        add_unit(rentamount=20000, address="Westlands", title="Westlands flat", room_number="2")
        renter = renter_with(preferredlocation="kilmani", budgetrange="30000")

        result = services.recommend(renter)

        assert result["picks"][0]["listing"].title == "Kilimani flat"
        assert result["picks"][0]["in_pref"] is True

    def test_other_areas_are_shown_when_the_preferred_one_is_empty(self, app, areas):
        add_unit(rentamount=20000, address="South B", title="South B flat",
                 latitude=-1.3141, longitude=36.8376)
        renter = renter_with(preferredlocation="Kilimani", budgetrange="30000")

        result = services.recommend(renter)

        assert [p["listing"].title for p in result["picks"]] == ["South B flat"]
        assert any("so other areas are shown" in n or "nearby" in n for n in result["notes"])

    def test_occupied_and_reserved_units_are_never_recommended(self, app, areas):
        add_unit(rentamount=20000, availability_status="occupied", room_number="1A")
        add_unit(rentamount=20000, availability_status="reserved", room_number="1B")
        add_unit(rentamount=20000, availability_status="vacant", room_number="1C")
        result = services.recommend(renter_with(budgetrange="30000"))
        assert [p["listing"].room_number for p in result["picks"]] == ["1C"]

    def test_vacant_units_rank_above_unconfirmed_ones(self, app, areas):
        add_unit(rentamount=20000, availability_status="unknown", room_number="U")
        add_unit(rentamount=20000, availability_status="vacant", room_number="V")
        result = services.recommend(renter_with(budgetrange="30000"))
        assert result["picks"][0]["listing"].room_number == "V"

    def test_when_nothing_fits_it_says_how_much_more_is_needed(self, app, areas):
        add_unit(rentamount=30000)
        result = services.recommend(renter_with(budgetrange="20000"))
        assert result["picks"] == []
        assert result["near_misses"]
        assert any("10,000" in n for n in result["notes"])

    def test_travel_cost_is_part_of_the_real_monthly_cost(self, app, areas):
        add_unit(rentamount=20000, latitude=-1.373, longitude=36.817, address="South B")
        # works in Westlands, so South B is a real trip away
        renter = renter_with(monthlyincome=80000, workplace="Westlands", workplacearea="Westlands",
                             workplace_lat=-1.2676, workplace_lng=36.8108)
        entry = services.recommend(renter)["picks"][0]
        assert entry["distance_km"] > 5
        assert entry["monthly_commute"] > 0
        assert entry["total_monthly"] == 20000 + entry["monthly_commute"]
        assert any("a month to travel" in r for r in entry["reasons"])

    def test_the_bedroom_filter_applies(self, app, areas):
        add_unit(rentamount=20000, bedrooms=1, room_number="1")
        add_unit(rentamount=22000, bedrooms=3, room_number="3")
        result = services.recommend(renter_with(budgetrange="30000"), beds=2)
        assert [p["listing"].room_number for p in result["picks"]] == ["3"]


class TestAnalyserPage:
    def test_saving_the_form_then_seeing_homes(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        add_unit(rentamount=20000, title="Affordable flat")
        client.post("/insights/budget", data={
            "monthlyincome": "80000", "budget_max": "", "preferredlocation": "",
            "workplace": "", "commute_mode": "matatu",
        })
        page = client.get("/insights/budget").get_data(as_text=True)
        assert "Affordable flat" in page
        assert "Top match" in page

    def test_an_unknown_preferred_area_is_reported_not_silently_dropped(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        page = client.post("/insights/budget", data={
            "monthlyincome": "80000", "preferredlocation": "zzzzqqq", "commute_mode": "matatu",
        }, follow_redirects=True).get_data(as_text=True)
        assert "know a neighbourhood called" in page.replace("&#34;", '"')

    def test_a_bad_income_is_reported(self, client, app, areas):
        make_user("r@example.com", "Renter")
        login(client, "r@example.com")
        page = client.post("/insights/budget", data={
            "monthlyincome": "lots", "commute_mode": "matatu",
        }, follow_redirects=True).get_data(as_text=True)
        assert "has to be a number" in page
