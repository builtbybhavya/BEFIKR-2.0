"""External-service boundaries with explicit providers and honest fallbacks."""

from dataclasses import dataclass
import json
import math
import os
import threading
import time
from typing import Any, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class MappingProvider(Protocol):
    name: str

    def alternatives(self, origin: str, destination: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DemoMappingProvider:
    """Clearly non-navigable placeholders. Never fabricate geometry or metrics."""

    name: str = "demo"

    def alternatives(self, origin: str, destination: str) -> dict[str, Any]:
        options = [
            {"id": "demo-direct", "label": "Illustrative option A", "distance_km": 0, "minutes": 0,
             "risk_score": None, "confidence": 0, "classification": "insufficient", "navigable": False,
             "provider": self.name, "explanation": ["No live mapping or route data is configured.", "Safety data cannot be classified."]},
            {"id": "demo-connected", "label": "Illustrative option B", "distance_km": 0, "minutes": 0,
             "risk_score": None, "confidence": 0, "classification": "insufficient", "navigable": False,
             "provider": self.name, "explanation": ["Illustrative placeholder only; it is not a real route.", "No live mapping or route data is configured."]},
        ]
        return {"origin": origin, "destination": destination, "provider_state": "demo_only",
                "warning": "These are placeholders, not real routes. Configure a mapping provider before navigation.",
                "routes": options}


@dataclass(frozen=True)
class UnavailableMappingProvider:
    name: str
    reason: str

    def alternatives(self, origin: str, destination: str) -> dict[str, Any]:
        return {"origin": origin, "destination": destination, "provider_state": "not_configured",
                "warning": self.reason, "routes": []}


class OSMnxWalkingProvider:
    """Build walking alternatives from the OSM pedestrian graph when explicitly enabled."""

    name = "osmnx_openstreetmap"
    _geocode_lock = threading.Lock()
    _last_geocode_at = 0.0

    def _geocode(self, ox: Any, query: str) -> tuple[float, float]:
        # Respect Nominatim's public-service request cadence. This is in-memory only.
        with self._geocode_lock:
            pause = 1.1 - (time.monotonic() - self._last_geocode_at)
            if pause > 0:
                time.sleep(pause)
            point = ox.geocoder.geocode(query)
            self._last_geocode_at = time.monotonic()
        return float(point[0]), float(point[1])

    @staticmethod
    def _path_geometry(graph: Any, path: list[int]) -> tuple[list[list[float]], float]:
        coordinates: list[list[float]] = []
        distance_m = 0.0
        for start, end in zip(path, path[1:]):
            edges = graph.get_edge_data(start, end) or {}
            if not edges:
                continue
            edge = min(edges.values(), key=lambda item: float(item.get("length", math.inf)))
            distance_m += float(edge.get("length", 0))
            start_xy = (float(graph.nodes[start]["x"]), float(graph.nodes[start]["y"]))
            end_xy = (float(graph.nodes[end]["x"]), float(graph.nodes[end]["y"]))
            geometry = edge.get("geometry")
            line = list(geometry.coords) if geometry is not None else [start_xy, end_xy]
            if line and math.dist(line[0], start_xy) > math.dist(line[-1], start_xy):
                line.reverse()
            for lon, lat in line:
                pair = [float(lon), float(lat)]
                if not coordinates or coordinates[-1] != pair:
                    coordinates.append(pair)
        return coordinates, distance_m

    def alternatives(self, origin: str, destination: str) -> dict[str, Any]:
        try:
            import osmnx as ox
        except ImportError:
            return {"origin": origin, "destination": destination, "provider_state": "dependency_missing",
                    "warning": "Install the declared OSMnx dependency and set BEFIKR_MAPPING_PROVIDER=osmnx to enable pedestrian routing.",
                    "routes": []}
        try:
            ox.settings.use_cache = False
            ox.settings.log_console = False
            ox.settings.timeout = 30
            ox.settings.http_user_agent = "BEFIKR-Raahi/0.1"
            origin_point = self._geocode(ox, origin)
            destination_point = self._geocode(ox, destination)
            mean_lat = (origin_point[0] + destination_point[0]) / 2
            mean_lon = (origin_point[1] + destination_point[1]) / 2
            direct_m = 111_000 * math.hypot(destination_point[0] - origin_point[0],
                                             (destination_point[1] - origin_point[1]) * math.cos(math.radians(mean_lat)))
            radius_m = min(25_000, max(3_000, direct_m * 0.65 + 2_500))
            graph = ox.graph.graph_from_point((mean_lat, mean_lon), dist=radius_m,
                                              dist_type="bbox", network_type="walk", simplify=True)
            start_node = ox.distance.nearest_nodes(graph, X=origin_point[1], Y=origin_point[0])
            end_node = ox.distance.nearest_nodes(graph, X=destination_point[1], Y=destination_point[0])
            paths = list(ox.routing.k_shortest_paths(graph, start_node, end_node, k=3, weight="length"))
            routes = []
            seen: set[tuple[int, ...]] = set()
            for path in paths:
                if not path or len(path) < 2 or tuple(path) in seen:
                    continue
                seen.add(tuple(path))
                coordinates, distance_m = self._path_geometry(graph, path)
                if len(coordinates) < 2 or distance_m <= 0:
                    continue
                distance_km = distance_m / 1000
                routes.append({
                    "id": f"osm-walk-{len(routes) + 1}",
                    "label": "Shortest walking route" if not routes else f"Walking alternative {len(routes) + 1}",
                    "distance_km": round(distance_km, 2),
                    "minutes": round(distance_km / 4.5 * 60),
                    "risk_score": None,
                    "confidence": 0,
                    "classification": "insufficient",
                    "navigable": False,
                    "provider": self.name,
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                    "explanation": ["Path follows the OpenStreetMap pedestrian network.",
                                    "No Safetipin or other route-matched personal-safety data is connected.",
                                    "Walking time is a rough estimate, not live navigation."],
                })
            return {"origin": origin, "destination": destination,
                    "provider_state": "walking_routes_available" if routes else "no_walking_route",
                    "provider": self.name,
                    "warning": "These are pedestrian-network options from OpenStreetMap. They are not safety-rated; the route geometry is a map estimate, not turn-by-turn navigation.",
                    "routes": routes}
        except Exception as error:
            return {"origin": origin, "destination": destination, "provider_state": "routing_unavailable",
                    "provider": self.name,
                    "warning": f"OpenStreetMap walking routes could not be loaded ({type(error).__name__}). Check the place names and internet connection, then try again.",
                    "routes": []}


@dataclass(frozen=True)
class MapboxDirectionsProvider:
    access_token: str
    name: str = "mapbox_walking"

    @staticmethod
    def _get_json(url: str) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "BEFIKR-Raahi/0.1"})
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read(2_000_001).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("The mapping provider returned an invalid response")
        return body

    def _geocode(self, query: str) -> tuple[float, float]:
        params = urlencode({"q": query, "country": "IN", "limit": 1, "access_token": self.access_token})
        result = self._get_json(f"https://api.mapbox.com/search/geocode/v6/forward?{params}")
        features = result.get("features") or []
        if not features:
            raise ValueError(f"Could not find {query}")
        longitude, latitude = features[0]["geometry"]["coordinates"][:2]
        return float(longitude), float(latitude)

    def alternatives(self, origin: str, destination: str) -> dict[str, Any]:
        try:
            start = self._geocode(origin)
            finish = self._geocode(destination)
            coordinates = f"{start[0]},{start[1]};{finish[0]},{finish[1]}"
            params = urlencode({"alternatives": "true", "geometries": "geojson", "overview": "full",
                                "access_token": self.access_token})
            result = self._get_json(f"https://api.mapbox.com/directions/v5/mapbox/walking/{quote(coordinates, safe=',;')}?{params}")
            if result.get("code") != "Ok":
                raise ValueError(result.get("message") or result.get("code") or "No walking route found")
            routes = []
            for index, route in enumerate(result.get("routes") or []):
                distance_km = float(route.get("distance", 0)) / 1000
                routes.append({
                    "id": f"mapbox-walk-{index + 1}",
                    "label": "Walking route" if index == 0 else f"Walking alternative {index + 1}",
                    "distance_km": round(distance_km, 2),
                    "minutes": round(float(route.get("duration", 0)) / 60),
                    "risk_score": None,
                    "confidence": 0,
                    "classification": "insufficient",
                    "navigable": False,
                    "provider": self.name,
                    "geometry": route.get("geometry"),
                    "explanation": ["Walking geometry and estimates are from Mapbox Directions.",
                                    "No Safetipin or other route-matched personal-safety data is connected."],
                })
            return {"origin": origin, "destination": destination, "provider_state": "walking_routes_available",
                    "provider": self.name,
                    "warning": "Mapbox returned walking routes. They are not safety-rated; navigation must be opened separately.",
                    "routes": routes}
        except Exception as error:
            return {"origin": origin, "destination": destination, "provider_state": "routing_unavailable",
                    "provider": self.name,
                    "warning": f"Mapbox walking routes could not be loaded ({type(error).__name__}). Check provider access and place names.",
                    "routes": []}


def configured_mapping_provider() -> MappingProvider:
    provider = os.getenv("BEFIKR_MAPPING_PROVIDER", "demo").strip().lower()
    if provider == "osmnx":
        return OSMnxWalkingProvider()
    if provider == "mapbox":
        token = os.getenv("MAPBOX_ACCESS_TOKEN", "").strip()
        if token:
            return MapboxDirectionsProvider(token)
        return UnavailableMappingProvider("mapbox", "Set MAPBOX_ACCESS_TOKEN on the server before selecting the Mapbox provider.")
    return DemoMappingProvider()


@dataclass(frozen=True)
class DeliveryResult:
    state: str
    confirmed: bool
    detail: str


class NotificationProvider(Protocol):
    def send(self, recipient: str, message: str) -> DeliveryResult: ...


@dataclass(frozen=True)
class UnconfiguredNotificationProvider:
    def send(self, recipient: str, message: str) -> DeliveryResult:
        return DeliveryResult("not_configured", False, "No notification provider is configured.")


class EvidenceStorageProvider(Protocol):
    def store(self, filename: str, content: bytes) -> str: ...


@dataclass(frozen=True)
class UnconfiguredEvidenceStorage:
    def store(self, filename: str, content: bytes) -> str:
        raise RuntimeError("Secure evidence storage and scanning are not configured.")
