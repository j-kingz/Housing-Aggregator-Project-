# Presenting the Housing Aggregator

A guide for the lecturer demo. Open the site at **http://127.0.0.1:5000**.

## The one-minute pitch

Renters in Nairobi search across many websites and cannot tell if a rent is fair or which unit is actually free.
This platform **collects** listings from several sites, **cleans** them into one database, **analyses** prices by
neighbourhood, and **personalises** the result to the renter's income and workplace. It also lets them **reserve**
a vacant unit with M-Pesa.

## How it works

```
 websites  -->  scraper  -->  cleaner  -->  MySQL database  -->  website  -->  renter
 (Property24,   (robots.txt,   (rent, beds,  (properties,        (search,       (search, afford,
  Jiji,          delays,        GPS, unit,    areas, runs,        analytics,     alerts, M-Pesa)
  PigiaMe)       retries)       vacancy)      payments)           insights)
```

1. **Scraper** (`scraper/`): checks `robots.txt`, waits between requests, reads each site with its own profile.
2. **Cleaner**: turns "KSh 28,000", "1bdrm", "110 m²" into numbers, converts dollar adverts, reads GPS from Plus Codes.
3. **Database**: one `properties` table holds every unit with building, floor, unit number, vacancy and GPS.
4. **Analytics**: average rent per neighbourhood; each listing is labelled cheap, fair or expensive (needs 3+ homes in the area).
5. **Insights**: "What can I afford?" ranks homes by rent + travel cost against income (30% comfortable, 40% stretch).
6. **Notifications**: a saved search creates a message when the scraper finds a match.
7. **Payments**: M-Pesa STK push for a reservation deposit; the unit becomes "Reserved".

## Demo script (about 8 minutes)

1. **Home** `/`: point out the counts, the photos, and the building / floor / unit / vacant strip on each card.
2. **Suggestions**: type `westlnds` in Neighbourhood. It suggests Westlands and corrects the typo. Type `river` in Where to see buildings.
3. **A listing**: open one. Show the map and GPS ("Exact point" or "Approximate"), the fair-price label, "See the original listing".
4. **Building page**: from a unit with a building, open the building to see floors and which units are vacant.
5. **Rent prices** `/analytics/`: charts by neighbourhood, bedrooms and trend.
6. **Register as a renter**, open **What can I afford?**: enter income 90000, a neighbourhood and your workplace. Show the ranked homes, the reasons and the real monthly cost.
7. **Reserve with M-Pesa** on a vacant unit. In demo mode a banner says no money moves, and the payment confirms after a few seconds.
8. **Admin** (run `python create_admin.py` first): Sources (turn a site on or off), "Run now", **Scraping runs** history, Listings.
9. **Landlord**: add a listing, press "Use my current location".

## Questions you may be asked

- **Is scraping legal / ethical?** Only public pages. robots.txt is obeyed, delays are used, and a site that blocks bots (BuyRentKenya) is left alone. Every listing links back to its source.
- **Why only three websites?** Each site needs its own parsing profile. BuyRentKenya is blocked by Cloudflare. More can be added from the admin page plus one profile in `scraper/parser.py`.
- **How do you handle duplicates?** Listings are never merged, so units in one building stay separate. Only the same advert from the same site is refreshed.
- **How accurate is the GPS?** Exact when an advert gives a Plus Code or a landlord sets it; otherwise it is the neighbourhood centre and is labelled "approximate".
- **How is "fair price" decided?** Compared with the neighbourhood average, cheap/expensive beyond a threshold; it says "not enough data" below 3 homes.
- **Are the travel costs exact?** No. They are estimates from typical fares and speeds, and the interface says so.
- **Is M-Pesa real?** The Daraja STK push, callback (secured with a secret token and amount check) and status query are implemented. Without Safaricom keys it runs in demo mode.
- **What about security?** Passwords are hashed (scrypt), forms have CSRF protection, role checks protect pages, and `.env` secrets are not in the repository.
- **What are the limits?** Listings are only as good as the source sites. Some adverts have no unit number. BuyRentKenya is not readable. No password-reset email.
- **Demo data:** the "Sample fixture" listings are bundled demo data. Filter by Source to show only real scraped sites.

## Before you present

1. Start MySQL, run `python init_db.py`, then `python -m scraper.cli run` for fresh listings.
2. `python run.py`, open http://127.0.0.1:5000.
3. Have an account ready for each role (renter, landlord, admin).
4. If the internet is unavailable, the site still works with the stored listings (maps need internet).
