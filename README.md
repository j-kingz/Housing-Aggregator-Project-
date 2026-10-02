# Housing Aggregator Project

This is my IT Project II at Strathmore (BBIT). The full title is "A Web-Based Housing Aggregator and Price Analytics Platform for Urban Renters using Data Scraping Techniques".

The idea came from how annoying it is to look for a house in Nairobi. Listings are spread across BuyRentKenya, Property24, Facebook groups and agent websites, and none of them tell you if the rent you're looking at is actually fair for that area. So the plan is to pull public listings into one database, let people search them in one place, and later on show price comparisons per neighbourhood.

Justin Ngunjiri Macharia (158787), supervised by Mr. Wallace Muchiri.

## Where it's at

Right now the project is at about 40%. What works:

- Register and log in / log out. You pick whether you're a renter or a landlord when you sign up.
- Passwords are hashed with Werkzeug (scrypt) before they're saved, so the database never has the real password.
- Landlords can add, view, edit and delete their own listings (the CRUD part). They can't touch anyone else's.
- Anyone can search listings by area, max rent and number of bedrooms.
- Users can edit their profile. Renters can save a preferred area and budget, landlords can add a business name.
- The MySQL database follows the schema diagram in the drawio file, so you can open it in MySQL Workbench and see all the tables.
- All forms have CSRF protection (Flask-WTF).

Still to do: the real scraper (there's a starting version in `scraper/` that reads a sample HTML page), the price analytics dashboard, notifications for search alerts, the payment flow and the admin side.

## What I used

Python 3 with Flask for the backend, MySQL for the database (through SQLAlchemy and PyMySQL), and plain HTML templates with Bootstrap 5 for the frontend. BeautifulSoup is there for the scraper.

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

   This also adds the three roles (Renter, Landlord, Administrator). If you ever want to wipe it and start fresh, run `python init_db.py --reset`. It asks you to type `yes` first.

5. (Optional) Load a few sample listings so the search page isn't empty:

   ```powershell
   python -m scraper.scraper
   ```

6. Start the site:

   ```powershell
   python run.py
   ```

   Then go to http://127.0.0.1:5000. On Windows you can also just double-click `start.bat`.

## Seeing the database

Open MySQL Workbench, connect to your local server and look for `housing_aggregator_db`. The tables are:

| Table | What's in it |
|-------|--------------|
| `role` | Renter, Landlord, Administrator |
| `user` | Everyone who has registered. The `password` column only holds the hash |
| `renter_details` | Preferred area and budget for renters |
| `landlord_details` | Business name and verification status for landlords |
| `properties` | The listings, both landlord-added and scraped |
| `search_alert` | Saved searches (not used yet) |
| `notification` | Alerts sent to renters (not used yet) |
| `payment` | Payments (not used yet) |

A quick way to check the hashing is working:

```sql
SELECT email, password FROM housing_aggregator_db.user;
```

You should see something starting with `scrypt:` instead of the actual password.

## Folder layout

```
app/
  __init__.py        sets up Flask, the database and login
  models.py          all the tables
  auth/              register, login, logout
  main/              search page and profile
  listings/          add / edit / delete listings
  templates/         the HTML pages
  static/css/        a bit of extra styling
scraper/             scraper (work in progress)
config.py            reads settings from .env
init_db.py           creates the database
run.py               starts the server
```

The proposal document and the diagrams (use case, context, DFDs, ERD, schema, sequence and wireframe) are in the root of the repo as well.

## About the scraping

The scraper will only go after publicly available listings, and it checks a site's `robots.txt` before requesting anything (`scraper/robots_checker.py`). When it's pointed at real sites there'll be a delay between requests so it doesn't hammer anyone's server. The data is only for this academic project and won't be used commercially.
