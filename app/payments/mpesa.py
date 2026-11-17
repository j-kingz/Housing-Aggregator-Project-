"""M-Pesa (Safaricom Daraja) STK push.

The renter types their phone number, Safaricom sends a payment prompt to that
phone and the renter enters their M-Pesa PIN. Safaricom then calls our
callback URL with the result. If the callback cannot reach this machine (for
example when running on localhost) the status can also be asked for with the
STK query API, which is what the status page does.

With no MPESA_CONSUMER_KEY configured the module runs in DEMO MODE: nothing is
sent to Safaricom and the payment is confirmed locally after a few seconds.
"""

import base64
import hashlib
import hmac
import re
import time
from datetime import datetime

import requests

BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}
TIMEOUT = 20

# Safaricom result codes worth explaining in plain words
RESULT_MESSAGES = {
    0: "Payment received.",
    1: "The M-Pesa balance was not enough.",
    1001: "The phone is busy with another M-Pesa request. Try again in a moment.",
    1019: "The payment request expired.",
    1025: "The payment prompt could not be sent to the phone.",
    1032: "The payment was cancelled on the phone.",
    1037: "The phone did not answer the prompt in time.",
    2001: "The M-Pesa PIN was wrong.",
}


# Replies from the STK query API that mean "the customer has not finished yet",
# not a final result. Daraja sends ResultCode 4999 ("The transaction is still
# under processing") while the PIN prompt is still open on the phone; treating
# it as a failure marked payments failed seconds before the PIN was entered.
STILL_PROCESSING_CODES = {4999}
STILL_PROCESSING_ERRORS = {"500.001.1001"}


class MpesaError(Exception):
    """Raised when Safaricom could not be reached or refused the request."""


def is_demo(config):
    return not config.get("MPESA_CONSUMER_KEY")


def normalise_phone(raw):
    """Phone number in the 2547XXXXXXXX form Safaricom needs, or None."""
    digits = re.sub(r"[^\d]", "", str(raw or ""))
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        digits = "254" + digits
    if re.fullmatch(r"254(7|1)\d{8}", digits):
        return digits
    return None


def local_part(raw):
    """The 9 digits that follow +254 (e.g. 712345678), for the phone field."""
    phone = normalise_phone(raw)
    if phone:
        return phone[3:]
    return re.sub(r"[^\d]", "", str(raw or ""))[:10]


def callback_token(config):
    """Secret that must be in the callback URL so only Safaricom's call is accepted."""
    key = (config.get("SECRET_KEY") or "").encode()
    return hmac.new(key, b"mpesa-callback", hashlib.sha256).hexdigest()[:32]


# Daraja refuses a CallBackURL that is not a public https address. When none
# is configured (running on your own computer without a tunnel) this
# placeholder is sent instead; Safaricom's callback then goes nowhere and the
# status page finds the result with the STK query API.
PLACEHOLDER_CALLBACK_BASE = "https://example.com"

# Safaricom's published passkey for the sandbox test shortcode 174379
SANDBOX_SHORTCODE = "174379"
SANDBOX_PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"


def callback_url(config):
    base = (config.get("MPESA_CALLBACK_BASE_URL") or "").rstrip("/")
    if not base.startswith("https://"):
        base = PLACEHOLDER_CALLBACK_BASE
    return f"{base}/payments/mpesa/callback/{callback_token(config)}"


def _base(config):
    return BASE_URLS.get(config.get("MPESA_ENV"), BASE_URLS["sandbox"])


def _shortcode(config):
    return str(config.get("MPESA_SHORTCODE") or SANDBOX_SHORTCODE)


def _passkey(config):
    passkey = config.get("MPESA_PASSKEY") or ""
    if not passkey and config.get("MPESA_ENV", "sandbox") != "production":
        passkey = SANDBOX_PASSKEY
    return passkey


HEADERS = {"User-Agent": "HousingAggregator/1.0 (+python-requests)", "Accept": "application/json"}

# Daraja tokens last an hour. Asking for a new one on every call is slow and
# can get the computer blocked by Safaricom's firewall, so one is reused
# until shortly before it expires.
_token_cache = {}


def _blocked_message(response):
    if "incapsula" in response.text.lower() or response.status_code == 403:
        return ("Safaricom's firewall refused the request (HTTP 403). This is usually "
                "temporary after many requests in a short time; wait a few minutes and try again.")
    return f"Unexpected reply from Safaricom (HTTP {response.status_code})."


def _access_token(config, refresh=False):
    key = (_base(config), config["MPESA_CONSUMER_KEY"])
    cached = _token_cache.get(key)
    if cached and not refresh and cached[1] > time.time():
        return cached[0]
    try:
        response = requests.get(
            f"{_base(config)}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(config["MPESA_CONSUMER_KEY"], config["MPESA_CONSUMER_SECRET"]),
            headers=HEADERS,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise MpesaError(f"Could not sign in to M-Pesa: {exc}") from exc
    try:
        data = response.json()
        token = data["access_token"]
    except (KeyError, ValueError):
        if response.status_code in (400, 401):
            raise MpesaError("M-Pesa refused the consumer key or secret. Check them in .env.")
        raise MpesaError("Could not sign in to M-Pesa. " + _blocked_message(response))
    lifetime = int(data.get("expires_in") or 3599)
    _token_cache[key] = (token, time.time() + lifetime - 120)
    return token


def _password(config, timestamp):
    raw = f"{_shortcode(config)}{_passkey(config)}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _send(config, path, payload, token):
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    try:
        response = requests.post(
            f"{_base(config)}{path}", json=payload, headers=headers, timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        raise MpesaError(f"M-Pesa could not be reached: {exc}") from exc
    try:
        return response.json()
    except ValueError:
        raise MpesaError(_blocked_message(response))


def _post(config, path, payload):
    data = _send(config, path, payload, _access_token(config))
    if data.get("errorCode") == "404.001.03":  # "Invalid Access Token": try one fresh token
        data = _send(config, path, payload, _access_token(config, refresh=True))
        if data.get("errorCode") == "404.001.03":
            raise MpesaError(
                "Invalid Access Token. On the Daraja portal, open your app and make sure the "
                "\"M-Pesa Express Sandbox\" (Lipa Na M-Pesa) product is ticked."
            )
    return data


def stk_push(config, phone, amount, reference, description):
    """Ask Safaricom to prompt the phone for payment.

    Returns {"merchant_request_id", "checkout_request_id"}.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": _shortcode(config),
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": _shortcode(config),
        "PhoneNumber": phone,
        "CallBackURL": callback_url(config),
        "AccountReference": str(reference)[:12],
        "TransactionDesc": str(description)[:13],
    }
    data = _post(config, "/mpesa/stkpush/v1/processrequest", payload)
    if data.get("ResponseCode") != "0":
        message = data.get("errorMessage") or data.get("ResponseDescription") or "Request refused"
        raise MpesaError(message)
    return {
        "merchant_request_id": data.get("MerchantRequestID"),
        "checkout_request_id": data.get("CheckoutRequestID"),
    }


def stk_query(config, checkout_request_id):
    """Ask Safaricom how a prompt ended.

    Returns None while the customer is still deciding, otherwise
    {"code": int, "description": str}.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": _shortcode(config),
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }
    data = _post(config, "/mpesa/stkpushquery/v1/query", payload)
    if "ResultCode" not in data or data.get("errorCode") in STILL_PROCESSING_ERRORS:
        # "The transaction is being processed" comes back as an error body;
        # so do rate-limit replies. Neither is a result, so keep waiting.
        return None
    try:
        code = int(data["ResultCode"])
    except (TypeError, ValueError):
        return None
    if code in STILL_PROCESSING_CODES:
        return None
    return {"code": code, "description": data.get("ResultDesc") or RESULT_MESSAGES.get(code, "")}


def parse_callback(body):
    """Read Safaricom's callback JSON into a simple dict, or None if malformed."""
    try:
        stk = body["Body"]["stkCallback"]
        result = {
            "merchant_request_id": stk.get("MerchantRequestID"),
            "checkout_request_id": stk["CheckoutRequestID"],
            "code": int(stk["ResultCode"]),
            "description": stk.get("ResultDesc", ""),
            "receipt": None,
            "amount": None,
            "phone": None,
        }
        for item in (stk.get("CallbackMetadata") or {}).get("Item", []):
            name, value = item.get("Name"), item.get("Value")
            if name == "MpesaReceiptNumber":
                result["receipt"] = value
            elif name == "Amount":
                result["amount"] = value
            elif name == "PhoneNumber":
                result["phone"] = str(value)
        return result
    except (KeyError, TypeError, ValueError):
        return None
