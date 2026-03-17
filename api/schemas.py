from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DraftCreate(BaseModel):
    payload: dict[str, Any]
    status: str = "draft"


class DraftUpdate(BaseModel):
    payload: dict[str, Any] | None = None
    status: str | None = None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int
    status: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
