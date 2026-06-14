"""Tests for the BirdWeather GraphQL client and its pure helpers."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.birdweather.client import (
    BirdWeatherClient,
    BirdWeatherError,
    _clean_station,
    _haversine_km,
    _normalise_detection,
    _parse_image_credit,
    _species_attribution,
)

# ---- fake transport -------------------------------------------------------- #


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self):
        return self._payload


class _Session:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def post(self, url, json=None, headers=None):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _client(resp=None, exc=None) -> BirdWeatherClient:
    return BirdWeatherClient(_Session(resp, exc))


# ---- _query contract ------------------------------------------------------- #


async def test_query_returns_data() -> None:
    c = _client(_Resp(payload={"data": {"station": {"id": "1"}}}))
    out = await c._query("q", {})
    assert out == {"station": {"id": "1"}}


async def test_query_transport_error_wrapped() -> None:
    c = _client(exc=aiohttp.ClientError("boom"))
    with pytest.raises(BirdWeatherError, match="transport error"):
        await c._query("q", {})


async def test_query_graphql_errors_raise() -> None:
    c = _client(_Resp(payload={"errors": [{"message": "bad"}], "data": None}))
    with pytest.raises(BirdWeatherError):
        await c._query("q", {})


async def test_get_station_clean_or_none() -> None:
    c = _client(_Resp(payload={"data": {"station": {"id": "42", "name": "  Backyard "}}}))
    assert (await c.get_station("42"))["name"] == "Backyard"
    c = _client(_Resp(payload={"data": {"station": None}}))
    assert await c.get_station("42") is None


# ---- _parse_image_credit --------------------------------------------------- #


def test_parse_image_credit_extracts_text_and_href() -> None:
    raw = '<a href="//commons.wikimedia.org/wiki/User:Foo">Foo</a>'
    text, url = _parse_image_credit(raw)
    assert text == "Foo"
    assert url == "https://commons.wikimedia.org/wiki/User:Foo"  # protocol-relative fixed


def test_parse_image_credit_strips_tags_unescapes() -> None:
    text, url = _parse_image_credit("Jane &amp; John")
    assert text == "Jane & John"
    assert url is None


def test_parse_image_credit_empty() -> None:
    assert _parse_image_credit(None) == (None, None)
    assert _parse_image_credit("") == (None, None)


# ---- _species_attribution -------------------------------------------------- #


def test_species_attribution_maps_fields() -> None:
    sp = {
        "imageCredit": '<a href="https://x.test/u">Pat</a>',
        "imageLicense": "CC BY-SA 4.0",
        "imageLicenseUrl": "https://creativecommons.org/x",
    }
    out = _species_attribution(sp)
    assert out == {
        "image_credit": "Pat",
        "image_credit_url": "https://x.test/u",
        "image_license": "CC BY-SA 4.0",
        "image_license_url": "https://creativecommons.org/x",
    }


# ---- _clean_station -------------------------------------------------------- #


def test_clean_station_name_fallback() -> None:
    out = _clean_station({"id": "7", "name": "   "})
    assert out["name"] == "Station 7"


def test_clean_station_passes_through() -> None:
    node = {"id": "7", "name": "Yard", "type": "puc", "country": "US",
            "state": "MN", "coords": {"lat": 1, "lon": 2}, "latestDetectionAt": "t"}
    out = _clean_station(node)
    assert out["type"] == "puc"
    assert out["coords"] == {"lat": 1, "lon": 2}
    assert out["latest_detection_at"] == "t"


# ---- _normalise_detection (singular) --------------------------------------- #


def test_normalise_detection_maps_species_and_extras() -> None:
    node = {
        "species": {
            "commonName": "American Robin", "scientificName": "Turdus migratorius",
            "ebirdCode": "amerob", "imageUrl": "i.jpg", "thumbnailUrl": "t.jpg",
            "ebirdUrl": "e", "wikipediaUrl": "w", "imageCredit": "<a href='x'>Cred</a>",
        },
        "timestamp": "2026-06-01T12:00:00Z",
        "confidence": 0.9, "score": 1, "certainty": "likely",
        "soundscape": {"url": "s.mp3"},
    }
    out = _normalise_detection(node)
    assert out["species"] == "American Robin"
    assert out["sp_code"] == "amerob"
    assert out["audio_url"] == "s.mp3"
    assert out["confidence"] == 0.9
    assert out["image_credit"] == "Cred"


def test_normalise_detection_handles_missing_species() -> None:
    out = _normalise_detection({"timestamp": "t"})
    assert out["species"] is None
    assert out["audio_url"] is None


# ---- _haversine_km --------------------------------------------------------- #


def test_haversine_zero_distance() -> None:
    assert _haversine_km(45.0, -93.0, 45.0, -93.0) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_distance() -> None:
    # ~1 deg of latitude is ~111 km.
    assert _haversine_km(45.0, -93.0, 46.0, -93.0) == pytest.approx(111.2, abs=1.0)
