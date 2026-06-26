from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SecretsOut(BaseModel):
    deepseek_keys: str = ""
    dashscope_key: str = ""


class UsageReport(BaseModel):
    event: str = Field(min_length=1, max_length=32)
    success: bool = True
    duration_ms: int = 0
    meta: str = ""
    client_version: str = ""


class UsageEventOut(BaseModel):
    id: int
    user_id: int
    event: str
    success: bool
    duration_ms: int
    meta: str
    client_version: str
    created_at: datetime

    model_config = {"from_attributes": True}
