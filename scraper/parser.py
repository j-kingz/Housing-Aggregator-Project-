# Turns a listings page into a list of dicts that match the Property columns.
# Kept away from the database code so it can be tested on any HTML string.

import re

from bs4 import BeautifulSoup


def get_number(text):
    # "KSh 28,000" -> 28000, "2 Bedrooms" -> 2
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse_listings(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for card in soup.select(".listing-card"):
        try:
            title = card.select_one(".listing-title").get_text(strip=True)
            price = get_number(card.select_one(".price").get_text())
            bedrooms = get_number(card.select_one(".bedrooms").get_text())
            bathrooms = get_number(card.select_one(".bathrooms").get_text())
            location = card.select_one(".location").get_text(strip=True)
        except AttributeError:
            # a field is missing on this card - skip it instead of crashing the whole run
            print("Skipped a listing with missing fields")
            continue

        if not price:
            continue

        # "Kilimani, Nairobi" -> address "Kilimani", city "Nairobi"
        parts = [p.strip() for p in location.split(",")]
        address = parts[0]
        city = parts[-1]

        results.append({
            "title": title,
            "rentamount": price,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "category": "Apartment",
            "city": city,
            "address": address,
        })

    return results
