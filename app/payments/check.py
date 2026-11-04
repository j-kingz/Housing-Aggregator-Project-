"""Check the M-Pesa (Daraja) settings from the command line.

    python -m app.payments.check                 # sign in only (gets an access token)
    python -m app.payments.check 0712345678      # also send a KSh 1 STK prompt to that phone

Uses the MPESA_* values from .env. In the sandbox no real money moves; use
Safaricom's sandbox test number 254708374149 or your own Safaricom line.
"""

import sys
import time

from app.payments import mpesa
from config import Config


def main(argv):
    config = {key: getattr(Config, key) for key in dir(Config) if key.isupper()}
    if mpesa.is_demo(config):
        print("MPESA_CONSUMER_KEY is empty, so the site runs in DEMO MODE (no request is sent).")
        print("Add MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET from your Daraja app to .env.")
        return 1

    print(f"Environment : {config.get('MPESA_ENV')}")
    print(f"Shortcode   : {mpesa._shortcode(config)}")
    print(f"Callback URL: {mpesa.callback_url(config)}")
    try:
        mpesa._access_token(config)
    except mpesa.MpesaError as exc:
        print(f"FAILED to get an access token: {exc}")
        print("Check MPESA_CONSUMER_KEY / MPESA_CONSUMER_SECRET and MPESA_ENV.")
        return 1
    print("Access token: OK")

    if len(argv) < 2:
        return 0
    phone = mpesa.normalise_phone(argv[1])
    if not phone:
        print(f"{argv[1]!r} is not a valid Safaricom number.")
        return 1
    try:
        result = mpesa.stk_push(config, phone, 1, reference="TEST", description="Test")
    except mpesa.MpesaError as exc:
        print(f"FAILED to send the STK prompt: {exc}")
        return 1
    print(f"STK prompt sent to {phone}. CheckoutRequestID: {result['checkout_request_id']}")
    print("Approve it on the phone; checking the result for up to 60 seconds...")
    for _ in range(12):
        time.sleep(5)
        try:
            outcome = mpesa.stk_query(config, result["checkout_request_id"])
        except mpesa.MpesaError as exc:
            print(f"  query failed: {exc}")
            continue
        if outcome is not None:
            print(f"Result {outcome['code']}: {outcome['description']}")
            return 0 if outcome["code"] == 0 else 1
        print("  still waiting for the phone...")
    print("No answer from the phone yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
