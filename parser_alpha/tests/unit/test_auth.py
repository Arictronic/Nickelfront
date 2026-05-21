"""
Тесты для авторизации и аутентификации.

Тестируемые endpoints:
- POST /api/v1/auth/register
- POST /api/v1/auth/login
- POST /api/v1/auth/logout
- GET /api/v1/auth/me
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient, test_db: AsyncSession):
    """Тест регистрации пользователя."""
    user_data = {
        "email": "test@example.com",
        "password": "TestPassword123!",
        "username": "testuser",
    }
    
    response = await client.post("/api/v1/auth/register", json=user_data)
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == user_data["email"]
    assert data["username"] == user_data["username"]
    assert "id" in data
    assert "password" not in data  # Пароль не должен возвращаться


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_db: AsyncSession):
    """Тест регистрации с дублирующимся email."""
    user_data = {
        "email": "duplicate@example.com",
        "password": "TestPassword123!",
        "username": "testuser1",
    }
    
    # Первая регистрация
    response1 = await client.post("/api/v1/auth/register", json=user_data)
    assert response1.status_code == 201
    
    # Вторая регистрация с тем же email
    response2 = await client.post("/api/v1/auth/register", json=user_data)
    assert response2.status_code == 400  # Конфликт


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient, test_db: AsyncSession):
    """Тест регистрации со слабым паролем."""
    user_data = {
        "email": "weak@example.com",
        "password": "123",  # Слишком короткий
        "username": "testuser",
    }
    
    response = await client.post("/api/v1/auth/register", json=user_data)
    assert response.status_code == 422  # Ошибка валидации


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient, test_db: AsyncSession):
    """Тест входа пользователя."""
    # Сначала регистрируемся
    register_data = {
        "email": "login@example.com",
        "password": "TestPassword123!",
        "username": "loginuser",
    }
    await client.post("/api/v1/auth/register", json=register_data)
    
    # Теперь входим
    login_data = {
        "email": "login@example.com",
        "password": "TestPassword123!",
    }
    
    response = await client.post("/api/v1/auth/login", json=login_data)
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_db: AsyncSession):
    """Тест входа с неправильным паролем."""
    # Сначала регистрируемся
    register_data = {
        "email": "wrong@example.com",
        "password": "TestPassword123!",
        "username": "wronguser",
    }
    await client.post("/api/v1/auth/register", json=register_data)
    
    # Вход с неправильным паролем
    login_data = {
        "email": "wrong@example.com",
        "password": "WrongPassword!",
    }
    
    response = await client.post("/api/v1/auth/login", json=login_data)
    assert response.status_code == 401  # Неверные учетные данные


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient, test_db: AsyncSession):
    """Тест получения текущего пользователя."""
    # Регистрируемся и входим
    register_data = {
        "email": "current@example.com",
        "password": "TestPassword123!",
        "username": "currentuser",
    }
    await client.post("/api/v1/auth/register", json=register_data)
    
    login_data = {
        "email": "current@example.com",
        "password": "TestPassword123!",
    }
    login_response = await client.post("/api/v1/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Получаем текущего пользователя
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "current@example.com"
    assert data["username"] == "currentuser"


@pytest.mark.asyncio
async def test_get_current_user_unauthorized(client: AsyncClient, test_db: AsyncSession):
    """Тест получения текущего пользователя без авторизации."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code in [401, 403]  # Неавторизован


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, test_db: AsyncSession):
    """Тест выхода."""
    # Регистрируемся и входим
    register_data = {
        "email": "logout@example.com",
        "password": "TestPassword123!",
        "username": "logoutuser",
    }
    await client.post("/api/v1/auth/register", json=register_data)
    
    login_data = {
        "email": "logout@example.com",
        "password": "TestPassword123!",
    }
    login_response = await client.post("/api/v1/auth/login", json=login_data)
    token = login_response.json()["access_token"]
    
    # Выход
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post("/api/v1/auth/logout", headers=headers)
    
    assert response.status_code == 200
    
    # Проверяем, что refresh-токен отозван
    refresh_token = login_response.json().get("refresh_token")
    refresh_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 401


@pytest.mark.asyncio
async def test_jwt_token_format(client: AsyncClient, test_db: AsyncSession):
    """Тест формата JWT токена."""
    register_data = {
        "email": "jwt@example.com",
        "password": "TestPassword123!",
        "username": "jwtuser",
    }
    await client.post("/api/v1/auth/register", json=register_data)
    
    login_data = {
        "email": "jwt@example.com",
        "password": "TestPassword123!",
    }
    response = await client.post("/api/v1/auth/login", json=login_data)
    
    data = response.json()
    assert "access_token" in data
    
    # JWT токен состоит из трех частей, разделенных точками
    token = data["access_token"]
    parts = token.split(".")
    assert len(parts) == 3


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient, test_db: AsyncSession):
    """Тест регистрации с невалидным email."""
    user_data = {
        "email": "invalid-email",  # Нет @
        "password": "TestPassword123!",
        "username": "testuser",
    }
    
    response = await client.post("/api/v1/auth/register", json=user_data)
    assert response.status_code == 422  # Ошибка валидации
