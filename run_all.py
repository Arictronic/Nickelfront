#!/usr/bin/env python3
"""
Единый скрипт для запуска всего проекта Nickelfront.

Запускает:
1. Redis (проверка наличия)
2. PostgreSQL (проверка наличия)
3. Backend (FastAPI, порт 8001)
4. Celery Worker
5. Frontend (Vite, порт 5173)
6. Flower (мониторинг Celery, опционально)

Использование:
    python run_all.py [--no-flower]

Автор: Nickelfront Team
Версия: 1.0.0
"""

import os
import sys
import time
import socket
import shutil
import signal
import argparse
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

# Порты
REDIS_PORT = 6380
POSTGRES_PORT = 5433
BACKEND_PORT = 8001
FRONTEND_PORT = 5173
FLOWER_PORT = 5555

# Пути к исполняемым файлам (Windows)
REDIS_SERVER = r"c:\Redis\redis-server.exe"
PGADMIN = r"C:\Program Files\PostgreSQL\16\pgAdmin 4\pgAdmin4.exe"

# Таймауты
STARTUP_DELAY = 3  # секунды между запуском компонентов
HEALTH_CHECK_TIMEOUT = 30  # секунд на проверку доступности сервиса

# =============================================================================
# УТИЛИТЫ
# =============================================================================


def log(message: str, level: str = "INFO") -> None:
    """Вывод сообщения с временной меткой."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    # Используем ASCII символы для совместимости с Windows консолью
    icons = {
        "INFO": "[*]",
        "SUCCESS": "[+]",
        "WARNING": "[!]",
        "ERROR": "[-]",
        "RESET": ""
    }
    icon = icons.get(level, icons["INFO"])
    try:
        print(f"[{timestamp}] {icon} {level}: {message}", flush=True)
    except UnicodeEncodeError:
        # Fallback для старых консолей
        print(f"[{timestamp}] {level}: {message}", flush=True)


def check_port_available(port: int) -> bool:
    """Проверка, свободен ли порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


def is_service_running(host: str, port: int, timeout: int = 2) -> bool:
    """Проверка доступности сервиса."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            return True
    except (socket.timeout, ConnectionRefusedError):
        return False


def check_python_version() -> bool:
    """Проверка версии Python."""
    required = (3, 9)
    current = sys.version_info[:2]
    if current < required:
        log(f"Требуется Python {required[0]}.{required[1]}+, у вас {current[0]}.{current[1]}", "ERROR")
        return False
    log(f"Python {sys.version.split()[0]} OK", "SUCCESS")
    return True


def check_node_installed() -> bool:
    """Проверка установки Node.js."""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            log(f"Node.js {result.stdout.strip()} OK", "SUCCESS")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    log("Node.js не найден. Установите Node.js 18+", "ERROR")
    return False


def check_redis_running() -> bool:
    """Проверка запущенного Redis."""
    if is_service_running("localhost", REDIS_PORT):
        log(f"Redis уже запущен на порту {REDIS_PORT} OK", "SUCCESS")
        return True
    
    # Проверка стандартного порта
    if is_service_running("localhost", 6379):
        log("Redis запущен на стандартном порту 6379 OK", "SUCCESS")
        return True
    
    log(f"Redis не найден (порт {REDIS_PORT} или 6379)", "WARNING")
    return False


def start_redis() -> Optional[subprocess.Popen]:
    """Запуск Redis сервера."""
    # Поиск redis-server в различных расположениях
    possible_paths = [
        REDIS_SERVER,
        r"C:\Program Files\Redis\redis-server.exe",
        r"C:\redis\redis-server.exe",
        shutil.which("redis-server")
    ]
    
    redis_path = None
    for path in possible_paths:
        if path and Path(path).exists():
            redis_path = path
            break
    
    if not redis_path:
        log("Redis сервер не найден", "WARNING")
        log("Celery будет работать в режиме solo (без брокера)", "WARNING")
        log("Для полноценной работы установите Redis: https://github.com/microsoftarchive/redis/releases", "WARNING")
        return None
    
    try:
        cmd = [str(redis_path), f"--port", str(REDIS_PORT)]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        log(f"Запуск Redis на порту {REDIS_PORT}...", "INFO")
        time.sleep(2)
        if check_redis_running():
            log("Redis успешно запущен OK", "SUCCESS")
            return proc
    except Exception as e:
        log(f"Ошибка запуска Redis: {e}", "ERROR")
    return None


def check_postgres_running() -> bool:
    """Проверка запущенного PostgreSQL."""
    if is_service_running("localhost", POSTGRES_PORT):
        log(f"PostgreSQL запущен на порту {POSTGRES_PORT} OK", "SUCCESS")
        return True
    
    # Проверка стандартного порта
    if is_service_running("localhost", 5432):
        log("PostgreSQL запущен на стандартном порту 5432 OK", "SUCCESS")
        return True
    
    log(f"PostgreSQL не найден на порту {POSTGRES_PORT}", "WARNING")
    return False


def setup_env_file() -> None:
    """Создание .env файла из .env.example если не существует."""
    env_file = ROOT_DIR / ".env"
    env_example = ROOT_DIR / ".env.example"
    
    if not env_file.exists() and env_example.exists():
        log("Создание .env файла из шаблона...", "INFO")
        shutil.copy(env_example, env_file)
        
        # Генерация секретного ключа
        try:
            import secrets
            secret_key = secrets.token_urlsafe(32)
            
            with open(env_file, "r", encoding="utf-8") as f:
                content = f.read()
            
            content = content.replace(
                "SECRET_KEY=your-secret-key-here",
                f"SECRET_KEY={secret_key}"
            )
            
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(content)
            
            log("Секретный ключ сгенерирован OK", "SUCCESS")
        except Exception as e:
            log(f"Предупреждение: не удалось сгенерировать ключ: {e}", "WARNING")
        
        log(".env файл создан. Настройте параметры подключения к БД!", "WARNING")
    elif env_file.exists():
        log(".env файл найден OK", "SUCCESS")


def install_backend_deps() -> bool:
    """Установка зависимостей backend."""
    log("Установка Python зависимостей...", "INFO")
    
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.exists():
        log("requirements.txt не найден", "ERROR")
        return False
    
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate(timeout=300)
        
        if proc.returncode == 0:
            log("Python зависимости установлены OK", "SUCCESS")
            return True
        else:
            log(f"Ошибка установки: {stderr.decode()[:200]}", "ERROR")
            return False
    except Exception as e:
        log(f"Ошибка: {e}", "ERROR")
        return False


def install_frontend_deps() -> bool:
    """Установка зависимостей frontend."""
    log("Установка Node.js зависимостей...", "INFO")
    
    package_json = FRONTEND_DIR / "package.json"
    if not package_json.exists():
        log("package.json не найден", "ERROR")
        return False
    
    try:
        proc = subprocess.Popen(
            ["npm", "install"],
            cwd=str(FRONTEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = proc.communicate(timeout=600)
        
        if proc.returncode == 0:
            log("Node.js зависимости установлены OK", "SUCCESS")
            return True
        else:
            log(f"Ошибка установки: {stderr.decode()[:200]}", "ERROR")
            return False
    except Exception as e:
        log(f"Ошибка: {e}", "ERROR")
        return False


def check_backend_deps(auto_install: bool = False) -> bool:
    """Проверка установленных зависимостей backend."""
    deps = ["fastapi", "uvicorn", "celery", "redis", "sqlalchemy"]
    missing = []
    
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
        except ImportError:
            missing.append(dep)
    
    if missing:
        log(f"Отсутствуют Python пакеты: {', '.join(missing)}", "WARNING")
        if auto_install:
            return install_backend_deps()
        log("Запустите с --install для автоматической установки", "INFO")
        return False
    
    log("Python зависимости установлены OK", "SUCCESS")
    return True


def check_frontend_deps(auto_install: bool = False) -> bool:
    """Проверка установленных зависимостей frontend."""
    node_modules = FRONTEND_DIR / "node_modules"
    
    if not node_modules.exists():
        log("Frontend зависимости не найдены", "WARNING")
        if auto_install:
            return install_frontend_deps()
        log("Запустите с --install для автоматической установки", "INFO")
        return False
    
    log("Frontend зависимости установлены OK", "SUCCESS")
    return True


# =============================================================================
# ПРОЦЕССЫ
# =============================================================================


class ProcessManager:
    """Менеджер процессов для graceful shutdown."""
    
    def __init__(self):
        self.processes: list[subprocess.Popen] = []
        self.running = True
        
        # Обработчики сигналов
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов завершения."""
        log("\nПолучен сигнал завершения...", "WARNING")
        self.running = False
        self.shutdown()
    
    def add_process(self, proc: subprocess.Popen, name: str) -> None:
        """Добавление процесса."""
        self.processes.append((proc, name))
        log(f"Запущен процесс: {name}", "INFO")
    
    def shutdown(self) -> None:
        """Завершение всех процессов."""
        log("Завершение работы...", "INFO")
        
        for proc, name in reversed(self.processes):
            try:
                if proc.poll() is None:
                    log(f"Остановка {name}...", "INFO")
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception as e:
                log(f"Ошибка остановки {name}: {e}", "ERROR")
        
        log("Все процессы остановлены", "SUCCESS")


def start_backend(manager: ProcessManager) -> None:
    """Запуск Backend сервера."""
    log("Запуск Backend (FastAPI)...", "INFO")
    
    # Проверка порта
    if not check_port_available(BACKEND_PORT):
        log(f"Порт {BACKEND_PORT} занят. Backend не будет запущен.", "ERROR")
        return
    
    # Создание .env если нужно
    backend_env = BACKEND_DIR / ".env"
    if not backend_env.exists():
        root_env = ROOT_DIR / ".env"
        if root_env.exists():
            shutil.copy(root_env, backend_env)
    
    cmd = [
        sys.executable,
        str(BACKEND_DIR / "start_server.py")
    ]
    
    try:
        # Запускаем в том же окне для видимости логов
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        manager.add_process(proc, f"Backend (порт {BACKEND_PORT})")
        
        # Ожидание запуска
        for _ in range(HEALTH_CHECK_TIMEOUT):
            if is_service_running("localhost", BACKEND_PORT):
                log(f"Backend доступен на http://localhost:{BACKEND_PORT} OK", "SUCCESS")
                log(f"Swagger UI: http://localhost:{BACKEND_PORT}/docs", "INFO")
                break
            time.sleep(1)
    except Exception as e:
        log(f"Ошибка запуска Backend: {e}", "ERROR")


def start_celery_worker(manager: ProcessManager) -> None:
    """Запуск Celery Worker."""
    log("Запуск Celery Worker...", "INFO")
    
    # Проверка Redis
    if not check_redis_running():
        log("Redis не запущен. Пропуск Celery Worker.", "WARNING")
        log("Для работы Celery установите и запустите Redis.", "WARNING")
        return
    
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.tasks.celery_app",
        "worker",
        "--loglevel=info",
        "--pool=solo"  # Для Windows
    ]
    
    try:
        # Запускаем в том же окне для видимости логов
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        manager.add_process(proc, "Celery Worker")
        time.sleep(STARTUP_DELAY)
    except Exception as e:
        log(f"Ошибка запуска Celery Worker: {e}", "ERROR")


def start_flower(manager: ProcessManager) -> None:
    """Запуск Flower (мониторинг Celery)."""
    # Проверка Redis
    if not check_redis_running():
        log("Redis не запущен. Пропуск Flower.", "WARNING")
        return
    
    log("Запуск Flower (мониторинг)...", "INFO")
    
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.tasks.celery_app",
        "flower",
        f"--port={FLOWER_PORT}"
    ]
    
    try:
        # Запускаем в том же окне для видимости логов
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            env={**os.environ, "PYTHONUNBUFFERED": "1"}
        )
        manager.add_process(proc, f"Flower (порт {FLOWER_PORT})")
        
        # Ожидание запуска
        for _ in range(10):
            if is_service_running("localhost", FLOWER_PORT):
                log(f"Flower доступен на http://localhost:{FLOWER_PORT} OK", "SUCCESS")
                break
            time.sleep(1)
    except Exception as e:
        log(f"Ошибка запуска Flower: {e}", "ERROR")


def start_frontend(manager: ProcessManager) -> None:
    """Запуск Frontend сервера."""
    log("Запуск Frontend (Vite)...", "INFO")

    # Проверка порта
    if not check_port_available(FRONTEND_PORT):
        log(f"Порт {FRONTEND_PORT} занят. Frontend не будет запущен.", "ERROR")
        return

    try:
        cmd = ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", str(FRONTEND_PORT)]
        # Запускаем в том же окне для видимости логов
        proc = subprocess.Popen(
            cmd,
            cwd=str(FRONTEND_DIR)
        )
        manager.add_process(proc, f"Frontend (порт {FRONTEND_PORT})")

        # Ожидание запуска
        for _ in range(HEALTH_CHECK_TIMEOUT):
            if is_service_running("localhost", FRONTEND_PORT):
                log(f"Frontend доступен на http://localhost:{FRONTEND_PORT} OK", "SUCCESS")
                break
            time.sleep(1)
    except Exception as e:
        log(f"Ошибка запуска Frontend: {e}", "ERROR")


# =============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================================================


def main():
    """Точка входа."""
    parser = argparse.ArgumentParser(
        description="Запуск всего проекта Nickelfront",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python run_all.py              # Запуск всего
  python run_all.py --no-flower  # Без Flower
  python run_all.py --backend-only  # Только backend
  python run_all.py --install    # Сначала установить зависимости
        """
    )
    parser.add_argument(
        "--no-flower",
        action="store_true",
        help="Не запускать Flower"
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Запустить только Backend и Worker"
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Не открывать новые окна (все в консоли)"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Сначала установить зависимости"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Автоматически подтверждать установку"
    )
    
    args = parser.parse_args()

    # Заголовок
    print("\n" + "=" * 60)
    print("  NICKELFRONT - Запуск проекта")
    print("  Платформа для анализа научных статей")
    print("=" * 60 + "\n")

    # Проверки
    log("Проверка зависимостей...", "INFO")

    checks_passed = True

    if not check_python_version():
        checks_passed = False

    if not args.backend_only and not check_node_installed():
        checks_passed = False

    if not check_backend_deps(auto_install=args.install):
        checks_passed = False

    if not args.backend_only and not check_frontend_deps(auto_install=args.install):
        checks_passed = False

    if not checks_passed:
        log("\nНе все проверки пройдены. Установите зависимости и повторите.", "ERROR")
        log("\nКоманды для установки:", "INFO")
        log("  pip install -r backend/requirements.txt", "INFO")
        if not args.backend_only:
            log("  cd frontend && npm install", "INFO")
        sys.exit(1)
    
    # Проверка сервисов
    log("\nПроверка сервисов...", "INFO")
    
    if not check_redis_running():
        start_redis()
        time.sleep(STARTUP_DELAY)
    
    if not check_postgres_running():
        log("PostgreSQL не запущен. Запустите вручную или через Docker.", "WARNING")
        log("Ожидание 10 секунд на ручной запуск...", "WARNING")
        time.sleep(10)
    
    # Создание .env
    setup_env_file()
    
    # Запуск процессов
    manager = ProcessManager()
    
    try:
        # Backend
        start_backend(manager)
        time.sleep(STARTUP_DELAY)
        
        # Celery Worker
        start_celery_worker(manager)
        time.sleep(STARTUP_DELAY)
        
        # Flower (опционально)
        if not args.no_flower and not args.backend_only:
            start_flower(manager)
            time.sleep(STARTUP_DELAY)
        
        # Frontend (опционально)
        if not args.backend_only:
            start_frontend(manager)
        
        # Информация
        print("\n" + "=" * 60)
        log("ПРОЕКТ ЗАПУЩЕН!", "SUCCESS")
        print("=" * 60)
        print(f"\n  Frontend:  http://localhost:{FRONTEND_PORT}")
        print(f"  Backend:   http://localhost:{BACKEND_PORT}")
        print(f"  Swagger:   http://localhost:{BACKEND_PORT}/docs")
        if not args.no_flower and not args.backend_only:
            print(f"  Flower:    http://localhost:{FLOWER_PORT}")
        print("\n  Нажмите Ctrl+C для остановки всех сервисов\n")
        print("=" * 60 + "\n")
        
        # Ожидание завершения
        while manager.running:
            time.sleep(1)
    
    except KeyboardInterrupt:
        log("Получен сигнал прерывания", "WARNING")
    finally:
        manager.shutdown()
    
    log("Работа завершена", "SUCCESS")


if __name__ == "__main__":
    main()
