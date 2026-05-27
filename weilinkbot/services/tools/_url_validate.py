"""Shared URL validation with SSRF protection for all web-facing tools."""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from .base import ToolExecutionError

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS = frozenset({
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
})

_PRIVATE_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def validate_url(url: str) -> str:
    """Validate a URL is safe to fetch, blocking private/internal addresses.

    Returns the resolved IP address string for callers to pin connections.
    Raises ToolExecutionError if the URL targets a private, loopback, or
    link-local address, or uses a disallowed scheme.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolExecutionError(
            f"Only http/https URLs are supported, got: {parsed.scheme or 'no scheme'}"
        )
    if not parsed.netloc:
        raise ToolExecutionError(f"Invalid URL: {url}")

    # Strip port from netloc for hostname resolution
    hostname = parsed.hostname
    if not hostname:
        raise ToolExecutionError(f"Cannot extract hostname from URL: {url}")

    # Block known hostnames
    if hostname.lower() in _BLOCKED_HOSTS:
        raise ToolExecutionError(f"Access to internal host '{hostname}' is not allowed")

    # Try to resolve hostname and check if it points to a private IP
    resolved_ip = None
    try:
        # Use getaddrinfo to resolve, preferring IPv4
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in _PRIVATE_NETWORKS:
                if ip in network:
                    raise ToolExecutionError(
                        f"Access to internal/private address {ip} is not allowed"
                    )
            if resolved_ip is None:
                resolved_ip = str(ip)
    except ToolExecutionError:
        raise
    except socket.gaierror:
        # DNS resolution failed - let the HTTP client handle the error
        logger.debug("DNS resolution failed for %s, proceeding with request", hostname)
    except Exception as e:
        logger.debug("IP check failed for %s: %s", hostname, e)

    return resolved_ip or hostname
