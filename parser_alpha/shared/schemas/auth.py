"""Схемы данных для авторизации."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Базовая схема пользователя."""

    email: EmailStr = Field(..., description="Email пользователя")
    username: str | None = Field(None, min_length=2, max_length=100, description="Имя пользователя")


class UserCreate(UserBase):
    """Схема для регистрации пользователя."""

    password: str = Field(..., min_length=8, max_length=100, description="Пароль")


class UserLogin(BaseModel):
    """Схема для входа пользователя."""

    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., description="Пароль")


class UserResponse(UserBase):
    """Схема ответа с данными пользователя."""

    id: int
    is_active: bool = True
    is_admin: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    """Схема токена доступа."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


class RefreshTokenRequest(BaseModel):
    """Запрос на обновление токена."""

    refresh_token: str


class TokenData(BaseModel):
    """Схема данных токена."""

    email: str | None = None
    user_id: int | None = None
