"""URL normalization, so the same site is never stored under two spellings."""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from pydantic import HttpUrl, TypeAdapter, ValidationError

from pulseops.security.errors import InvalidUrlError, UrlCredentialsNotAllowedError

MAX_URL_LENGTH = 2048

_http_url = TypeAdapter(HttpUrl)


@dataclass(frozen=True)
class NormalizedUrl:
    url: str
    # Hostname or IP literal, without IPv6 brackets or a trailing dot.
    host: str


def normalize_url(raw: str) -> NormalizedUrl:
    """Normalize a user-supplied URL (ADR-022).

    HttpUrl lowercases scheme and host, drops default ports, converts
    international domains to punycode, adds "/" for an empty path, accepts
    only http/https and canonicalizes odd IP notations (0x7f.1 -> 127.0.0.1).
    Path and query are left untouched: they are case-sensitive.
    """
    try:
        parsed = _http_url.validate_python(raw.strip())
    except ValidationError:
        raise InvalidUrlError("Must be a valid http or https URL.") from None

    if parsed.username is not None or parsed.password is not None:
        raise UrlCredentialsNotAllowedError

    parts = urlsplit(str(parsed))
    host = parts.hostname.rstrip(".") if parts.hostname else ""
    if not host:
        raise InvalidUrlError("Must be a valid http or https URL.")

    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"

    # An empty fragment drops "#...": browsers never send it to the server.
    url = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    if len(url) > MAX_URL_LENGTH:
        raise InvalidUrlError(
            f"Must be at most {MAX_URL_LENGTH} characters once normalized."
        )
    return NormalizedUrl(url=url, host=host)
