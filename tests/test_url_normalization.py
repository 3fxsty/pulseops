import pytest

from pulseops.security.errors import InvalidUrlError, UrlCredentialsNotAllowedError
from pulseops.security.urls import MAX_URL_LENGTH, normalize_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM", "https://example.com/"),
        ("https://example.com:443/", "https://example.com/"),
        ("http://example.com:80/", "http://example.com/"),
        ("  https://example.com/  ", "https://example.com/"),
        ("https://example.com/a?b=1#section", "https://example.com/a?b=1"),
        ("https://example.com./path", "https://example.com/path"),
        ("http://Example.com.:8080/", "http://example.com:8080/"),
        ("https://example.com/Path?Q=A&b=2", "https://example.com/Path?Q=A&b=2"),
        ("https://bücher.de", "https://xn--bcher-kva.de/"),
        ("http://2130706433/", "http://127.0.0.1/"),
        ("http://0x7f.1/", "http://127.0.0.1/"),
        ("http://[::1]:8080/", "http://[::1]:8080/"),
    ],
)
def test_normalizes_url(raw, expected):
    assert normalize_url(raw).url == expected


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        ("https://Example.com./", "example.com"),
        ("http://[::ffff:127.0.0.1]/", "::ffff:7f00:1"),
        ("http://0x7f.1/", "127.0.0.1"),
    ],
)
def test_exposes_bare_host_for_ssrf_check(raw, host):
    assert normalize_url(raw).host == host


@pytest.mark.parametrize(
    "raw",
    [
        "https://user:secret@example.com/",
        "https://user@example.com/",
        "http://example.com@127.0.0.1/",
    ],
)
def test_rejects_credentials(raw):
    with pytest.raises(UrlCredentialsNotAllowedError):
        normalize_url(raw)


@pytest.mark.parametrize(
    "raw",
    ["ftp://example.com", "javascript:alert(1)", "not a url", "", "https://"],
)
def test_rejects_invalid_urls(raw):
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)


def test_length_limit_applies_after_normalization():
    base = "https://example.com/"
    fits = base + "a" * (MAX_URL_LENGTH - len(base))

    assert normalize_url(fits).url == fits
    # The fragment is dropped, so a long one does not count.
    assert normalize_url(fits + "#" + "x" * 30).url == fits
    with pytest.raises(InvalidUrlError):
        normalize_url(fits + "a")


def test_error_reason_does_not_echo_the_url():
    with pytest.raises(InvalidUrlError) as error:
        normalize_url("ftp://secret-host.example")

    assert "secret-host" not in error.value.reason
