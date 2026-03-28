# Тестирование RAG функционала

## ✅ Сервер запущен

Backend доступен на: http://localhost:8001

---

## 📖 Способы тестирования

### Способ 1: Swagger UI (рекомендуется)

1. Откройте http://localhost:8001/docs
2. Найдите секцию **rag**
3. Тестируйте endpoints:

#### 1. Загрузка PDF
- **Endpoint:** `POST /api/v1/rag/upload`
- **Нажмите:** "Try it out"
- **Выберите файл:** patent.pdf (любой PDF)
- **Execute**

**Пример ответа:**
```json
{
  "message": "Файл успешно загружен и обработан",
  "filename": "patent.pdf",
  "documents_count": 15,
  "chunks_count": 15
}
```

#### 2. Вопрос по документам
- **Endpoint:** `POST /api/v1/rag/ask`
- **Нажмите:** "Try it out"
- **Введите вопрос:**
```json
{
  "question": "Какой состав у сплава ХН77ТЮР?",
  "include_sources": true
}
```
- **Execute**

**Пример ответа:**
```json
{
  "answer": "Сплав ХН77ТЮР содержит: Ni (55-60%), Cr (19-22%)...",
  "question": "Какой состав у сплава ХН77ТЮР?",
  "sources": [...],
  "documents_found": 4
}
```

#### 3. Статистика
- **Endpoint:** `GET /api/v1/rag/stats`
- **Нажмите:** "Try it out" → "Execute"

---

### Способ 2: curl (командная строка)

**1. Загрузка PDF:**
```bat
curl -X POST "http://localhost:8001/api/v1/rag/upload" ^
  -F "file=@C:\path\to\patent.pdf"
```

**2. Вопрос:**
```bat
curl -X POST "http://localhost:8001/api/v1/rag/ask" ^
  -H "Content-Type: application/json" ^
  -d "{\"question\": \"Какой состав у сплава ХН77ТЮР?\", \"include_sources\": true}"
```

**3. Статистика:**
```bat
curl http://localhost:8001/api/v1/rag/stats
```

---

### Способ 3: Python скрипт

Создайте `test_rag.py`:

```python
import requests

BASE_URL = "http://localhost:8001"

# 1. Загрузка PDF
print("=== Загрузка PDF ===")
with open("patent.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/api/v1/rag/upload",
        files={"file": f}
    )
    print(response.json())

# 2. Вопрос
print("\n=== Вопрос ===")
response = requests.post(
    f"{BASE_URL}/api/v1/rag/ask",
    json={
        "question": "Какой состав у сплава ХН77ТЮР?",
        "include_sources": True
    }
)
print(response.json())

# 3. Статистика
print("\n=== Статистика ===")
response = requests.get(f"{BASE_URL}/api/v1/rag/stats")
print(response.json())
```

Запуск:
```bat
python test_rag.py
```

---

## 🧪 Тестовые файлы

Для тестирования можно использовать PDF файлы из папки `rag/` (если есть) или любые другие патенты.

**Примеры вопросов для теста:**
- "Какой состав у сплава ХН77ТЮР?"
- "Какие свойства у жаропрочных сплавов?"
- "Какая температура закалки для сплава ЭИ437Б?"

---

## 🔍 Проверка Qwen чата

**Swagger UI:**
1. Откройте http://localhost:8001/docs
2. Найдите секцию **qwen-chat**
3. `POST /api/v1/qwen/messages`

**curl:**
```bat
curl -X POST "http://localhost:8001/api/v1/qwen/messages" ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"Привет! Расскажи о никелевых сплавах.\"}"
```

---

## 📊 Endpoints

| Endpoint | Описание |
|----------|----------|
| `POST /api/v1/rag/upload` | Загрузить PDF |
| `POST /api/v1/rag/ask` | Задать вопрос |
| `GET /api/v1/rag/stats` | Статистика RAG |
| `POST /api/v1/rag/clear` | Очистить хранилище |
| `POST /api/v1/qwen/messages` | Чат с Qwen |
| `GET /api/v1/qwen/health` | Проверка Qwen |

---

## ⚠️ Возможные ошибки

### "Qwen Service недоступен"
**Решение:** Запустите `run_qwen_service.bat` в отдельном окне

### "Векторное хранилище не инициализировано"
**Решение:** Проверьте что `EMBEDDING_MODEL` доступен

### "Не удалось извлечь текст из PDF"
**Решение:** Убедитесь что PDF содержит текст (не сканы)
