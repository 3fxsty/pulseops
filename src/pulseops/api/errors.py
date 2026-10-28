"""Every error leaves the API as RFC 9457 Problem Details plus a `code` (ADR-020).

Responses never echo user input, SQL, table or constraint names, or traces.
Unexpected errors are logged and answered with a generic 500.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from pulseops.repositories.monitors import MonitorUrlConflictError
from pulseops.security.errors import (
    InvalidUrlError,
    UrlCredentialsNotAllowedError,
    UrlTargetNotAllowedError,
)

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"

# Generic codes for errors raised by the framework itself (unknown route...).
HTTP_STATUS_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiProblem(Exception):
    """Raise from an endpoint to answer with a Problem Details response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        errors: list[dict] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors


def unauthorized() -> ApiProblem:
    return ApiProblem(
        401, "unauthorized", "Unauthorized", "A valid X-API-Key header is required."
    )


def monitor_not_found() -> ApiProblem:
    return ApiProblem(
        404, "monitor_not_found", "Monitor not found", "No monitor has this id."
    )


def invalid_cursor() -> ApiProblem:
    # Never echoes the cursor that was sent.
    return ApiProblem(
        422,
        "invalid_cursor",
        "Invalid cursor",
        "Use the next_cursor of a previous page, or no cursor for the first one.",
    )


def problem_response(problem: ApiProblem) -> JSONResponse:
    body = {
        # A relative reference under our own namespace, derived from the code.
        "type": f"/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "code": problem.code,
    }
    if problem.errors is not None:
        body["errors"] = problem.errors
    return JSONResponse(body, status_code=problem.status, media_type=PROBLEM_JSON)


def validation_problem(errors: list[dict]) -> ApiProblem:
    return ApiProblem(
        422,
        "validation_error",
        "Validation error",
        "The request is not valid.",
        errors=errors,
    )


async def handle_api_problem(request: Request, exc: ApiProblem) -> JSONResponse:
    return problem_response(exc)


async def handle_request_validation(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Only loc, msg and type: never `input`, which may hold secrets.
    errors = [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return problem_response(validation_problem(errors))


async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    title = code.replace("_", " ").capitalize()
    detail = exc.detail if isinstance(exc.detail, str) else title
    return problem_response(ApiProblem(exc.status_code, code, title, detail))


async def handle_invalid_url(request: Request, exc: InvalidUrlError) -> JSONResponse:
    errors = [{"loc": ["body", "url"], "msg": exc.reason, "type": "url_invalid"}]
    return problem_response(validation_problem(errors))


async def handle_url_credentials(
    request: Request, exc: UrlCredentialsNotAllowedError
) -> JSONResponse:
    return problem_response(
        ApiProblem(
            422,
            "url_credentials_not_allowed",
            "Credentials not allowed in URL",
            "Remove the user name and password from the URL.",
        )
    )


async def handle_url_target(
    request: Request, exc: UrlTargetNotAllowedError
) -> JSONResponse:
    # Deliberately vague: never reveal the IP or what a name resolves to.
    return problem_response(
        ApiProblem(
            422,
            "url_target_not_allowed",
            "URL target not allowed",
            "The URL points to a destination that cannot be monitored.",
        )
    )


async def handle_url_conflict(
    request: Request, exc: MonitorUrlConflictError
) -> JSONResponse:
    return problem_response(
        ApiProblem(
            409,
            "monitor_url_conflict",
            "Monitor URL already exists",
            "Another monitor already uses this URL.",
        )
    )


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # The details go to the logs only; the client gets nothing internal.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return problem_response(
        ApiProblem(
            500,
            "internal_error",
            "Internal server error",
            "An unexpected error occurred.",
        )
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiProblem, handle_api_problem)
    app.add_exception_handler(RequestValidationError, handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(InvalidUrlError, handle_invalid_url)
    app.add_exception_handler(UrlCredentialsNotAllowedError, handle_url_credentials)
    app.add_exception_handler(UrlTargetNotAllowedError, handle_url_target)
    app.add_exception_handler(MonitorUrlConflictError, handle_url_conflict)
    app.add_exception_handler(Exception, handle_unexpected)
