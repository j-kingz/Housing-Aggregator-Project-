"""Shared test fixtures.

The tests run against an in-memory SQLite database so they are quick and do
not touch the real MySQL server. The SECRET_KEY is set before the app is
imported so the tests also run on a machine with no .env file.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-the-test-suite")

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Area, Role, User  # noqa: E402
from config import Config  # noqa: E402

ROLES = ["Renter", "Landlord", "Administrator"]


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-secret-key-for-the-test-suite"
    # never talk to Safaricom or a mail server from the tests, whatever .env says
    MPESA_CONSUMER_KEY = ""
    MPESA_CONSUMER_SECRET = ""
    MPESA_CALLBACK_BASE_URL = ""
    SMTP_HOST = ""
    MAIL_SENDER = ""


@pytest.fixture(autouse=True)
def no_internet_place_lookup(monkeypatch):
    """The tests never call the OpenStreetMap place service."""
    from app.places import services

    monkeypatch.setattr(services, "external_places", lambda query, limit=5: [])


@pytest.fixture
def app():
    """A fresh application with an empty database."""
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        for name in ROLES:
            db.session.add(Role(name=name, description=f"{name} role"))
        db.session.commit()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def areas(app):
    """A small neighbourhood list."""
    rows = [
        Area(name="Westlands", city="Nairobi", latitude=-1.253600, longitude=36.757400),
        Area(name="Kilimani", city="Nairobi", latitude=-1.244000, longitude=36.747000),
        Area(name="South B", city="Nairobi", latitude=-1.373000, longitude=36.817000),
        Area(name="Mombasa CBD", city="Mombasa", latitude=-4.043500, longitude=39.668200),
    ]
    for row in rows:
        db.session.add(row)
    db.session.commit()
    return rows


def make_user(email, role_name, password="testing123"):
    """Create a user with the given role, and the details row that goes with it."""
    from app.models import LandlordDetails, RenterDetails

    role = Role.query.filter_by(name=role_name).first()
    user = User(firstname="Test", lastname=role_name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    if role_name == "Renter":
        db.session.add(RenterDetails(renter_id=user.user_id))
    elif role_name == "Landlord":
        db.session.add(LandlordDetails(landlord_id=user.user_id))

    db.session.commit()
    return user


@pytest.fixture
def renter(app):
    return make_user("renter@example.com", "Renter")


@pytest.fixture
def landlord(app):
    return make_user("landlord@example.com", "Landlord")


@pytest.fixture
def admin(app):
    return make_user("admin@example.com", "Administrator")


def login(client, email, password="testing123"):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=True
    )
