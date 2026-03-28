"""Скрипт для очистки базы данных."""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.db.session import async_session_maker, engine
from app.db.models import Paper, User
from app.db.base import Base


async def clean_db():
    """Очистить базу данных."""
    async with async_session_maker() as db:
        try:
            # Удаляем все статьи
            result = await db.execute(delete(Paper))
            papers_count = result.rowcount
            await db.commit()
            print(f"Удалено статей: {papers_count}")

            # Удаляем всех пользователей кроме админа (id=1)
            result = await db.execute(delete(User).where(User.id != 1))
            users_count = result.rowcount
            await db.commit()
            print(f"Удалено пользователей: {users_count}")

            # Сбрасываем последовательности (для PostgreSQL)
            await db.execute(select(1))  # Проверка подключения

            print("\nБаза данных очищена!")

            # Проверка - сколько осталось
            result = await db.execute(select(User).where(User.id != 1))
            remaining_users = len(result.scalars().all())

            result = await db.execute(select(Paper))
            remaining_papers = len(result.scalars().all())

            print(f"\nОсталось в БД:")
            print(f"  - Пользователей (не включая админа): {remaining_users}")
            print(f"  - Статей: {remaining_papers}")

        except Exception as e:
            await db.rollback()
            print(f"Ошибка при очистке: {e}")
            raise


async def full_reset():
    """Полный сброс БД - удалить все таблицы и создать заново."""
    async with engine.begin() as conn:
        # Удаляем все таблицы
        await conn.run_sync(Base.metadata.drop_all)
        print("Все таблицы удалены")

        # Создаём таблицы заново
        await conn.run_sync(Base.metadata.create_all)
        print("Все таблицы созданы заново")


async def main():
    print("=== Очистка базы данных ===\n")
    print("Выберите действие:")
    print("1. Удалить все статьи и пользователей (кроме админа)")
    print("2. Полный сброс (удалить все таблицы и создать заново)")
    print("3. Только удалить все статьи")
    print()

    choice = input("Ваш выбор (1/2/3): ").strip()

    if choice == "1":
        await clean_db()
    elif choice == "2":
        confirm = input("\nВНИМАНИЕ! Это удалит ВСЕ данные включая админа. Продолжить? (yes/no): ").strip()
        if confirm.lower() == "yes":
            await full_reset()
            print("\nПолный сброс выполнен!")
        else:
            print("Отменено")
    elif choice == "3":
        async with async_session_maker() as db:
            result = await db.execute(delete(Paper))
            await db.commit()
            print(f"Удалено статей: {result.rowcount}")
    else:
        print("Неверный выбор")


if __name__ == "__main__":
    asyncio.run(main())
