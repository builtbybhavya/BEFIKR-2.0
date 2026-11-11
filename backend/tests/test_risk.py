import unittest

from app.risk import calculate_route, calculate_segment, compare_routes


class RiskEngineTests(unittest.TestCase):
    def test_missing_inputs_are_not_classified_as_low_risk(self):
        result = calculate_segment({})
        self.assertIsNone(result.score)
        self.assertEqual(result.classification, "insufficient")

    def test_partial_coverage_retains_uncertainty(self):
        result = calculate_segment({"incident": 10, "freshness": 20}, corroboration=0, minimum_coverage=0.55)
        self.assertEqual(result.classification, "insufficient")
        self.assertLess(result.confidence, 35)

    def test_input_range_is_validated(self):
        with self.assertRaises(ValueError):
            calculate_segment({"incident": 101})

    def test_complete_input_coverage_is_normalized_to_one(self):
        result = calculate_segment({key: 50 for key in ("incident", "freshness", "population", "lighting", "time_of_day", "historical", "isolation")})
        self.assertEqual(result.coverage, 1.0)

    def test_route_score_uses_weighted_mean_and_peak(self):
        result = calculate_route([
            {"score": 20, "confidence": 80, "length_km": 1, "explanation": []},
            {"score": 60, "confidence": 40, "length_km": 3, "explanation": []},
        ])
        self.assertEqual(result["score"], 53.0)
        self.assertEqual(result["confidence"], 50)

    def test_unknown_routes_have_no_comparison_recommendation(self):
        routes = compare_routes([{"risk_score": None, "minutes": 10, "distance_km": 5, "confidence": 0}])
        self.assertIsNone(routes[0]["comparison_score"])


if __name__ == "__main__":
    unittest.main()
