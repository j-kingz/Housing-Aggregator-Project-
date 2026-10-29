# Testing and Data-Quality Verification

## Automated tests

Install the project dependencies and run the complete suite:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

The tests cover:

- Authentication and role-based access
- Listing creation and ownership rules
- Search and analytics routes
- Budget and commute insights
- Saved alerts and notifications
- Scraper parsing, cleaning and de-duplication
- Scraping run history

## Scraper data-quality checks

The cleaner normalizes monthly rent values before they are stored. It handles
currency values with commas, spaced thousands, `k` and `M` suffixes, and daily
or weekly prices. Invalid records are skipped instead of being inserted.

Examples that must parse correctly include:

```text
KSh 28,000
KSh 500 000+
KSh 28.5k
KSh 1.2M
KSh 2,000 per day
```

The parser rejects or removes:

- Missing or non-positive prices
- Prices outside the database column range
- Titles that contain only a price
- `javascript:`, `data:` and fragment URLs

## Release verification

Before committing a release:

1. Run the full test suite.
2. Load a clean database using `init_db.py`.
3. Run the scraper against the live sources (`python -m scraper.cli run`).
4. Check the lowest and highest rents for obvious parsing errors.
5. Open `/`, `/analytics/`, and an area analysis page.
6. Confirm that no listing has a price-only title or unsafe source URL.
7. Record the test result and the commit identifier used for the demo.
