"""Server entry point. Run in the server folder: `uvicorn app.main:app --reload`"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


from .ai import AIError
from . import settings, gateway
from .schemas import ErrorResponse, AskResponse, AskRequest


log = logging.getLogger("agentstack")

app = FastAPI(title="Agent Stack", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error={"code": code, "message": message})
    return JSONResponse(status_code=status_code, content=body.model_dump())


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
    "/api/ask",
    response_model=AskResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def ask(request: AskRequest) -> AskResponse:
    return gateway.handle_question(question=request.question, user=request.user)
