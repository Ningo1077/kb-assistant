import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=72)
    display_name: str = Field(default="", max_length=64)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v


class LoginIn(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=512)


class KBOut(BaseModel):
    id: int
    name: str
    description: str
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    filename: str
    mime_type: str
    size_bytes: int
    status: str
    page_count: int
    chunk_count: int
    error_msg: str
    created_at: datetime


class ChatIn(BaseModel):
    kb_id: int
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: int | None = None


class Citation(BaseModel):
    index: int
    chunk_id: int
    doc_id: int
    filename: str
    page_no: int
    snippet: str
    score: float


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    citations: list[dict] | None = None
    latency_ms: int
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    title: str
    created_at: datetime
    updated_at: datetime


class FeedbackIn(BaseModel):
    message_id: int
    rating: int = Field(ge=-1, le=1)
    comment: str = Field(default="", max_length=512)


class HealthOut(BaseModel):
    status: str
    database: str
    embed_provider: str
    llm_provider: str
