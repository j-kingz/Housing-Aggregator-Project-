"""Validation helpers for administrator-configured scraper URLs."""

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a scraper URL could target a local or private network."""


def validate_public_https_url(value, field_name="URL"):
    """Return a normalized URL or raise for an unsafe scraper target."""
    raw = (value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise UnsafeUrlError(f"{field_name} must be an absolute HTTPS URL.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError(f"{field_name} must not contain login credentials.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise UnsafeUrlError(f"{field_name} cannot target a local host.")

    try:
        addresses = {
            ipaddress.ip_address(info[4][0])
            for info in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except (socket.gaierror, ValueError, OSError) as exc:
        raise UnsafeUrlError(f"{field_name} host could not be resolved.") from exc

    if not addresses or any(
        not address.is_global
        for address in addresses
    ):
        raise UnsafeUrlError(f"{field_name} must resolve only to a public IP address.")
    return raw


def validate_request_url(url):
    """Validate a URL immediately before requesting it."""
    return validate_public_https_url(url, "Scraper URL")
