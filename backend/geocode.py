# -*- coding: utf-8 -*-
"""
Reverse geocoding: turn (lat, lng) into a human-readable place name.

Tries Google's Geocoding API first (much better street/neighborhood coverage
for this region) when GOOGLE_MAPS_API_KEY is configured, and falls back to
the free OpenStreetMap/Nominatim lookup otherwise or if the Google call
fails for any reason - so the feature keeps working even before the key is
set up, and never hard-fails the request if Google is briefly unavailable.
"""

import os
import re

import httpx

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

_HTTP_TIMEOUT = 6.0
_OSM_USER_AGENT = "suli-report-form-hackathon/1.0"

_CODE_LIKE_ROAD = re.compile(r"^[\d\s\-/]+$")


def _is_code_like_road(value):
    """Many roads in this region are only tagged with plot/block codes in
    OpenStreetMap (e.g. "102-7") instead of a real street name - not useful
    to show to a citizen reporting a problem."""
    return not value or bool(_CODE_LIKE_ROAD.match(value))


def _build_google_label(address_components):
    def find(*types):
        for c in address_components:
            if any(t in c.get("types", []) for t in types):
                return c.get("long_name")
        return None

    parts = []
    road = find("route")
    if road:
        parts.append(road)
    neighbourhood = find("neighborhood", "sublocality", "sublocality_level_1")
    if neighbourhood and neighbourhood != road:
        parts.append(neighbourhood)
    city = find("locality", "administrative_area_level_2")
    if city and city != neighbourhood:
        parts.append(city)
    if not parts:
        state = find("administrative_area_level_1")
        if state:
            parts.append(state)
    return "، ".join(parts) if parts else None


def _build_osm_label(addr):
    if not addr:
        return None
    parts = []
    road = addr.get("road")
    if road and not _is_code_like_road(road):
        parts.append(road)
    neighbourhood = (
        addr.get("neighbourhood") or addr.get("suburb") or addr.get("quarter") or addr.get("city_district")
    )
    if neighbourhood and neighbourhood != road:
        parts.append(neighbourhood)
    city = addr.get("city") or addr.get("town") or addr.get("village")
    if city and city != neighbourhood:
        parts.append(city)
    if not parts:
        county = addr.get("county")
        if county:
            parts.append(county)
    if not parts:
        state = addr.get("state")
        if state:
            parts.append(state)
    return "، ".join(parts) if parts else None


async def _geocode_google(lat, lng):
    if not GOOGLE_MAPS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            res = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "latlng": f"{lat},{lng}",
                    "key": GOOGLE_MAPS_API_KEY,
                    "language": "ar",
                },
            )
        data = res.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        return _build_google_label(data["results"][0].get("address_components", []))
    except Exception:
        return None


async def _geocode_osm(lat, lng):
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _OSM_USER_AGENT}) as client:
            res = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "format": "jsonv2",
                    "lat": lat,
                    "lon": lng,
                    "zoom": 17,
                    "addressdetails": 1,
                    "accept-language": "ckb,ar,en",
                },
            )
        data = res.json()
        return _build_osm_label(data.get("address")) or data.get("display_name")
    except Exception:
        return None


async def reverse_geocode(lat, lng):
    """Returns (label, source) - source is "google" or "osm", or (None, None)
    if neither could resolve an address for this point."""
    label = await _geocode_google(lat, lng)
    if label:
        return label, "google"
    label = await _geocode_osm(lat, lng)
    if label:
        return label, "osm"
    return None, None
