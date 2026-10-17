"""Sending one webhook over HTTP, safely.

The main risk with webhooks is SSRF: a partner (or an attacker holding a partner's key) registers a
URL that points at OUR internal network, and our server dutifully calls it. The defences here:

1. Only public addresses. The hostname is resolved, every address must be public, and a private,
   loopback, link-local, multicast or cloud-metadata address is refused (`blocked_address`).
2. We then connect to the address we checked, not to the name again, so a name cannot answer
   "public" for the check and "internal" for the connection (DNS rebinding).
3. Redirects are never followed (a redirect could point inside).
4. The partner's reply body is never read or stored, and error text never leaves this module:
   only short codes do.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

log = logging.getLogger("certivo.webhooks")

MAX_URL_LENGTH = 2048
BLOCKED_NAME_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
Resolver = Callable[[str, int], list[str]]


class UrlNotAllowed(ValueError):
    """The URL breaks the rules in docs/spec/base/05-webhooks.md, section 1. The text is safe to show."""


@dataclass(frozen=True)
class SendResult:
    status_code: int | None
    error: str | None  # None means the partner answered 2xx. Otherwise a short code, never free text.
    duration_ms: int


def is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 is really 10.0.0.1
    return ip.is_global


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def parse_target(url: str, *, allow_http: bool, allow_private: bool) -> tuple[str, str, int, str]:
    """Returns (scheme, host, port, path_and_query) or raises UrlNotAllowed."""
    if len(url) > MAX_URL_LENGTH:
        raise UrlNotAllowed(f"URL is longer than {MAX_URL_LENGTH} characters")
    if not url.isascii() or any(c in url for c in " \t\r\n"):
        raise UrlNotAllowed("URL must be plain ASCII with no spaces")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise UrlNotAllowed("URL must start with https://")
    if parts.scheme == "http" and not allow_http:
        raise UrlNotAllowed("URL must use https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UrlNotAllowed("URL must not contain a username or password")
    if parts.fragment:
        raise UrlNotAllowed("URL must not contain a fragment (#)")
    host = parts.hostname
    if not host:
        raise UrlNotAllowed("URL has no host name")
    try:
        port = parts.port
    except ValueError:
        raise UrlNotAllowed("URL has an invalid port") from None
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    if not allow_private:
        if _is_ip_literal(host):
            if not is_public_address(host):
                raise UrlNotAllowed("URL points at a private or internal address")
        elif host == "localhost" or host.endswith(BLOCKED_NAME_SUFFIXES) or "." not in host:
            raise UrlNotAllowed("URL points at a private or internal host name")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.scheme, host, port, path


def default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    return sorted(addresses, key=lambda a: ":" in a)  # IPv4 first: it is the more reliably routed


def _caused_by_tls(exc: BaseException | None) -> bool:
    while exc is not None:
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class HttpSender:
    def __init__(self, *, resolver: Resolver | None = None, verify: ssl.SSLContext | bool = True):
        self._resolver = resolver or default_resolver
        self._verify = verify

    def __call__(self, url: str, body: bytes, headers: dict[str, str], *, timeout_s: float,
                 allow_private: bool, allow_http: bool) -> SendResult:
        started = time.monotonic()

        def finish(status: int | None, error: str | None) -> SendResult:
            return SendResult(status, error, int((time.monotonic() - started) * 1000))

        try:
            scheme, host, port, path = parse_target(url, allow_http=allow_http,
                                                    allow_private=allow_private)
        except UrlNotAllowed:
            return finish(None, "invalid_url")
        try:
            addresses = self._resolver(host, port)
        except OSError:
            return finish(None, "dns_error")
        if not addresses:
            return finish(None, "dns_error")
        if not allow_private and not all(is_public_address(a) for a in addresses):
            return finish(None, "blocked_address")

        ip = addresses[0]  # the address we just checked is the one we connect to
        netloc_ip = f"[{ip}]" if ":" in ip else ip
        default_port = 443 if scheme == "https" else 80
        host_header = (f"[{host}]" if ":" in host else host) + ("" if port == default_port else f":{port}")
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=False, trust_env=False,
                              verify=self._verify) as client:
                with client.stream(
                    "POST", f"{scheme}://{netloc_ip}:{port}{path}", content=body,
                    headers={**headers, "Host": host_header},
                    extensions={"sni_hostname": host} if scheme == "https" else {},
                ) as response:
                    status = response.status_code  # the body is deliberately never read
        except httpx.TimeoutException:
            return finish(None, "timeout")
        except httpx.ConnectError as exc:
            return finish(None, "tls_error" if _caused_by_tls(exc) else "connection_error")
        except httpx.HTTPError:
            return finish(None, "request_error")
        except Exception:  # one odd failure must never crash the worker
            log.exception("Unexpected error sending a webhook")
            return finish(None, "request_error")

        if 200 <= status < 300:
            return finish(status, None)
        if 300 <= status < 400:
            return finish(status, "redirect")
        return finish(status, "http_status")
