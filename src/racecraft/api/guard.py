"""
What keeps the API to this computer's own pages.

The server listens on 127.0.0.1 only, but any web page open in a browser on the
same computer can still send it requests. Three checks close that:

* **The Host header must name this computer.** A site that points its own
  domain at 127.0.0.1 (DNS rebinding) could otherwise read every answer; its
  requests carry its own name, and are refused.
* **A request that changes something must come from a page this server
  served.** Anything but GET, HEAD and OPTIONS is checked: a browser names the
  page that sent it in the Origin header, and another site's is refused. The
  desktop app's own calls (a second launch asking the first to come forward)
  come from no page, carry no Origin, and pass.
* **Every response carries headers** that stop it being framed by another site,
  sniffed as another type, or used to load scripts from anywhere else.

To reach the server from another device on purpose, name the address it will
be reached by in RACECRAFT_ALLOWED_HOSTS (comma-separated). There is no login:
anyone who can reach it can use it.
"""

from __future__ import annotations

import json
import os

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Everything the interface loads is its own: the bundle, its fonts, the API.
# Styles allow 'unsafe-inline' because React and the charts set style
# attributes; scripts allow nothing but the bundle.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

SECURITY_HEADERS = [
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-origin"),
]


def allowed_hosts() -> frozenset[str]:
    """This computer's names, plus any named in RACECRAFT_ALLOWED_HOSTS."""
    extra = os.environ.get("RACECRAFT_ALLOWED_HOSTS", "")
    return LOCAL_HOSTS | {h.strip().lower() for h in extra.split(",") if h.strip()}


def hostname(host: str) -> str:
    """The name in a Host header, without its port: '[::1]:8000' is '::1'."""
    host = host.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end > 0 else ""
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class Guard:
    """ASGI middleware: the host and origin checks, and the security headers."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if hostname(host) not in allowed_hosts():
            await _refuse(send, f"host '{host}' is not this computer")
            return
        if scope["method"] not in SAFE_METHODS and not _same_origin(headers, host):
            await _refuse(send, "requests that change something must come from Racecraft's own pages")
            return

        async def with_headers(message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in SECURITY_HEADERS if k not in present]
            await send(message)

        await self.app(scope, receive, with_headers)


def _same_origin(headers: dict[str, str], host: str) -> bool:
    origin = headers.get("origin")
    if origin is not None:
        return origin.lower() == f"http://{host.lower()}"
    # No Origin: not sent by a page, unless the browser still says it was another site's.
    return headers.get("sec-fetch-site") not in ("cross-site", "same-site")


async def _refuse(send, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": 403,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()), *SECURITY_HEADERS]})
    await send({"type": "http.response.body", "body": body})
