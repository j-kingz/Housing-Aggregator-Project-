import pytest

from scraper.url_safety import UnsafeUrlError, validate_public_https_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/listings",
        "file:///C:/secret.txt",
        "https://localhost/listings",
        "https://127.0.0.1/listings",
        "https://user:password@example.com/listings",
    ],
)
def test_scraper_rejects_unsafe_urls(url):
    with pytest.raises(UnsafeUrlError):
        validate_public_https_url(url)


def test_scraper_accepts_public_https_url(monkeypatch):
    monkeypatch.setattr(
        "scraper.url_safety.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    assert validate_public_https_url("https://example.com/listings") == "https://example.com/listings"
