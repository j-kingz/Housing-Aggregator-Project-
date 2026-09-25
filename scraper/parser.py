"""
Turns raw listing-page HTML into a clean list of dictionaries.
Kept separate from scraper.py so the parsing logic can be unit-tested
on any HTML string, without needing a live network request or a database.
"""
import re
from bs4 import BeautifulSoup


def _extract_number(text):
    """Pulls the digits out of strings like 'KSh 28,000' or '2 Bedrooms'."""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_listings(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    listings = []

    for card in soup.select(".listing-card"):
        title = card.select_one(".listing-title").get_text(strip=True)
        price = _extract_number(card.select_one(".price").get_text())
        bedrooms = _extract_number(card.select_one(".bedrooms").get_text())
        bathrooms = _extract_number(card.select_one(".bathrooms").get_text())
        location_text = card.select_one(".location").get_text(strip=True)

        # "Kilimani, Nairobi" -> address="Kilimani", city="Nairobi"
        parts = [p.strip() for p in location_text.split(",")]
        address = parts[0] if parts else location_text
        city = parts[1] if len(parts) > 1 else parts[0]

        listings.append({
            "title": title,
            "rentamount": price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "category": "Apartment",
            "city": city,
            "address": address,
        })

    return listings
