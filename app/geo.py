"""Small GPS helpers shared by the web app and the scraper.

* Plus Codes (Open Location Codes) such as "PQRR+9WG" are printed in the
  address of many Property24 adverts. They are real GPS points, so reading
  them gives a listing an exact location without any paid API.
* geocode() asks the Google Geocoding API for a place's coordinates when a
  GOOGLE_MAPS_API_KEY is configured.
"""

import math
import re

import requests

ALPHABET = "23456789CFGHJMPQRVWX"
# the size in degrees of one step of each pair of characters
PAIR_RESOLUTIONS = [20.0, 1.0, 0.05, 0.0025, 0.000125]
GRID_ROWS = 5
GRID_COLUMNS = 4

PLUS_CODE_RE = re.compile(
    r"\b([23456789CFGHJMPQRVWX]{2,8}\+[23456789CFGHJMPQRVWX]{2,3})\b", re.IGNORECASE
)


def _decode_digits(code):
    """Decode a full plus code into (latitude, longitude) of its centre."""
    digits = code.replace("+", "").upper()
    lat, lng = -90.0, -180.0
    size_lat = size_lng = PAIR_RESOLUTIONS[-1]

    for index in range(0, min(len(digits), 10), 2):
        res = PAIR_RESOLUTIONS[index // 2]
        lat += ALPHABET.index(digits[index]) * res
        lng += ALPHABET.index(digits[index + 1]) * res
        size_lat = size_lng = res

    # 11th digit refines the last pair on a 5 x 4 grid
    if len(digits) > 10:
        position = ALPHABET.index(digits[10])
        size_lat = PAIR_RESOLUTIONS[-1] / GRID_ROWS
        size_lng = PAIR_RESOLUTIONS[-1] / GRID_COLUMNS
        lat += (position // GRID_COLUMNS) * size_lat
        lng += (position % GRID_COLUMNS) * size_lng

    return lat + size_lat / 2, lng + size_lng / 2


def decode_plus_code(code, reference_lat=None, reference_lng=None):
    """GPS (lat, lng) for a plus code, or None.

    Short codes ("PQRR+9WG") leave out the first characters. They are
    completed from a nearby reference point such as the neighbourhood centre.
    """
    if not code:
        return None
    code = code.strip().upper()
    try:
        head, tail = code.split("+")
        if len(head) % 2 == 1 or len(head) > 8:
            return None

        if len(head) == 8:
            lat, lng = _decode_digits(code)
        else:
            if reference_lat is None or reference_lng is None:
                return None
            removed = 8 - len(head)
            lat_n = float(reference_lat) + 90.0
            lng_n = float(reference_lng) + 180.0
            prefix = ""
            for pair in range(removed // 2):
                res = PAIR_RESOLUTIONS[pair]
                lat_i = int(lat_n // res)
                lng_i = int(lng_n // res)
                prefix += ALPHABET[lat_i] + ALPHABET[lng_i]
                lat_n -= lat_i * res
                lng_n -= lng_i * res
            lat, lng = _decode_digits(prefix + head + "+" + tail)

            # the completed code may sit in the neighbouring block
            block = PAIR_RESOLUTIONS[removed // 2 - 1]
            if float(reference_lat) + block / 2 < lat:
                lat -= block
            elif float(reference_lat) - block / 2 > lat:
                lat += block
            if float(reference_lng) + block / 2 < lng:
                lng -= block
            elif float(reference_lng) - block / 2 > lng:
                lng += block
    except (ValueError, IndexError):
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 6), round(lng, 6)


def find_plus_code(text):
    """The first plus code written inside a block of text, or None."""
    if not text:
        return None
    match = PLUS_CODE_RE.search(text)
    return match.group(1).upper() if match else None


def distance_km(lat1, lng1, lat2, lng2):
    """Straight-line distance between two GPS points in kilometres."""
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lam = math.radians(float(lng2) - float(lng1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def geocode(query, api_key, region="ke", timeout=8):
    """Look an address up with the Google Geocoding API.

    Returns {"lat", "lng", "formatted"} or None when the key is missing, the
    place is unknown or the request fails.
    """
    if not api_key or not query:
        return None
    try:
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "region": region, "key": api_key},
            timeout=timeout,
        )
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if data.get("status") != "OK" or not data.get("results"):
        return None
    top = data["results"][0]
    location = top["geometry"]["location"]
    return {
        "lat": round(location["lat"], 6),
        "lng": round(location["lng"], 6),
        "formatted": top.get("formatted_address"),
    }
