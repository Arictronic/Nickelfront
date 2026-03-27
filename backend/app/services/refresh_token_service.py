"""Сервис для работы с refresh-токенами."""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_refresh_token, hash_refresh_token
from app.db.models.refresh_token import RefreshToken


class RefreshTokenService:
    """Создание, проверка и отзыв refresh-токенов."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_for_user(self, user_id: int) -> str:
        """Создать refresh-токен для пользователя и сохранить в БД."""
        raw_token = create_refresh_token()
        token_hash = hash_refresh_token(raw_token)
        expires_at = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(token)
        await self.db.commit()
        return raw_token

    async def get_by_token(self, raw_token: str) -> Optional[RefreshToken]:
        """Получить refresh-токен по значению."""
        token_hash = hash_refresh_token(raw_token)
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_valid_token(self, raw_token: str) -> Optional[RefreshToken]:
        """Проверить refresh-токен на валидность."""
        token = await self.get_by_token(raw_token)
        if not token:
            return None
        if token.revoked_at is not None:
            return None
        if token.expires_at <= datetime.utcnow():
            return None
        return token

    async def revoke_token(self, token: RefreshToken) -> None:
        """Отозвать refresh-токен."""
        if token.revoked_at is not None:
            return
        token.revoked_at = datetime.utcnow()
        await self.db.commit()

    async def revoke_user_tokens(self, user_id: int) -> None:
        """Отозвать все refresh-токены пользователя."""
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.utcnow())
        )
        await self.db.commit()
