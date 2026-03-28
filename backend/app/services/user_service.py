"""Сервис для работы с пользователями."""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.db.models.user import User


class UserService:
    """Сервис для управления пользователями."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        """Получить пользователя по email."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        """Получить пользователя по ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_user(self, email: str, password: str, username: str | None = None) -> User:
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
        user.last_login_at = datetime.now(UTC)
        await self.db.commit()

    async def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверить пароль."""
        return verify_password(plain_password, hashed_password)

    async def authenticate(self, email: str, password: str) -> User | None:
        """Аутентифицировать пользователя."""
        user = await self.get_by_email(email)
        if not user:
            return None
        if not await self.verify_password(password, user.password_hash):
            return None
        if not user.is_active:
            return None
        return user

    async def ensure_admin_account(self) -> User:
        """Ensure built-in admin account exists."""
        admin_email = "admin@admin.com"
        admin_password = "admin"

        admin = await self.get_by_email(admin_email)
        if admin:
            return admin

        admin = User(
            email=admin_email,
            username="admin",
            password_hash=get_password_hash(admin_password),
            is_active=True,
            is_verified=True,
        )

        self.db.add(admin)
        await self.db.commit()
        await self.db.refresh(admin)

        logger.warning(f"Auto-created built-in admin account: {admin_email}")
        return admin
