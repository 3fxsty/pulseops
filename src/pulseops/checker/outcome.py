from dataclasses import dataclass

from pulseops.db.models import ERROR_KINDS

# Matches checks.error_detail (varchar(500)).
MAX_ERROR_DETAIL_LENGTH = 500


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    """What one visit to a URL found. Mirrors a row of the checks table."""

    is_up: bool
    status_code: int | None = None
    response_time_ms: int | None = None
    error_kind: str | None = None
    error_detail: str | None = None

    def __post_init__(self) -> None:
        # Same rules as the database constraints, caught before any insert.
        if self.is_up != (self.error_kind is None):
            raise ValueError("is_up must be True exactly when error_kind is None")
        if self.error_kind is not None and self.error_kind not in ERROR_KINDS:
            raise ValueError(f"Unknown error_kind: {self.error_kind}")
        if self.error_detail is not None:
            object.__setattr__(
                self, "error_detail", self.error_detail[:MAX_ERROR_DETAIL_LENGTH]
            )


def up(status_code: int, response_time_ms: int) -> CheckOutcome:
    return CheckOutcome(
        is_up=True, status_code=status_code, response_time_ms=response_time_ms
    )


def down(
    error_kind: str,
    detail: str,
    *,
    status_code: int | None = None,
    response_time_ms: int | None = None,
) -> CheckOutcome:
    return CheckOutcome(
        is_up=False,
        status_code=status_code,
        response_time_ms=response_time_ms,
        error_kind=error_kind,
        error_detail=detail,
    )
