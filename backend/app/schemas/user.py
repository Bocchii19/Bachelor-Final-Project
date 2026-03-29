"""Pydantic Schemas — User & Auth."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    email: str = Field(..., max_length=100)
    full_name: str = Field(..., max_length=100)
    role: str = Field(..., pattern="^(admin|teacher)$")


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)


class UserRead(UserBase):
    id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str  # user_id as string
    role: str
    exp: Optional[int] = None
