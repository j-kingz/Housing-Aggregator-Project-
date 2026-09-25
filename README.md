# Housing Aggregator and Price Analytics Platform

A web-based platform that brings scattered rental listings together in one place and
turns them into price insights for urban renters.

Final year Information Systems project — Strathmore University, BBIT.

## Built with

- **Python / Flask** — backend and routing
- **MySQL + SQLAlchemy** — data storage
- **Bootstrap 5 + Jinja2** — frontend
- **BeautifulSoup** — listing data extraction

## Running it locally

**First time only**

1. Create the virtual environment and install the dependencies:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your MySQL password.

3. Create the database and its tables:

   ```powershell
   python init_db.py
   ```

**Every time after that**

Double-click `start.bat`, or run:

```powershell
.\venv\Scripts\Activate.ps1
python run.py
```

Then open http://127.0.0.1:5000 in your browser. Press `Ctrl+C` in the terminal to stop.

## Project layout

| Path | Purpose |
|------|---------|
| `run.py` | Starts the development server |
| `init_db.py` | One-time database and table setup |
| `config.py` | Reads settings from `.env` |
| `app/models.py` | Database tables, mirroring the ERD |
| `app/auth/` | Registration, login and logout |
| `app/main/` | Listing search and the analytics dashboard |
| `app/templates/` | HTML pages |
| `scraper/` | Listing extraction engine (work in progress) |

## A note on scraping

The scraper only targets publicly available listings and checks each site's
`robots.txt` before requesting anything. Requests are deliberately spaced out so
target servers are not overloaded. Collected data is used solely for academic
analysis within this project.
