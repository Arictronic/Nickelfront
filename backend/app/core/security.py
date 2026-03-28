"""JWT утилиты для авторизации."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Контекст для хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверить пароль по хешу."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Получить хеш пароля."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Создать JWT токен доступа."""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.get_secret_key(),
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict | None:
    """Декодировать JWT токен."""
    try:
        payload = jwt.decode(
            token,
            settings.get_secret_key(),
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def create_refresh_token() -> str:
    """Создать refresh-токен."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Хешировать refresh-токен для хранения."""
    secret = settings.get_secret_key().encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_refresh_token(token: str, token_hash: str) -> bool:
    """Проверить refresh-токен по хешу."""
    return hmac.compare_digest(hash_refresh_token(token), token_hash)
