# Deployment and Operations

## Local development

1. Copy `.env.example` to `.env`.
2. Set `SECRET_KEY` and the MySQL connection values.
3. Create the schema and seed the lookup data:

   ```powershell
   .\venv\Scripts\python.exe init_db.py
   ```

4. Optionally load the bundled sample listings:

   ```powershell
   .\venv\Scripts\python.exe -m scraper.cli import-fixture
   ```

5. Start the web application:

   ```powershell
   .\venv\Scripts\python.exe run.py
   ```

The site is available at `http://127.0.0.1:5000`.

## Docker deployment

Create a `.env` file next to `docker-compose.yml` and set values that are
appropriate for the deployment. In particular, replace the example database
password and secret key.

Start the services with:

```powershell
docker compose up --build
```

The compose file runs three services:

- `db`: MySQL 8 with a persistent volume
- `web`: Flask application and database initialization
- `scraper`: background scraper worker

To run one scraper pass instead of the worker:

```powershell
docker compose run --rm scraper python -m scraper.cli run
```

## Operations checks

Before a demonstration or release:

1. Confirm the database health check is passing.
2. Open the home page and run a filtered search.
3. Open the analytics dashboard and confirm that charts render.
4. Log in as a renter and check the budget analyser and alerts.
5. Log in as an administrator and review scraping runs.
6. Confirm the scraper obeys `robots.txt` and records failures.
7. Review the latest source URLs and listing prices for invalid data.

Do not use the development fallback secret or the example database password
in a shared or production environment.
