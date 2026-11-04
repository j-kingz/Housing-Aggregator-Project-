"""Check the email (SMTP) settings from the command line.

    python -m app.email_check you@example.com

Sends a short test message using the SMTP_* and MAIL_SENDER values in .env.
"""

import sys

from app.email import EmailDeliveryError, email_configured, send_test_email
from config import Config


def main(argv):
    config = {key: getattr(Config, key) for key in dir(Config) if key.isupper()}
    if len(argv) < 2:
        print(__doc__)
        return 1
    if not email_configured(config):
        print("SMTP_HOST and MAIL_SENDER must be set in .env first (see .env.example).")
        return 1
    try:
        send_test_email(argv[1], config)
    except EmailDeliveryError as exc:
        print(f"FAILED: {exc}")
        return 1
    print(f"Test email sent to {argv[1]} through {config['SMTP_HOST']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
