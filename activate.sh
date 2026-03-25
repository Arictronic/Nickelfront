#!/bin/bash
# Скрипт активации виртуального окружения для Linux/macOS
# Использование: source activate.sh

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="$SCRIPT_DIR/venv"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    echo "✓ Виртуальное окружение активировано"
else
    echo "✗ Виртуальное окружение не найдено. Создайте:"
    echo "  python3 -m venv venv"
fi
