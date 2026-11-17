import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY is missing - check your .env file")

    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", 3306))
    DB_NAME = os.getenv("DB_NAME", "housing_aggregator_db")
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # ---- transactional email ----
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
    SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", 15))
    MAIL_SENDER = os.getenv("MAIL_SENDER", "")

    # ---- M-Pesa (Safaricom Daraja, STK push) ----
    # With no consumer key the platform runs in demo mode: the whole payment
    # flow works but no real request is sent and no money moves.
    MPESA_ENV = os.getenv("MPESA_ENV", "sandbox")  # sandbox or production
    MPESA_CONSUMER_KEY = os.getenv("MPESA_CONSUMER_KEY", "")
    MPESA_CONSUMER_SECRET = os.getenv("MPESA_CONSUMER_SECRET", "")
    MPESA_SHORTCODE = os.getenv("MPESA_SHORTCODE", "174379")  # Daraja sandbox shortcode
    MPESA_PASSKEY = os.getenv("MPESA_PASSKEY", "")
    # public https address Safaricom can reach, e.g. https://abc.ngrok-free.app
    MPESA_CALLBACK_BASE_URL = os.getenv("MPESA_CALLBACK_BASE_URL", "").rstrip("/")
    # share of the monthly rent taken as the reservation deposit
    MPESA_RESERVATION_PERCENT = float(os.getenv("MPESA_RESERVATION_PERCENT", 10))
    PREMIUM_SUBSCRIPTION_AMOUNT = int(os.getenv("PREMIUM_SUBSCRIPTION_AMOUNT", 500))
    PREMIUM_SUBSCRIPTION_DAYS = int(os.getenv("PREMIUM_SUBSCRIPTION_DAYS", 30))
    # hours a verifier has to report on a vacancy check before it is reassigned
    VERIFICATION_DEADLINE_HOURS = int(os.getenv("VERIFICATION_DEADLINE_HOURS", 24))
    # how many times an overdue check is handed to another verifier before it expires
    VERIFICATION_MAX_REASSIGNMENTS = int(os.getenv("VERIFICATION_MAX_REASSIGNMENTS", 2))

    # quote_plus so a password with @ or / in it doesn't break the url
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USER}:{quote_plus(DB_PASSWORD)}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # MySQL closes idle connections (wait_timeout); test each pooled connection
    # before use and recycle it early, instead of failing with "server has gone away"
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # set SESSION_COOKIE_SECURE=true once the site is served over https
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
