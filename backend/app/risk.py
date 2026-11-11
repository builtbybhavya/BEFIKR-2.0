"""Configurable, explainable prototype risk calculations for Raahi."""

from dataclasses import dataclass
from typing import Any

WEIGHTS = {"incident": 0.25, "freshness": 0.15, "population": 0.10, "lighting": 0.10,
           "time_of_day": 0.10, "historical": 0.10, "isolation": 0.10}


@dataclass(frozen=True)
class SegmentResult:
    score: float | None
    confidence: float
    coverage: float
    classification: str
    explanation: list[str]


def calculate_segment(inputs: dict[str, Any], *, corroboration: float | None = None,
                      minimum_coverage: float = 0.55) -> SegmentResult:
    """Calculate a score from available 0-100 risk inputs; missing data lowers coverage."""
    available = {key: float(inputs[key]) for key in WEIGHTS if inputs.get(key) is not None}
    if any(value < 0 or value > 100 for value in available.values()):
        raise ValueError("Risk inputs must be between 0 and 100")
    coverage = sum(WEIGHTS[key] for key in available) / sum(WEIGHTS.values())
    if coverage == 0:
        return SegmentResult(None, 0.0, 0.0, "insufficient", ["Limited safety data is available."])
    score = sum(WEIGHTS[key] * value for key, value in available.items()) / coverage
    evidence = max(0.0, min(1.0, corroboration if corroboration is not None else 0.0))
    confidence = round(100 * coverage * (0.35 + 0.65 * evidence))
    if coverage < minimum_coverage:
        classification = "insufficient"
        explanation = ["Limited safety data is available.", "This area cannot be reliably classified."]
    elif confidence < 35:
        classification = "insufficient"
        explanation = ["Available information has low confidence.", "This area cannot be reliably classified."]
    else:
        classification = "lower_reported_risk" if score < 35 else "caution" if score < 65 else "elevated_reported_risk"
        explanation = []
        if "incident" in available and available["incident"] >= 35:
            explanation.append("Available reports indicate safety concerns in this area.")
        if "lighting" in available and available["lighting"] >= 50:
            explanation.append("Lighting information indicates some stretches may be poorly lit.")
        if "isolation" in available and available["isolation"] >= 50:
            explanation.append("Available route context indicates some isolated stretches.")
        if not explanation:
            explanation.append("No elevated concern was found in the available information; this is not a guarantee of safety.")
        if confidence < 65:
            explanation.append("Available information has some uncertainty.")
    return SegmentResult(round(score, 1), confidence, round(coverage, 3), classification, explanation[:3])


def calculate_route(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Length-weighted mean plus highest segment, per the BEFIKR prototype equation."""
    known = [segment for segment in segments if segment.get("score") is not None]
    if not known:
        return {"score": None, "classification": "insufficient", "confidence": 0,
                "explanation": ["Limited safety data is available for this route."]}
    lengths = [max(float(s.get("length_km", 0)), 0) for s in known]
    if sum(lengths) == 0:
        lengths = [1.0] * len(known)
    weighted = sum(length * float(s["score"]) for length, s in zip(lengths, known)) / sum(lengths)
    score = round(0.70 * weighted + 0.30 * max(float(s["score"]) for s in known), 1)
    confidence = round(sum(float(s.get("confidence", 0)) * length for s, length in zip(known, lengths)) / sum(lengths))
    classification = "insufficient" if confidence < 35 else "lower_reported_risk" if score < 35 else "caution" if score < 65 else "elevated_reported_risk"
    return {"score": score, "classification": classification, "confidence": confidence,
            "explanation": list(dict.fromkeys(x for s in known for x in s.get("explanation", [])))[:3]}


def compare_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare known route scores with configurable normalized time, distance and uncertainty costs."""
    if not routes:
        return []
    max_time = max(float(r.get("minutes", 0)) for r in routes) or 1
    max_distance = max(float(r.get("distance_km", 0)) for r in routes) or 1
    result = []
    for route in routes:
        risk = route.get("risk_score")
        if risk is None:
            comparison = None
        else:
            time_cost = float(route.get("minutes", 0)) / max_time * 100
            distance_cost = float(route.get("distance_km", 0)) / max_distance * 100
            uncertainty = 100 - float(route.get("confidence", 0))
            comparison = round(0.50 * float(risk) + 0.25 * time_cost + 0.15 * distance_cost + 0.10 * uncertainty, 1)
        result.append({**route, "comparison_score": comparison})
    return result
