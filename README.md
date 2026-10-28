# Housing Aggregator Project

This is my IT Project II at Strathmore (BBIT). The full title is "A Web-Based Housing Aggregator and Price Analytics Platform for Urban Renters using Data Scraping Techniques".

The idea came from how annoying it is to look for a house in Nairobi. Listings are spread across BuyRentKenya, Property24, Facebook groups and agent websites, and none of them tell you if the rent you're looking at is actually fair for that area. So the plan is to pull public listings into one database, let people search them in one place, and show price comparisons per neighbourhood.

Justin Ngunjiri Macharia (158787), supervised by Mr. Wallace Muchiri.

## Where it's at

The project now covers the Level 2 chapters of the proposal: data collection (scraping), the analytics engine, personalised insights, notifications and containerised deployment. What works:

**Accounts and CRUD**

- Register and log in / log out. You pick whether you're a renter or a landlord when you sign up.
- Passwords are hashed with Werkzeug (scrypt) before they're saved, so the database never has the real password.
- Landlords can add, view, edit and delete their own listings. They can't touch anyone else's.
- Users can edit their profile. Renters can save a preferred area, budget and commute settings, landlords can add a business name.
- Admins can see a quick overview, deactivate or reactivate accounts, verify landlords and remove any listing.
- All forms have CSRF protection (Flask-WTF).

**Scraping (proposal chapter 3.3)**

- A working scraper in `scraper/` that reads public listing pages, cleans the data and stores it.
- It checks each site's `robots.txt` before requesting anything, and stops if the site asks it not to crawl that path.
- Requests are throttled with a delay plus random jitter, and failed requests are retried with a backoff instead of killing the run.
- Each source is parsed with its own profile (BuyRentKenya, Property24) and falls back to a generic profile that reads any card-like block of HTML.
- Listings are de-duplicated on a fingerprint of the URL or the title, so the same flat is not stored twice.
- Every run is written to the `scraping_run` table: how many pages were read, how many listings were found, how many were new, and any errors.
- Admin pages let you turn sources on and off, run one on demand and read the history of past runs.

**Analytics (proposal chapter 3.4)**

- A dashboard with the headline numbers: how many listings, how many areas, the average and median rent.
- Price trends grouped by month so you can see whether rents are going up or down.
- Price breakdown by neighbourhood, by bedroom count and by property category.
- A fair-price verdict on every listing: it compares the rent against the neighbourhood average and says whether the place is cheap, fair or expensive, and how confident it is.
- Comparisons need at least three listings in the same area, otherwise the platform says it does not know rather than comparing against noise.

**Personalised insights (proposal chapter 3.5)**

- A personalised page for every renter built from their saved preferences.
- It finds the listings that fit the budget, shows how the rent compares to the area average, and lists the amenities renters look for the most in that area.
- It suggests a sensible rent ceiling based on what is actually available, and shows the areas where a renter is most likely to find something.

**Notifications (proposal chapter 3.6)**

- Renters can save a search alert: area, maximum price, minimum bedrooms and bathrooms.
- When the scraper finds a new listing that matches an alert, a notification is created for that renter.
- The same listing is never announced to the same renter twice.
- A bell in the navbar shows the unread count, and there is a notifications page with read and unread messages.

**Deployment (proposal chapter 3.7)**

- `Dockerfile` and `docker-compose.yml` run the site, the MySQL database and the scraper as separate containers.
- The scraper runs in its own container on a timer, so a long scrape can never slow the site down.

Still to do: the payment flow (the `payment` table is there as a placeholder, but the proposal scopes financial transactions out of this build), a password reset email, and images for the listings.

## What I used

Python 3 with Flask for the backend, MySQL for the database (through SQLAlchemy and PyMySQL), and plain HTML templates with Bootstrap 5 for the frontend. BeautifulSoup and Requests are used for the scraper. Pytest for the tests.

## Running it on your machine

You need Python 3.10 or newer and MySQL Server running locally.

1. Clone the repo and open the folder in a terminal.

2. Make a virtual environment and install everything:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your MySQL username and password, plus a random `SECRET_KEY`. The `.env` file is in `.gitignore` so it won't get pushed.

4. Create the database and tables:

   ```powershell
   python init_db.py
   ```

   This also adds the three roles (Renter, Landlord, Administrator), the Nairobi neighbourhood list and the default scraping sources. The command is safe to run on an existing database: missing tables and columns are added and nothing already stored is lost. If you ever want to wipe it and start fresh, run `python init_db.py --reset`. It asks you to type `yes` first.

5. (Optional) Load the bundled sample listings so the search page isn't empty:

   ```powershell
   python -m scraper.cli import-fixture
   ```

6. (Optional) Make an admin account. You can't sign up as an admin on the website, so it's done from the terminal:

   ```powershell
   python create_admin.py
   ```

   It asks for a name, email and password. After logging in with that account you'll see an **Admin** tab in the navbar.

7. Start the site:

   ```powershell
   python run.py
   ```

   Then go to http://127.0.0.1:5000. On Windows you can also just double-click `start.bat`.

## Running it in Docker

```powershell
docker compose up --build
```

That starts MySQL, the web server on http://127.0.0.1:5000 and the scraper worker. The web container runs `init_db.py` first, so the tables are created on the first start.

To run the scraper once instead of leaving the worker running:

```powershell
docker compose run --rm scraper
```

Put your own password in a `.env` file next to `docker-compose.yml` (`SECRET_KEY`, `DB_PASSWORD`) so the compose file picks it up.

## The scraper from the terminal

```powershell
python -m scraper.cli sources              # list the registered sources
python -m scraper.cli run                   # run every enabled source once
python -m scraper.cli run --source property24
python -m scraper.cli import-fixture        # load the bundled sample listings
python -m scraper.cli match-notifications  # match existing listings to saved alerts
python -m scraper.cli areas                 # list the neighbourhoods
```

`python -m scraper.worker --every 30` runs the same thing on a timer; that is what the scraper container does.

## Seeing the database

Open MySQL Workbench, connect to your local server and look for `housing_aggregator_db`. The tables are:

| Table | What's in it |
|-------|--------------|
| `role` | Renter, Landlord, Administrator |
| `user` | Everyone who has registered. The `password` column only holds the hash |
| `renter_details` | Preferred area, budget and commute settings for renters |
| `landlord_details` | Business name and verification status for landlords |
| `properties` | The listings, both landlord-added and scraped |
| `area` | The neighbourhoods, with coordinates for the commute estimates |
| `search_alert` | Saved searches that drive the notifications |
| `notification` | Alerts sent to renters when a matching listing appears |
| `scraping_source` | The sites the scraper reads, and whether they are enabled |
| `scraping_run` | The history of every scrape: pages read, listings found, errors |
| `market_snapshot` | A daily copy of the average rent per area, used for the trends |
| `payment` | Payments (placeholder only, not built in this version) |

A quick way to check the hashing is working:

```sql
SELECT email, password FROM housing_aggregator_db.user;
```

You should see something starting with `scrypt:` instead of the actual password.

## Running the tests

```powershell
pip install -r requirements.txt
python -m pytest
```

The tests use a separate test database (`housing_aggregator_test`) and clean up after themselves. They cover the cleaner, the parsers, the analytics, the insights, the notifications and the main routes.

## Folder layout

```
app/
  __init__.py        sets up Flask, the database and login
  models.py          all the tables
  migrations.py      adds new columns to an existing database
  seed_data.py       the neighbourhood list and the default sources
  auth/              register, login, logout
  main/              search page and profile
  listings/          add / edit / delete listings, price verdict
  analytics/         the dashboard: summaries, trends, area benchmarks
  insights/          the personalised page for each renter
  notifications/     saved alerts, matching and the inbox
  admin/             admin overview, users, listings, sources and runs
  templates/         the HTML pages
  static/css/        a bit of extra styling
scraper/
  robots_checker.py  reads and obeys robots.txt
  fetcher.py         throttled requests with retries and pagination
  cleaner.py         turns raw text into clean, comparable numbers
  parser.py          the per-site profiles
  scraper.py         runs a source and stores the results
  cli.py             the command line entry points
  worker.py          the background worker used by the container
  fixtures/          the bundled sample page
tests/               pytest suite
config.py            reads settings from .env
init_db.py           creates the database
create_admin.py      makes an admin account
run.py               starts the server
Dockerfile           image for the web server and the scraper
docker-compose.yml   MySQL + web + scraper
```

The proposal document and the diagrams are kept outside the repo.

## About the scraping

The scraper only goes after publicly available listings. It checks a site's `robots.txt` before requesting anything and honours the crawl delay and the disallowed paths. Requests are spaced out so it doesn't hammer anyone's server, and it stops on a source that repeatedly fails instead of hammering it further. The data is only for this academic project and won't be used commercially.
