"""The single entry point that turns user input into a storable URL (ADR-030)."""

from pulseops.security.ssrf import check_target
from pulseops.security.urls import normalize_url

# Only this module holds the token, so only validate_monitor_url() can build
# a ValidatedUrl. Python has no private constructors: this prevents mistakes,
# not deliberate misuse.
_CONSTRUCTION_TOKEN = object()


class ValidatedUrl:
    """A URL that has been normalized and passed the SSRF check."""

    __slots__ = ("_value",)

    def __init__(self, value: str, *, _token: object) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError(
                "ValidatedUrl can only be created by validate_monitor_url()"
            )
        object.__setattr__(self, "_value", value)

    @property
    def value(self) -> str:
        return self._value

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ValidatedUrl is immutable")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ValidatedUrl) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
        return f"ValidatedUrl({self._value!r})"


async def validate_monitor_url(
    raw: str, *, allow_private_targets: bool
) -> ValidatedUrl:
    """Normalize (ADR-022), then run the SSRF check (ADR-023)."""
    normalized = normalize_url(raw)
    await check_target(normalized.host, allow_private=allow_private_targets)
    return ValidatedUrl(normalized.url, _token=_CONSTRUCTION_TOKEN)
