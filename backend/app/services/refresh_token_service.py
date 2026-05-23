"""Сервис для работы с refresh-токенами."""

from datetime import UTC, datetime, timedelta

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
        expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.db.add(token)
        await self.db.commit()
        return raw_token

    async def get_by_token(self, raw_token: str) -> RefreshToken | None:
        """Получить refresh-токен по значению."""
        token_hash = hash_refresh_token(raw_token)
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()


    @staticmethod
    def _ensure_aware(value: datetime) -> datetime:
        """Normalize DB datetimes for safe UTC comparisons."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    async def get_recently_revoked_token(
        self,
        raw_token: str,
        grace_seconds: int,
    ) -> RefreshToken | None:
        """
        Return a revoked refresh token only inside a short rotation grace window.

        This makes refresh idempotent enough for browser races: several tabs can
        receive 401 at the same moment and try to rotate the same refresh token.
        The first request revokes it; a following request within the grace window
        should not force logout if the token was otherwise valid.
        """
        if grace_seconds <= 0:
            return None

        token = await self.get_by_token(raw_token)
        if not token or token.revoked_at is None:
            return None

        expires_at = self._ensure_aware(token.expires_at)
        now = datetime.now(UTC)
        if expires_at <= now:
            return None

        revoked_at = self._ensure_aware(token.revoked_at)
        if now - revoked_at > timedelta(seconds=grace_seconds):
            return None

        return token

    async def get_valid_token(self, raw_token: str) -> RefreshToken | None:
        """Проверить refresh-токен на валидность."""
        token = await self.get_by_token(raw_token)
        if not token:
            return None
        if token.revoked_at is not None:
            return None
        expires_at = self._ensure_aware(token.expires_at)
        if expires_at <= datetime.now(UTC):
            return None
        return token

    async def revoke_token(self, token: RefreshToken) -> None:
        """Отозвать refresh-токен."""
        if token.revoked_at is not None:
            return
        token.revoked_at = datetime.now(UTC)
        await self.db.commit()

    async def revoke_user_tokens(self, user_id: int) -> None:
        """Отозвать все refresh-токены пользователя."""
        await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self.db.commit()
