"""API contract: the format of the data sent between the frontend and the server.

Detailed description: docs/api-contract.md
"""
from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="The user's question")
    # TEMPORARY: removed in Stage 2; identity will be read from the session.
    # If this field stays, it is the biggest authorization hole: Ali can change this field and become Nuri.
    user: str = Field(min_length=1, max_length=100, description="TEMPORARY user name")


class SourceMessage(BaseModel):
    channel: str
    author: str
    time: str  # ISO 8601, e.g. 2026-10-22T14:05:00+03:00
    text: str


class SecuritySummary(BaseModel):
    blocked: int = 0
    masked: int = 0
    suspicious: int = 0


class AskResponse(BaseModel):
    request_id: str
    status: Literal["ok", "no_access"] = "ok"
    answer: str
    sources: list[SourceMessage] = []
    security: SecuritySummary = SecuritySummary()


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
