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


def callback_token(config):
    """Secret that must be in the callback URL so only Safaricom's call is accepted."""
    key = (config.get("SECRET_KEY") or "").encode()
    return hmac.new(key, b"mpesa-callback", hashlib.sha256).hexdigest()[:32]


def callback_url(config):
    base = config.get("MPESA_CALLBACK_BASE_URL") or "http://localhost"
    return f"{base}/payments/mpesa/callback/{callback_token(config)}"


def _base(config):
    return BASE_URLS.get(config.get("MPESA_ENV"), BASE_URLS["sandbox"])


def _access_token(config):
    try:
        response = requests.get(
            f"{_base(config)}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(config["MPESA_CONSUMER_KEY"], config["MPESA_CONSUMER_SECRET"]),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise MpesaError(f"Could not sign in to M-Pesa: {exc}") from exc


def _password(config, timestamp):
    raw = f"{config['MPESA_SHORTCODE']}{config['MPESA_PASSKEY']}{timestamp}"
    return base64.b64encode(raw.encode()).decode()


def _post(config, path, payload):
    headers = {"Authorization": f"Bearer {_access_token(config)}"}
    try:
        response = requests.post(
            f"{_base(config)}{path}", json=payload, headers=headers, timeout=TIMEOUT
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise MpesaError(f"M-Pesa could not be reached: {exc}") from exc
    return data


def stk_push(config, phone, amount, reference, description):
    """Ask Safaricom to prompt the phone for payment.

    Returns {"merchant_request_id", "checkout_request_id"}.
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": config["MPESA_SHORTCODE"],
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone,
        "PartyB": config["MPESA_SHORTCODE"],
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
        "BusinessShortCode": config["MPESA_SHORTCODE"],
        "Password": _password(config, timestamp),
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id,
    }
    data = _post(config, "/mpesa/stkpushquery/v1/query", payload)
    if "ResultCode" not in data:
        # "The transaction is being processed" comes back as an error body
        return None
    code = int(data["ResultCode"])
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
