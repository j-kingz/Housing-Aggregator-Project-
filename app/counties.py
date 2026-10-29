"""The 47 counties of Kenya with the GPS point of their main town.

Used by the location suggestions so a person can start from a county and then
narrow down to a neighbourhood inside it, and by the search to find every
listing in a county. The points are approximate (the county headquarters).
"""

# name, latitude, longitude
COUNTIES = [
    ("Mombasa", -4.0435, 39.6682), ("Kwale", -4.1816, 39.4606), ("Kilifi", -3.5107, 39.9093),
    ("Tana River", -1.5000, 40.0300), ("Lamu", -2.2717, 40.9020), ("Taita-Taveta", -3.3160, 38.4840),
    ("Garissa", -0.4532, 39.6461), ("Wajir", 1.7471, 40.0573), ("Mandera", 3.9366, 41.8670),
    ("Marsabit", 2.3284, 37.9899), ("Isiolo", 0.3546, 37.5822), ("Meru", 0.0470, 37.6490),
    ("Tharaka-Nithi", -0.2965, 37.8750), ("Embu", -0.5389, 37.4596), ("Kitui", -1.3670, 38.0106),
    ("Machakos", -1.5177, 37.2634), ("Makueni", -1.8040, 37.6200), ("Nyandarua", -0.1800, 36.5230),
    ("Nyeri", -0.4197, 36.9510), ("Kirinyaga", -0.4990, 37.2800), ("Murang'a", -0.7210, 37.1520),
    ("Kiambu", -1.1714, 36.8356), ("Turkana", 3.1190, 35.5970), ("West Pokot", 1.2390, 35.1190),
    ("Samburu", 1.1000, 36.7000), ("Trans-Nzoia", 1.0150, 34.9500), ("Uasin Gishu", 0.5143, 35.2698),
    ("Elgeyo-Marakwet", 0.5170, 35.5200), ("Nandi", 0.2000, 35.1000), ("Baringo", 0.4919, 35.7430),
    ("Laikipia", 0.3000, 36.8000), ("Nakuru", -0.3031, 36.0800), ("Narok", -1.0780, 35.8600),
    ("Kajiado", -1.8520, 36.7820), ("Kericho", -0.3689, 35.2863), ("Bomet", -0.7813, 35.3416),
    ("Kakamega", 0.2827, 34.7519), ("Vihiga", 0.0500, 34.7200), ("Bungoma", 0.5635, 34.5606),
    ("Busia", 0.4608, 34.1115), ("Siaya", 0.0600, 34.2880), ("Kisumu", -0.0917, 34.7680),
    ("Homa Bay", -0.5273, 34.4571), ("Migori", -1.0634, 34.4731), ("Kisii", -0.6817, 34.7667),
    ("Nyamira", -0.5633, 34.9358), ("Nairobi", -1.2864, 36.8172),
]

BY_NAME = {name.lower(): (name, lat, lng) for name, lat, lng in COUNTIES}


def find_county(text):
    """The county whose name is exactly `text` (ignoring case and a trailing "County")."""
    q = " ".join(str(text or "").lower().split())
    if q.endswith(" county"):
        q = q[: -len(" county")]
    return BY_NAME.get(q)
