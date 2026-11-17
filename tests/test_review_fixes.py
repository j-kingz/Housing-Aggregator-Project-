"""Tests for the performance, reliability and security fixes."""

from datetime import timedelta

import pytest
import requests

from app.extensions import db
from app.models import Payment, PremiumSubscription, Property, VerificationRequest, utcnow
from scraper import fetcher as fetcher_module
from scraper.fetcher import FetchError, Fetcher
from tests.conftest import login, make_user
from tests.test_units import add_unit


# -- scraper retries ---------------------------------------------------------
class FakeResponse:
    def __init__(self, status, text="<html>ok</html>"):
        self.status_code = status
        self.text = text
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def quiet_fetcher(monkeypatch):
    monkeypatch.setattr(fetcher_module, "validate_request_url", lambda url: url)
    monkeypatch.setattr(fetcher_module.time, "sleep", lambda seconds: None)
    return Fetcher(delay=0, respect_robots=False, max_retries=2)


def test_a_temporary_server_error_is_retried(quiet_fetcher, monkeypatch):
    replies = [FakeResponse(503), FakeResponse(200)]
    monkeypatch.setattr(quiet_fetcher.session, "get", lambda *a, **k: replies.pop(0))
    assert quiet_fetcher.get("https://example.com/") == "<html>ok</html>"


def test_a_server_that_keeps_failing_gives_up(quiet_fetcher, monkeypatch):
    calls = []

    def always_500(*args, **kwargs):
        calls.append(1)
        return FakeResponse(500)

    monkeypatch.setattr(quiet_fetcher.session, "get", always_500)
    with pytest.raises(FetchError):
        quiet_fetcher.get("https://example.com/")
    assert len(calls) == 3  # first try plus two retries


def test_blocking_is_not_retried(quiet_fetcher, monkeypatch):
    calls = []

    def blocked(*args, **kwargs):
        calls.append(1)
        return FakeResponse(429)

    monkeypatch.setattr(quiet_fetcher.session, "get", blocked)
    with pytest.raises(FetchError):
        quiet_fetcher.get("https://example.com/")
    assert len(calls) == 1


# -- premium verifier load balancing ----------------------------------------
def _premium_renter(email, payment_id):
    renter = make_user(email, "Renter")
    db.session.add(Payment(payment_id=payment_id, renter_id=renter.user_id, amount=500,
                           purpose="premium_subscription", status="paid"))
    db.session.add(PremiumSubscription(renter_id=renter.user_id, payment_id=payment_id,
                                       starts_at=utcnow(),
                                       expires_at=utcnow() + timedelta(days=30)))
    db.session.commit()
    return renter


def _verifier(email):
    user = make_user(email, "Landlord")
    user.verifier_approved = True
    user.verifier_available = True
    db.session.commit()
    return user


def test_requests_go_to_the_least_busy_verifier(client, app):
    busy = _verifier("busy@example.com")
    free = _verifier("free@example.com")
    unit = add_unit()
    other = _premium_renter("other@example.com", 1)
    db.session.add(VerificationRequest(renter_id=other.user_id, listing_id=unit.listing_id,
                                       verifier_id=busy.user_id, status="assigned"))
    db.session.commit()

    renter = _premium_renter("renter@example.com", 2)
    login(client, renter.email)
    client.post(f"/premium/verify/{unit.listing_id}")

    mine = VerificationRequest.query.filter_by(renter_id=renter.user_id).one()
    assert mine.verifier_id == free.user_id


def test_completed_checks_do_not_count_as_busy(client, app):
    first = _verifier("first@example.com")
    _verifier("second@example.com")
    unit = add_unit()
    other = _premium_renter("other@example.com", 1)
    db.session.add(VerificationRequest(renter_id=other.user_id, listing_id=unit.listing_id,
                                       verifier_id=first.user_id, status="completed"))
    db.session.commit()

    renter = _premium_renter("renter@example.com", 2)
    login(client, renter.email)
    client.post(f"/premium/verify/{unit.listing_id}")

    mine = VerificationRequest.query.filter_by(renter_id=renter.user_id).one()
    assert mine.verifier_id == first.user_id


# -- admin listings page -----------------------------------------------------
def test_admin_listings_are_paginated(client, admin):
    for number in range(55):
        db.session.add(Property(title=f"Flat {number}", rentamount=20000, city="Nairobi"))
    db.session.commit()
    login(client, admin.email)

    first = client.get("/admin/listings").get_data(as_text=True)
    assert "Page 1 of 2" in first
    assert first.count("Remove this listing?") == 50

    second = client.get("/admin/listings?page=2").get_data(as_text=True)
    assert second.count("Remove this listing?") == 5


# -- security headers --------------------------------------------------------
def test_pages_send_security_headers(client):
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
