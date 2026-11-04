"""Server entry point. Run in the server folder: `uvicorn app.main:app --reload`"""
import logging
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError


from .accounts.login import attempt_login, end_session
from .accounts.rules import SESSION_LIFETIME, SignedInPerson, is_session_token
from .accounts.sessions import resolve_session
from .ai import AIError
from .audit.log import list_events
from .audit.rules import parse_event_limit
from . import settings, gateway
from .database.schema import connect, create_tables
from .schemas import AuditEventList, ErrorResponse, AskResponse, AskRequest, LoginRequest, PersonResponse


log = logging.getLogger("agentstack")

SESSION_COOKIE = "agentstack_session"

# An exact origin: http:// or https://, a host name and an optional port; no path, no trailing "/".
ORIGIN_FORMAT = re.compile(r"https?://[a-z0-9.-]+(:[0-9]{1,5})?")
ORIGIN_ERROR = (
    "FRONTEND_ORIGINS must list exact origins like http://localhost:5173 (no path, no trailing slash); "
    "'*' and 'null' are not allowed."
)


def cors_options(origins: list[str]) -> dict[str, object]:
    """CORS settings for the frontend (API contract v3). An empty list is valid: no browser access.

    The session cookie is sent, so a wildcard or 'null' origin would let any site send requests with it.
    """
    if any(not ORIGIN_FORMAT.fullmatch(origin) for origin in origins):
        raise ValueError(ORIGIN_ERROR)
    return {
        "allow_origins": list(origins),
        "allow_credentials": True,
        "allow_methods": ["GET", "POST"],
        "allow_headers": ["Content-Type"],
        "expose_headers": ["Retry-After"],
    }


app = FastAPI(title="Agent Stack", version="0.1.0")

app.add_middleware(CORSMiddleware, **cors_options(settings.FRONTEND_ORIGINS))


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message})
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def _database() -> Iterator[sqlite3.Connection]:
    # Every request opens its own connection (FastAPI requests run in separate threads).
    connection = connect(settings.DATABASE_PATH)
    try:
        create_tables(connection)
        yield connection
    finally:
        connection.close()


def _client_ip(request: Request) -> str:
    # The address of the connection; proxy headers such as X-Forwarded-For can be forged and are not read.
    return request.client.host if request.client else "unknown"


class NotSignedIn(Exception):
    """No valid session: no session, an expired session or an inactive account."""


class Forbidden(Exception):
    """A valid session of an active account, but the role is not allowed. Admin endpoints only."""


def current_person(request: Request) -> SignedInPerson:
    """The single way to find who is calling: the session cookie, checked again on every request."""
    token = request.cookies.get(SESSION_COOKIE)
    if not is_session_token(token):
        raise NotSignedIn()
    with _database() as connection:
        person = resolve_session(connection, token, _utc_now())
    if person is None:
        raise NotSignedIn()
    return person


def ask_person(request: Request) -> SignedInPerson:
    """current_person for /api/ask: a refused question also leaves an audit event (limited; the answer stays 401)."""
    start = time.perf_counter()
    try:
        return current_person(request)
    except NotSignedIn:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        gateway.record_unauthenticated_ask(_client_ip(request), _utc_now(), duration_ms)
        raise


def current_admin(person: SignedInPerson = Depends(current_person)) -> SignedInPerson:
    """Checked on every request by the endpoint itself: only the role "admin" passes, any other value is refused."""
    if person.role != "admin":
        raise Forbidden()
    return person


def read_event_limit(request: Request) -> int:
    """Reads `limit` itself: a whole number with digits only (FastAPI's int would accept "5.0" and "+5").

    So this dependency must come after current_admin in the endpoint: the session and the role are checked first.
    """
    try:
        return parse_event_limit(request.query_params.getlist("limit"))
    except ValueError:
        raise RequestValidationError([]) from None


async def read_ask_body(request: Request) -> AskRequest:
    """Reads the body of /api/ask itself, because FastAPI parses a body parameter before any dependency.

    So this dependency must come after current_person in the endpoint: without a session the answer
    is 401 for every body, also for broken JSON (API contract 8).
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise RequestValidationError([])
    try:
        return AskRequest.model_validate_json(await request.body())
    except ValidationError:
        raise RequestValidationError([]) from None


def _person_response(person: SignedInPerson) -> PersonResponse:
    return PersonResponse(
        username=person.username,
        name=person.display_name,
        role=person.role,
        slack_linked=person.slack_user_id is not None,
    )


@app.exception_handler(NotSignedIn)
async def handle_not_signed_in(_: Request, __: NotSignedIn):
    return error_response(401, "UNAUTHENTICATED", "Please sign in.")


@app.exception_handler(Forbidden)
async def handle_forbidden(_: Request, __: Forbidden):
    return error_response(403, "FORBIDDEN", "You don't have permission for this page.")


@app.exception_handler(AIError)
async def handle_ai_error(_: Request, exc: AIError):
    if exc.code == "TIMEOUT":
        return error_response(504, "TIMEOUT", exc.message)
    return error_response(502, "PROVIDER_ERROR", exc.message)


@app.exception_handler(RequestValidationError)
async def handle_invalid_request(_: Request, __: RequestValidationError):
    return error_response(422, "INVALID_REQUEST", "Invalid request format. See the API contract.")


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception):
    # We do not log the request content: it may contain company data.
    log.error("Unexpected error: %s", type(exc).__name__)
    return error_response(500, "SERVER_ERROR", "An unexpected server error occurred.")


@app.get("/health")
def health():
    return {"status": "up"}


@app.post(
    "/api/auth/login",
    response_model=PersonResponse,
    responses={
        401: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
        429: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
    },
)
def login(body: LoginRequest, request: Request, response: Response):
    with _database() as connection:
        result = attempt_login(connection, body.username, body.password, _client_ip(request), _utc_now())
    if result.retry_after is not None:
        limited = error_response(429, "TOO_MANY_ATTEMPTS", "Too many login attempts. Try again later.")
        limited.headers["Retry-After"] = str(result.retry_after)
        return limited
    if result.person is None:
        return error_response(401, "INVALID_CREDENTIALS", "Username or password is incorrect.")
    response.set_cookie(
        SESSION_COOKIE, result.token, max_age=int(SESSION_LIFETIME.total_seconds()), path="/",
        secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite="lax",
    )
    return _person_response(result.person)


@app.post("/api/auth/logout", status_code=204, response_class=Response, responses={500: {"model": ErrorResponse}})
def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if is_session_token(token):
        with _database() as connection:
            end_session(connection, token, _utc_now())
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite="lax",
    )
    return response


@app.get(
    "/api/auth/me",
    response_model=PersonResponse,
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def me(person: SignedInPerson = Depends(current_person)) -> PersonResponse:
    return _person_response(person)


@app.post(
    "/api/ask",
    response_model=AskResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    # The body is read by read_ask_body, so its format is written here for the documentation.
    openapi_extra={"requestBody": {
        "required": True,
        "content": {"application/json": {"schema": AskRequest.model_json_schema()}},
    }},
)
def ask(
    person: SignedInPerson = Depends(ask_person),  # first: a request without a session never reaches the body
    body: AskRequest = Depends(read_ask_body),
) -> AskResponse:
    return gateway.handle_question(question=body.question, person=person)


@app.get(
    "/api/admin/events",
    response_model=AuditEventList,
    responses={
        401: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
        422: {"model": ErrorResponse}, 500: {"model": ErrorResponse},
    },
)
def admin_events(
    admin: SignedInPerson = Depends(current_admin),  # first: session and role before the limit
    limit: int = Depends(read_event_limit),
) -> AuditEventList:
    with _database() as connection:
        return AuditEventList(events=list_events(connection, limit))
