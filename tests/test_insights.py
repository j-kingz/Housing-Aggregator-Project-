"""Tests for the personalised insights: income ratios, distance and commute."""

from app.insights import services


class TestHaversine:
    def test_the_distance_between_two_nairobi_areas(self):
        # Westlands to Karen, roughly 8 kilometres as the crow flies
        distance = services.haversine_km(-1.2536, 36.7574, -1.3300, 36.7150)
        assert 7.0 < distance < 10.0

    def test_the_same_point_is_zero(self):
        assert services.haversine_km(-1.2536, 36.7574, -1.2536, 36.7574) == 0

    def test_missing_coordinates(self):
        assert services.haversine_km(None, 36.7574, -1.2536, 36.7574) is None


class TestCommuteEstimate:
    def test_the_matatu_estimate(self):
        result = services.commute_estimate(10, "matatu")

        assert result["label"] == "Matatu"
        # the route is 30 percent longer than the straight line
        assert round(result["route_km"]) == 13
        assert result["cost"] > 0
        assert result["minutes"] > 0

    def test_a_car_costs_more_than_a_bus(self):
        car = services.commute_estimate(10, "car")
        bus = services.commute_estimate(10, "bus")
        assert car["cost"] > bus["cost"]

    def test_walking_is_free(self):
        result = services.commute_estimate(2, "walk")
        assert result["cost"] == 0

    def test_no_distance(self):
        result = services.commute_estimate(None, "matatu")
        assert result["cost"] is None
        assert result["minutes"] is None


class TestRentToIncome:
    def test_a_comfortable_rent(self):
        result = services.rent_to_income(25000, 100000)
        assert result["ratio_percent"] == 25
        assert result["verdict"] == "affordable"
        assert result["remaining"] == 75000

    def test_a_stretch(self):
        result = services.rent_to_income(35000, 100000)
        assert result["verdict"] == "stretch"

    def test_beyond_reach(self):
        result = services.rent_to_income(60000, 100000)
        assert result["verdict"] == "expensive"
        assert result["affordable"] is False

    def test_no_income_given(self):
        result = services.rent_to_income(25000, None)
        assert result["ratio_percent"] is None
        assert result["verdict"] == "unknown"

    def test_zero_income(self):
        result = services.rent_to_income(25000, 0)
        assert result["verdict"] == "unknown"


class TestBudgetRange:
    def test_a_range(self):
        assert services.parse_budget_range("20,000 - 30,000") == (20000, 30000)

    def test_a_single_value_is_a_ceiling(self):
        assert services.parse_budget_range("25,000") == (None, 25000)

    def test_shorthand_and_words(self):
        assert services.parse_budget_range("50k") == (None, 50000)
        assert services.parse_budget_range("under 50000") == (None, 50000)
        assert services.parse_budget_range("1.2m") == (None, 1_200_000)
        assert services.parse_budget_range("from 30000") == (30000, None)

    def test_nothing(self):
        assert services.parse_budget_range(None) == (None, None)
        assert services.parse_budget_range("") == (None, None)

    def test_text_with_no_numbers(self):
        assert services.parse_budget_range("anything goes") == (None, None)
