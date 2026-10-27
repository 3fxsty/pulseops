class UrlValidationError(Exception):
    """Base class for every reason a monitor URL is refused."""


class InvalidUrlError(UrlValidationError):
    """Not a usable http(s) URL. The reason never echoes the URL itself."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UrlCredentialsNotAllowedError(UrlValidationError):
    """The URL embeds `user:password@`, which would be stored in plain text."""


class UrlTargetNotAllowedError(UrlValidationError):
    """The URL points to a private, internal or otherwise blocked address."""
