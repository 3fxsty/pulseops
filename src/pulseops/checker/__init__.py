"""The checker: visits a URL and reports whether it is up.

Pure network logic, no database: Phase 4 stores the outcomes.
"""

from pulseops.checker.http import Checker, check_url
from pulseops.checker.outcome import CheckOutcome

__all__ = ["CheckOutcome", "Checker", "check_url"]
