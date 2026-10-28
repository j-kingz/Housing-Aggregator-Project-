"""One-off generator for the bundled sample listings page.

Run it with:  python scraper/fixtures/build_sample.py
It writes nairobi_listings.html which is the sample page the scraper reads
when it is not pointed at a live site.
"""

import random
from pathlib import Path

random.seed(20260615)

OUT = Path(__file__).parent / "nairobi_listings.html"

# (area, city, title prefix, bedrooms, bathrooms, low rent, high rent, sqft range)
AREAS = [
    ("Westlands", "Nairobi", "Modern", 1, 1, 45000, 70000, (450, 700)),
    ("Westlands", "Nairobi", "Executive", 2, 2, 85000, 140000, (900, 1400)),
    ("Westlands", "Nairobi", "Premium", 3, 3, 150000, 260000, (1400, 2200)),
    ("Kilimani", "Nairobi", "Bright", 2, 2, 70000, 120000, (850, 1300)),
    ("Kilimani", "Nairobi", "Cozy", 1, 1, 40000, 60000, (400, 620)),
    ("Parklands", "Nairobi", "Spacious", 2, 2, 55000, 90000, (750, 1100)),
    ("Parklands", "Nairobi", "Affordable", 1, 1, 35000, 50000, (380, 560)),
    ("Lavington", "Nairobi", "Family", 3, 3, 120000, 200000, (1800, 2600)),
    ("Lavington", "Nairobi", "Executive", 4, 4, 200000, 350000, (2600, 4000)),
    ("Upper Hill", "Nairobi", "Quiet", 2, 2, 60000, 100000, (800, 1200)),
    ("Riverside", "Nairobi", "Corporate", 1, 1, 45000, 65000, (450, 700)),
    ("Riverside", "Nairobi", "Waterfront", 2, 2, 85000, 130000, (950, 1500)),
    ("Kileleshwa", "Nairobi", "Compact", 1, 1, 30000, 45000, (350, 520)),
    ("Dagoretti", "Nairobi", "Affordable", 2, 1, 30000, 45000, (600, 850)),
    ("Dagoretti", "Nairobi", "Studio", 0, 1, 18000, 26000, (250, 380)),
    ("South B", "Nairobi", "Gated", 2, 2, 40000, 65000, (700, 950)),
    ("South B", "Nairobi", "Affordable", 1, 1, 25000, 40000, (330, 480)),
    ("South C", "Nairobi", "Family", 2, 2, 45000, 70000, (750, 1000)),
    ("Ngong", "Nairobi", "Garden", 3, 2, 60000, 120000, (1500, 2200)),
    ("Karen", "Nairobi", "Luxury", 4, 4, 250000, 450000, (3200, 5200)),
    ("Karen", "Nairobi", "Servant", 3, 3, 150000, 250000, (2400, 3400)),
    ("Sameer", "Nairobi", "Affordable", 1, 1, 20000, 30000, (300, 450)),
    ("Mombasa Road", "Nairobi", "Transit", 2, 1, 35000, 55000, (620, 880)),
    ("Industrial Area", "Nairobi", "Commercial", 1, 1, 18000, 28000, (280, 420)),
    ("Embakasi", "Nairobi", "Airport", 2, 2, 30000, 45000, (600, 850)),
    ("Umoja", "Nairobi", "Family", 2, 2, 35000, 55000, (650, 900)),
    ("Huruma", "Nairobi", "Affordable", 1, 1, 22000, 35000, (320, 470)),
    ("Ruaraka", "Nairobi", "Estate", 2, 2, 30000, 45000, (600, 820)),
    ("Kasarani", "Nairobi", "Estate", 3, 2, 45000, 70000, (950, 1400)),
    ("Eastleigh", "Nairobi", "Commercial", 1, 1, 15000, 25000, (260, 400)),
    ("Buruburu", "Nairobi", "Estate", 2, 2, 25000, 40000, (580, 800)),
    ("Kikuyu", "Nairobi", "Green", 1, 1, 25000, 40000, (350, 520)),
    ("Kariobangi", "Nairobi", "Affordable", 1, 1, 18000, 28000, (280, 430)),
    ("Nairobi CBD", "Nairobi", "City", 1, 1, 30000, 50000, (350, 540)),
    ("Milimani", "Nairobi", "Parkside", 2, 2, 70000, 110000, (900, 1300)),
    ("Tena Estate", "Nairobi", "Affordable", 1, 1, 20000, 30000, (300, 460)),
    ("Nakuru Town", "Nakuru", "Lakeside", 2, 2, 30000, 45000, (650, 900)),
    ("Nakuru Town", "Nakuru", "Affordable", 1, 1, 18000, 28000, (320, 470)),
    ("Mombasa CBD", "Mombasa", "Coastal", 2, 2, 40000, 60000, (700, 1000)),
    ("Mombasa CBD", "Mombasa", "Studio", 0, 1, 22000, 32000, (280, 400)),
    ("Nyali", "Mombasa", "Beach", 3, 3, 85000, 130000, (1400, 2000)),
    ("Kisumu", "Kisumu", "Lakeside", 2, 2, 32000, 48000, (680, 950)),
    ("Thika", "Thika", "Industrial", 1, 1, 15000, 25000, (300, 440)),
    ("Kiambu", "Kiambu", "Green", 2, 2, 28000, 42000, (620, 880)),
    ("Limuru", "Limuru", "Commuter", 2, 2, 30000, 45000, (650, 900)),
    ("Ruiru", "Ruiru", "Affordable", 1, 1, 16000, 24000, (290, 420)),
]

AMENITIES = [
    "Water tank",
    "Borehole",
    "Prepaid electricity",
    "Parking",
    "Security guard",
    "Electric fence",
    "Furnished",
    "WiFi",
    "Gym",
    "Lift",
    "Balcony",
    "Backup water",
    "Master bedroom",
]

DESCRIPTIONS = [
    "Finished to a high standard with generous living spaces and plenty of natural light.",
    "Well maintained unit in a quiet neighbourhood with all the services close by.",
    "A great starter or investment home in an area with steady rental demand.",
    "Recently renovated with a modern kitchen, tiled floors and a secure balcony.",
    "Walking distance to shops, transport and schools, making it easy to commute.",
    "Bright and airy rooms with a shared compound that is kept clean and secure.",
]

CATEGORY_BY_BEDS = {0: "Bedsitter", 1: "Apartment", 2: "Apartment", 3: "Apartment", 4: "Maisonette"}


def format_price(amount):
    """Write some prices the way real sites write them."""
    roll = random.random()
    if roll < 0.15:
        return f"KSh {amount / 1000:.1f}k"
    if roll < 0.20:
        return f"KSh {amount:,}"
    if roll < 0.24:
        return f"KSh {amount:,} per month"
    return f"KSh {amount:,}"


FEATURES = [
    "Balcony",
    "Furnished",
    "Near the mall",
    "Quiet street",
    "Elevator building",
    "Garden access",
    "Backup water",
    "Fibre ready",
    "Recently painted",
    "Corner unit",
    "Top floor",
    "Ground floor",
    "Shared compound",
    "24 hour security",
]


def build():
    cards = []
    used_titles = set()

    for area, city, prefix, beds, baths, low, high, (sqft_low, sqft_high) in AREAS:
        count = random.randint(2, 4)
        for index in range(count):
            rent = random.randrange(low, high, 500)
            size = random.randrange(sqft_low, sqft_high, 10)
            feature = random.choice(FEATURES)

            # every so often a listing is copied across two sites, which is what
            # the de-duplication in the scraper is there to catch
            duplicate = random.random() < 0.06

            title = f"{prefix} {beds} Bedroom {'Maisonette' if beds >= 4 else 'Apartment'} in {area} with {feature.lower()}"
            if title in used_titles:
                title = (
                    f"{prefix} {beds} Bedroom Apartment {area} "
                    f"{feature.lower()} {index + 1}"
                )
            used_titles.add(title)

            amenities = random.sample(AMENITIES, random.randint(2, 5))
            description = random.choice(DESCRIPTIONS)

            cards.append(
                f"""  <div class="listing-card">
    <h2 class="listing-title">{title}</h2>
    <span class="price">{format_price(rent)}</span>
    <span class="bedrooms">{beds} Bedrooms</span>
    <span class="bathrooms">{baths} Bathrooms</span>
    <span class="location">{area}, {city}</span>
    <span class="size">{size} sqm</span>
    <p class="description">{description}</p>
    <ul class="amenities">"""
                + "".join(f"\n      <li>{item}</li>" for item in amenities)
                + f"""
    </ul>
    <a class="link" href="/listing/{abs(hash(title)) % 100000}">View listing</a>
  </div>"""
            )

            if duplicate:
                # the same flat advertised a second time with a slightly different title
                cards.append(
                    f"""  <div class="listing-card">
    <h2 class="listing-title">{prefix} {beds} Bedroom for rent at {area} {feature.lower()}</h2>
    <span class="price">KSh {rent:,}</span>
    <span class="bedrooms">{beds} Bedrooms</span>
    <span class="bathrooms">{baths} Bathrooms</span>
    <span class="location">{area}, {city}</span>
    <span class="size">{size} sqm</span>
    <p class="description">{description}</p>
  </div>"""
                )

    html = f"""<!doctype html>
<!-- Sample listings page. This is made up data used to demonstrate the
     platform without scraping a live site. Prices are realistic for the
     Nairobi rental market but the listings themselves are not real. -->
<html>
<head><title>Sample rental listings</title></head>
<body>
{chr(10).join(cards)}
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {len(cards)} sample listings to {OUT}")


if __name__ == "__main__":
    build()
