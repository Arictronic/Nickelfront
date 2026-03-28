"""
Qwen Service Client - Клиент для тестирования Qwen Service
Запускается как обычный Python скрипт для проверки работы сервиса

Настройки загружаются из переменных окружения (.env в корне проекта):
- QWEN_SERVICE_HOST - хост (по умолчанию 127.0.0.1)
- QWEN_SERVICE_PORT - порт (по умолчанию 8767)
- QWEN_API_KEY - API ключ (по умолчанию qwen-service-key-2026)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

import httpx

# Загрузка из .env
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Конфигурация из переменных окружения
SERVICE_URL = f"http://{os.getenv('QWEN_SERVICE_HOST', '127.0.0.1')}:{os.getenv('QWEN_SERVICE_PORT', '8767')}"
API_KEY = os.getenv("QWEN_API_KEY", "qwen-service-key-2026")


class QwenServiceClient:
    """Клиент для работы с Qwen Service"""

    def __init__(self, base_url: str = SERVICE_URL, api_key: str = API_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.current_session_id: str | None = None

    def _request(self, method: str, endpoint: str, **kwargs):
        """Внутренний метод для HTTP запросов"""
        url = f"{self.base_url}{endpoint}"
        with httpx.Client(timeout=60.0) as client:
            response = client.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            return response.json()

    def health_check(self) -> dict:
        """Проверка доступности сервиса"""
        return self._request("GET", "/health")

    def get_config(self) -> dict:
        """Получение конфигурации"""
        return self._request("GET", "/config")

    def set_token(self, token: str) -> dict:
        """Установка токена Qwen"""
        return self._request("POST", "/config/token", json={"token": token})

    def set_api_key(self, api_key: str) -> dict:
        """Установка API ключа"""
        return self._request("POST", "/config/api_key", json={"api_key": api_key})

    def get_model(self) -> dict:
        """Получение текущей модели"""
        return self._request("GET", "/config/model")

    def set_model(self, model: str, thinking_enabled: bool = True, search_enabled: bool = True) -> dict:
        """Настройка модели"""
        return self._request(
            "POST",
            "/config/model",
            json={"model": model, "thinking_enabled": thinking_enabled, "search_enabled": search_enabled},
        )

    def list_models(self) -> dict:
        """Получение списка моделей"""
        return self._request("GET", "/models")

    def create_session(self) -> dict:
        """Создание новой сессии"""
        result = self._request("POST", "/sessions")
        self.current_session_id = result.get("session_id")
        return result

    def list_sessions(self) -> dict:
        """Получение списка сессий"""
        return self._request("GET", "/sessions")

    def get_session(self, session_id: str) -> dict:
        """Получение информации о сессии"""
        return self._request("GET", f"/sessions/{session_id}")

    def delete_session(self, session_id: str) -> dict:
        """Удаление сессии"""
        return self._request("DELETE", f"/sessions/{session_id}")

    def rename_session(self, session_id: str, title: str) -> dict:
        """Переименование сессии"""
        return self._request("POST", f"/sessions/{session_id}/rename", json={"title": title})

    def send_message(
        self,
        message: str,
        session_id: Optional[str] = None,
        thinking_enabled: bool = True,
        search_enabled: bool = True,
        file_ids: Optional[List[str]] = None,
        auto_continue: Optional[bool] = None,
    ) -> dict:
        """Отправка сообщения"""
        sid = session_id or self.current_session_id
        if not sid:
            raise ValueError("Не указан session_id")

        payload = {
            "session_id": sid,
            "message": message,
            "thinking_enabled": thinking_enabled,
            "search_enabled": search_enabled,
            "file_ids": file_ids or [],
        }
        if auto_continue is not None:
            payload["auto_continue"] = auto_continue

        return self._request(
            "POST",
            "/messages",
            json=payload,
        )

    def continue_message(self, session_id: str, message_id: int, thinking_enabled: bool = True) -> dict:
        """Продолжение ответа"""
        return self._request(
            "POST",
            "/messages/continue",
            json={"session_id": session_id, "message_id": message_id, "thinking_enabled": thinking_enabled},
        )

    def upload_file(self, file_path: str) -> dict:
        """Загрузка файла"""
        return self._request("POST", "/files/upload", json={"file_path": file_path})

    def get_file(self, file_id: str) -> dict:
        """Получение информации о файле"""
        return self._request("GET", f"/files/{file_id}")

    def get_user_info(self) -> dict:
        """Получение информации о пользователе"""
        return self._request("GET", "/user/info")

    def get_auto_continue_config(self) -> dict:
        """Получение настроек авто-продолжения"""
        return self._request("GET", "/config/auto_continue")

    def set_auto_continue_config(self, enabled: bool, max_continues: Optional[int] = None) -> dict:
        """Настройка авто-продолжения"""
        params = {"enabled": str(enabled).lower()}
        if max_continues is not None:
            params["max_continues"] = str(max_continues)
        return self._request("POST", f"/config/auto_continue?{'&'.join(f'{k}={v}' for k, v in params.items())}")


def print_separator(title: str = ""):
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)


def test_service():
    """Тестирование сервиса"""
    print_separator("QWEN SERVICE CLIENT - ТЕСТИРОВАНИЕ")

    client = QwenServiceClient()

    # 1. Проверка здоровья
    print("\n[1] Проверка здоровья сервиса...")
    try:
        health = client.health_check()
        print(f"✓ Статус: {health.get('status')}")
        print(f"✓ Модель: {health.get('model')}")
    except httpx.HTTPError as e:
        print(f"✗ Ошибка подключения: {e}")
        print("\nСервис не запущен! Запустите: python service.py")
        return

    # 2. Получение конфигурации
    print_separator("[2] Конфигурация сервиса")
    config = client.get_config()
    print(f"Модель: {config.get('model')}")
    print(f"Режим мышления: {config.get('thinking_enabled')}")
    print(f"Поиск в интернете: {config.get('search_enabled')}")
    print(f"Токен установлен: {config.get('has_token')}")
    print(f"API ключ установлен: {config.get('has_api_key')}")

    # 3. Список моделей
    print_separator("[3] Доступные модели")
    try:
        models_response = client.list_models()
        models = models_response.get("models", [])
        print(f"Найдено моделей: {len(models)}")
        for model in models[:5]:  # Показываем первые 5
            print(f"  - {model.get('name', model.get('id', 'N/A'))}")
    except Exception as e:
        print(f"Ошибка получения моделей: {e}")

    # 4. Создание сессии
    print_separator("[4] Создание новой сессии")
    session = client.create_session()
    session_id = session.get("session_id")
    print(f"✓ Сессия создана: {session_id}")
    print(f"✓ Заголовок: {session.get('title')}")

    # 5. Отправка сообщения
    print_separator("[5] Отправка сообщения")
    print("Вопрос: 'Привет! Напиши краткий пример функции на Python для вычисления Фибоначчи.'")

    start_time = time.time()
    response = client.send_message(
        message="Привет! Напиши краткий пример функции на Python для вычисления Фибоначчи.",
        session_id=session_id,
        thinking_enabled=True,
        search_enabled=False,
    )
    elapsed = time.time() - start_time

    thinking = response.get("thinking", "")
    answer = response.get("response", "")

    if thinking:
        print(f"\n🧠 Режим мышления ({len(thinking)} символов):")
        print(f"   {thinking[:200]}..." if len(thinking) > 200 else f"   {thinking}")

    print(f"\n📝 Ответ ({len(answer)} символов, {elapsed:.2f} сек):")
    print("-" * 60)
    print(answer[:500] if len(answer) > 500 else answer)
    print("-" * 60)

    # 6. Переименование сессии
    print_separator("[6] Переименование сессии")
    rename_result = client.rename_session(session_id, "Пример Фибоначчи")
    print(f"✓ Сессия переименована: {rename_result.get('title')}")

    # 7. Список сессий
    print_separator("[7] Список сессий")
    sessions_response = client.list_sessions()
    sessions = sessions_response.get("sessions", [])
    print(f"Всего сессий: {len(sessions)}")
    for s in sessions[:3]:
        print(f"  - {s.get('title', 'N/A')} ({s.get('id', 'N/A')[:8]}...)")

    # 8. Информация о пользователе
    print_separator("[8] Информация о пользователе")
    user_info = client.get_user_info()
    info = user_info.get("user_info", {})
    if info:
        print(f"ID: {info.get('id', 'N/A')}")
        print(f"Display Name: {info.get('displayName', 'N/A')}")
        print(f"Email: {info.get('email', 'N/A')}")
    else:
        print("Информация недоступна")

    # 9. Тестирование режима с поиском
    print_separator("[9] Тест с поиском в интернете")
    print("Вопрос: 'Какие последние новости о Python 3.12?'")

    response_search = client.send_message(
        message="Какие последние новости о Python 3.12?",
        session_id=session_id,
        thinking_enabled=False,
        search_enabled=True,
    )

    answer_search = response_search.get("response", "")
    print(f"\n📝 Ответ с поиском ({len(answer_search)} символов):")
    print("-" * 60)
    print(answer_search[:400] if len(answer_search) > 400 else answer_search)
    print("-" * 60)

    # Итоги
    print_separator("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print(f"Сессия: {session_id}")
    print(f"Всего сообщений отправлено: 2")
    print(f"Сервис работает корректно!")
    print("\nДля остановки сервиса нажмите Ctrl+C в терминале где запущен service.py")


def interactive_mode():
    """Интерактивный режим чата"""
    print_separator("QWEN SERVICE CLIENT - ИНТЕРАКТИВНЫЙ ЧАТ")

    client = QwenServiceClient()

    # Проверка подключения
    try:
        client.health_check()
    except httpx.HTTPError:
        print("Сервис не запущен! Запустите: python service.py")
        return

    # Создание или выбор сессии
    print("\nСоздание новой сессии...")
    session = client.create_session()
    session_id = session.get("session_id")
    print(f"Сессия: {session_id}")

    print("\n" + "=" * 60)
    print("Режим чата активирован!")
    print("Команды:")
    print("  /exit - выход")
    print("  /new - новая сессия")
    print("  /think on|off - режим мышления")
    print("  /search on|off - поиск в интернете")
    print("=" * 60 + "\n")

    thinking_enabled = True
    search_enabled = False

    while True:
        try:
            user_input = input("Вы: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nВыход из чата...")
            break

        if not user_input:
            continue

        # Команды
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].lower() if len(parts) > 1 else ""

            if cmd == "/exit":
                print("Выход...")
                break
            elif cmd == "/new":
                session = client.create_session()
                session_id = session.get("session_id")
                print(f"✓ Новая сессия: {session_id}")
            elif cmd == "/think":
                thinking_enabled = arg in ("on", "1", "true", "вкл")
                print(f"✓ Режим мышления: {'включен' if thinking_enabled else 'выключен'}")
            elif cmd == "/search":
                search_enabled = arg in ("on", "1", "true", "вкл")
                print(f"✓ Поиск: {'включен' if search_enabled else 'выключен'}")
            else:
                print(f"Неизвестная команда: {cmd}")
            continue

        # Отправка сообщения
        print("\nQwen печатает...")
        try:
            response = client.send_message(
                message=user_input,
                session_id=session_id,
                thinking_enabled=thinking_enabled,
                search_enabled=search_enabled,
            )

            thinking = response.get("thinking", "")
            answer = response.get("response", "")

            if thinking:
                print(f"\n🧠 {thinking[:300]}..." if len(thinking) > 300 else f"\n🧠 {thinking}")

            print(f"\n{answer}\n")

        except Exception as e:
            print(f"Ошибка: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--chat":
        interactive_mode()
    else:
        test_service()
