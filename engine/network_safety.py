"""URL and DNS checks for public-only fetch adapters."""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]


def _resolve(host: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        return list(dict.fromkeys(
            str(ipaddress.ip_address(item[4][0]))
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)))


def validate_public_target_url(url: str, *,
                               resolver: Resolver = _resolve) -> tuple[str, ...]:
    """Return validated DNS answers; reject non-public destinations and unsafe URLs."""
    parsed = urlsplit(url)
    if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password):
        raise ValueError("target URL must be an HTTP(S) URL without credentials")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("loopback target is not allowed")
    try:
        addresses = tuple(resolver(host))
    except OSError as exc:
        raise ValueError("target hostname could not be resolved") from exc
    if not addresses:
        raise ValueError("target hostname has no DNS addresses")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("resolver returned an invalid address") from exc
        if not ip.is_global:
            raise ValueError("target resolves to a non-public IP address")
    return addresses
