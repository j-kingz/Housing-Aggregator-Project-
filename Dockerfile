# The Housing Aggregator
#
# Two images are built from this file:
#   web      - runs the Flask site
#   scraper  - runs the background scraping worker
#
# The proposal (3.7.4) asks for the background scraping routine to be kept
# away from the web server so a long scrape cannot slow the site down.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# mysqlclient style build tools are not needed, PyMySQL is pure python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["python", "run.py"]
