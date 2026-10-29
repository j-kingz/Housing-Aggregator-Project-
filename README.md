# Housing Aggregator

**A web-based housing aggregator and price analytics platform for urban renters, built with data scraping.**
IT Project II, Strathmore University (BBIT). Justin Ngunjiri Macharia (158787), supervised by Mr. Wallace Muchiri.

Finding a rental in Nairobi means checking many websites, and none of them tell you whether the rent is fair.
This project gathers public listings into one database, shows exactly which unit is vacant and where it is,
compares each rent with its neighbourhood, and helps a renter work out what they can afford.

**Open the site at http://127.0.0.1:5000** once it is running (see "Running it").

## What it does

| For | What you get |
|-----|--------------|
| **Renters** | Search any place in Kenya: the Where box suggests counties first, then the neighbourhoods inside them, then buildings and places (like a map search) and fixes typing mistakes. Every result shows building, floor, unit and whether it is vacant. A map shows every matching home, and a Vacant only tab lists the free ones. If a unit is not confirmed, the page sends you to the original advert to reach the agent. Hearts save homes to a Saved homes page. A "fair price" label compares each rent with the area. **What can I afford?** ranks homes from your income, where you want to live and where you work, and shows how far each is on a map. Saved searches notify you of new matches. A vacant unit can be reserved with an **M-Pesa** deposit. |
| **Landlords** | Add units with building, floor, room, vacancy and an exact GPS point (use the phone's location, search a place or click the map). See deposits paid for their units. |
| **Administrators** | Turn scraping sources on and off, run a scrape, read the history of every run, manage users and listings. |

### The scraper

| Website | Status (checked 29 Oct 2026) |
|---------|------------------------------|
| Property24 | Works. About 21 adverts a page. Many adverts include an exact GPS point. |
| Jiji | Works. About 20 adverts a page. |
| PigiaMe | Works. About 10 apartments a page. |
| BuyRentKenya | **Blocked.** Its Cloudflare protection returns 403 to automated requests, and the scraper does not try to get around it. |

It checks `robots.txt` before requesting anything, waits between requests, retries failures politely, and logs every run. Nothing is merged or dropped as a "duplicate": two units in the same building stay two listings. The scraper only recognises the same advert from the same site so it can refresh it instead of adding a copy. Photos are shown from the original site (not copied) and every listing links back to its source.

## Running it

You need Python 3.10 or newer and MySQL Server running locally.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then edit .env: set SECRET_KEY and DB_PASSWORD
python init_db.py             # creates the database, tables and seed data
python -m scraper.cli run     # fetch listings from the websites (takes a few minutes)
python create_admin.py        # optional: make an administrator account
python run.py                 # start the site
```

Then open **http://127.0.0.1:5000**. On Windows you can also double-click `start.bat`.

Only real listings are used: scraped from the websites above, or added by landlords. There is no demo data.

### Docker

```powershell
docker compose up --build
```

Starts MySQL, the website (http://127.0.0.1:5000) and the scraper worker as three separate containers, so a long scrape never slows the site down. Tested on 29 Oct 2026 from an empty volume: all three containers came up healthy and the worker collected 308 listings on its own. MySQL is reachable from your computer on port 3307. Stop it with `docker compose down`.

### Optional: Google Maps and M-Pesa

Both are set in `.env` (see `.env.example`). The site works without either.

- **Google Maps:** put a key in `GOOGLE_MAPS_API_KEY` (enable "Maps JavaScript API" and "Places API (New)", and restrict the key to your local address). It adds Google place suggestions to the search boxes. Without it the site still suggests every county, neighbourhood and building from its own data, and other places across Kenya from OpenStreetMap (Photon, a free service, so it needs internet), and shows OpenStreetMap maps.
- **M-Pesa:** register at https://developer.safaricom.co.ke and fill in the `MPESA_*` values. Safaricom must be able to reach your callback, so run a tunnel such as ngrok and set `MPESA_CALLBACK_BASE_URL`. With no keys the payment flow runs in a clearly labelled **demo mode** where no money moves.

## Where the data is stored

Everything is in the MySQL database `housing_aggregator_db` (open it in MySQL Workbench).

| Table | Contents |
|-------|----------|
| `scraping_source` | The websites the scraper reads, their settings and last run |
| `properties` | **Every listing**, scraped or added by a landlord (rent, building, floor, unit, vacancy, GPS, photo link, source) |
| `scraping_run` | The history of each scrape: pages read, listings found, new, errors |
| `area` | Neighbourhoods with their centre points |
| `user`, `renter_details`, `landlord_details`, `role` | Accounts (passwords are stored hashed) |
| `search_alert`, `notification` | Saved searches and the messages they produce |
| `payment` | M-Pesa deposits |
| `favorite` | Homes people saved with the heart |
| `market_snapshot` | Daily average rents, used for trends |

In the website, administrators see the same data under **Admin**: Sources, Listings and Scraping runs. Example query: `SELECT source_name, COUNT(*) FROM properties GROUP BY source_name;`

## Tests

```powershell
python -m pytest
```

182 tests run on a temporary in-memory database, so your real data is never touched. They cover accounts, listings, search, the scraper and cleaner, analytics, recommendations, notifications, GPS decoding and M-Pesa (including forged callbacks). See `docs/TESTING.md`. A guide for presenting the project is in `docs/PRESENTATION.md`.

## Scope

In scope and built: scraping, analytics, personalised insights, notifications, M-Pesa reservation deposits, Docker deployment.

Out of scope for this version:
- **Password reset by email.** It needs an email service. Accounts can be deactivated by an administrator.
- **Hosting photos.** Listing photos are linked from the source site and hidden if that site stops serving them. They are never copied.
- **Lease agreements and rent collection.** The platform only takes a reservation deposit and links to the original advert.

## Folder layout

```
app/
  models.py        all database tables
  migrations.py    adds new columns to an existing database
  seed_data.py     neighbourhoods and the default scraping sources
  geo.py           GPS helpers (Plus Codes, geocoding)
  places/          place suggestions and typo correction
  main/            search page, how-it-works page, profile
  listings/        add/edit units, listing and building pages
  analytics/       price dashboard, area benchmarks, fair-price verdict
  insights/        "What can I afford?" recommendations
  notifications/   saved searches and the inbox
  payments/        M-Pesa (Daraja) deposits
  admin/           users, listings, sources, scraping runs
  templates/, static/   pages, styles and the JavaScript for suggestions and maps
scraper/
  robots_checker.py  reads and obeys robots.txt
  fetcher.py         polite, throttled requests with retries
  parser.py          one profile per website, plus a fallback
  cleaner.py         turns raw text into clean numbers
  scraper.py         runs a source and stores the results
  cli.py, worker.py  command line and the container's background worker
tests/             pytest suite
docs/              TESTING.md, DEPLOYMENT.md, PRESENTATION.md
```

## Ethics

Only public listing pages are read. `robots.txt` is obeyed, requests are spaced out, and a site that blocks automated access is left alone. The data is used only for this academic project and is never sold.
