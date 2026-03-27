"""Сервис для работы с пользователями."""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from loguru import logger

from app.db.models.user import User
from app.core.security import get_password_hash, verify_password


class UserService:
    """Сервис для управления пользователями."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> Optional[User]:
        """Получить пользователя по email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Получить пользователя по ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_user(self, email: str, password: str, username: Optional[str] = None) -> User:
        """Создать нового пользователя."""
        password_hash = get_password_hash(password)

        user = User(
            email=email,
            username=username,
            password_hash=password_hash,
            is_active=True,
            is_verified=False,
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"Создан новый пользователь: {email}")
        return user

    async def update_last_login(self, user: User) -> None:
        """Обновить время последнего входа."""
        user.last_login_at = datetime.utcnow()
        await self.db.commit()

    async def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверить пароль."""
        return verify_password(plain_password, hashed_password)

    async def authenticate(self, email: str, password: str) -> Optional[User]:
        """Аутентифицировать пользователя."""
        user = await self.get_by_email(email)
        if not user:
            return None
        if not await self.verify_password(password, user.password_hash):
            return None
        if not user.is_active:
            return None
        return user
