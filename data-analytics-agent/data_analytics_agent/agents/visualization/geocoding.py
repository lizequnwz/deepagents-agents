"""Lazy, offline US postal and city/state coordinate resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float


_STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def normalize_us_state(value: Any) -> str:
    """Normalize a US state name or abbreviation to its postal code."""

    normalized = str(value or "").strip()
    if len(normalized) == 2:
        return normalized.upper()
    return _STATE_CODES.get(normalized.casefold(), normalized.upper())


class USLocationResolver:
    """Resolve US locations from pgeocode's locally cached GeoNames data."""

    def __init__(self) -> None:
        self._nominatim: Any | None = None

    def _client(self):
        if self._nominatim is None:
            import pgeocode

            self._nominatim = pgeocode.Nominatim("us")
        return self._nominatim

    @staticmethod
    def _point(row: Any) -> GeoPoint | None:
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if latitude != latitude or longitude != longitude:
            return None
        return GeoPoint(latitude=latitude, longitude=longitude)

    def resolve_zip(self, postal_code: Any) -> GeoPoint | None:
        normalized = str(postal_code or "").strip()
        if not normalized:
            return None
        row = self._client().query_postal_code(normalized)
        return self._point(row)

    def resolve_city_state(
        self,
        city: Any,
        state: Any,
    ) -> GeoPoint | None:
        city_name = str(city or "").strip()
        requested_state = normalize_us_state(state)
        if not city_name or not requested_state:
            return None
        matches = self._client().query_location(city_name, top_k=25)
        if matches is None or getattr(matches, "empty", True):
            return None
        candidates = []
        for _, row in matches.iterrows():
            point = self._point(row)
            row_states = {
                normalize_us_state(row.get("state_code")),
                normalize_us_state(row.get("state_name")),
            }
            if requested_state in row_states and point is not None:
                accuracy = row.get("accuracy")
                try:
                    score = float(accuracy)
                except (TypeError, ValueError):
                    score = 0
                candidates.append((score, point))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]
