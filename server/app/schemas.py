"""API contract: the format of the data sent between the frontend and the server.

Detailed description: docs/api-contract.md
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AskRequest(BaseModel):
    # An unknown field is an invalid request (422), so an old client never works silently.
    # Identity comes only from the session: a "user" field gets 422 too.
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000, description="The user's question")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64, description="The account's user name")
    password: str = Field(min_length=1, max_length=128, description="The password")

    @field_validator("username", "password")
    @classmethod
    def _must_be_encodable(cls, value: str) -> str:
        # JSON can carry a lone surrogate ("\ud800"); such a text cannot be hashed. The error never contains the value.
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Text cannot be encoded.") from None
        return value


class PersonResponse(BaseModel):
    username: str
    name: str
    role: Literal["user", "admin"]
    slack_linked: bool


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


class AuditEventItem(BaseModel):
    created_at: str  # ISO 8601 in UTC
    request_id: str
    person: str | None  # the user name
    channel: str | None  # the channel name
    step: str
    decision: str
    reason_code: str | None
    message_count: int
    blocked_count: int
    masked_count: int
    suspicious_count: int
    duration_ms: float


class AuditEventList(BaseModel):
    events: list[AuditEventItem]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
