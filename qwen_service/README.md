# Nickelfront Qwen Service

Локальный сервис-интеграция Nickelfront с Qwen Chat.

Сервис умеет:

- отправлять обычные текстовые сообщения в Qwen;
- загружать файлы в Qwen через настоящий browser-session pipeline;
- отправлять prompt вместе с одним или несколькими файлами;
- работать с текстовыми файлами, PDF, изображениями и другими типами, которые принимает Qwen;
- использовать HAR-файл из обычного браузера для обновления `Cookie`, `bx-*`, `User-Agent` и шаблонов файловых API-запросов.

---

## 1. Архитектура

Файловая загрузка Qwen — это не один запрос. Реальный pipeline:

```text
1. POST /api/v2/files/getstsToken
   Получаем file_id, file_path, bucket, endpoint, region и временные STS credentials.

2. PUT в Aliyun OSS
   Загружаем файл напрямую в объектное хранилище.
   Используется STS header-signing:
   Authorization: OSS4-HMAC-SHA256
   x-oss-security-token
   x-oss-date
   x-oss-content-sha256: UNSIGNED-PAYLOAD

3. POST /api/v2/files/parse
   Запускаем парсинг файла.

4. POST /api/v2/files/parse/status
   Поллим статус до success.

5. POST /api/v2/chat/completions
   Отправляем prompt + полный files[] объект.
```

Текстовый чат использует обычный Bearer-токен.

Файловые endpoints дополнительно требуют browser-session headers:

```text
Cookie
bx-ua
bx-umidtoken
bx-v
User-Agent
```

---

## 2. Основные файлы сервиса

```text
qwen_service/
├─ service.py                         FastAPI-сервис
├─ qwen_api.py                        Основной Qwen transport/client
├─ client.py                          Python client для qwen_service
├─ har_token_scanner.py               Извлечение token/session данных из HAR
├─ har/                               Папка для HAR-файлов
│  ├─ README.md
│  └─ *.har
└─ scripts/
   ├─ run_qwen_service.bat            Запуск сервиса
   ├─ run_qwen_upload_probe.bat       Диагностический launcher
   ├─ test_qwen_file_upload.py        Probe-скрипт
   ├─ qwen_upload_probe.txt           Тестовый TXT-файл
   └─ test.pdf                        Тестовый PDF-файл, если нужен
```

---

## 3. Минимальный `.env`

Ниже пример структуры. Не коммить реальные значения.

```env
# Base auth
QWEN_API_KEY=your-local-service-key
QWEN_TOKEN=your-qwen-bearer-token

# Browser-session layer for file endpoints
QWEN_COOKIE=
QWEN_BX_UA=
QWEN_BX_UMIDTOKEN=
QWEN_BX_V=
QWEN_USER_AGENT=

# File upload runtime
QWEN_FILE_UPLOAD_MODE=auto
QWEN_FILE_UPLOAD_MAX_SIZE_MB=20

# Session source
QWEN_SESSION_SOURCE=har
QWEN_HAR_DIR=qwen_service/har

# Qwen file API templates captured from HAR
QWEN_FILE_API_EXTRA_HEADERS_JSON=
QWEN_FILE_STS_PAYLOAD_TEMPLATE_JSON=
QWEN_FILE_STS_URL=https://chat.qwen.ai/api/v2/files/getstsToken
QWEN_FILE_PARSE_PAYLOAD_TEMPLATE_JSON=
QWEN_FILE_PARSE_URL=https://chat.qwen.ai/api/v2/files/parse
QWEN_FILE_PARSE_STATUS_PAYLOAD_TEMPLATE_JSON=
QWEN_FILE_PARSE_STATUS_URL=https://chat.qwen.ai/api/v2/files/parse/status
```

### Что можно не хранить

После финализации upload pipeline не нужны в боевом `.env`:

```env
QWEN_OSS_PUT_HEADERS_TEMPLATE_JSON=
QWEN_OSS_PUT_MODE=
QWEN_OSS_PUT_INCLUDE_CONTENT_TYPE=
```

OSS upload теперь строится из live `getstsToken` response и использует STS header-signing.

Playwright/CDP-переменные тоже можно убрать, если используется только HAR-сценарий:

```env
QWEN_PLAYWRIGHT_ENABLED=false
QWEN_BROWSER_LOGIN_AUTOMATION=false
QWEN_BROWSER_PROFILE_DIR=qwen_service/.browser/qwen
QWEN_BROWSER_HEADLESS=false
QWEN_BROWSER_CHANNEL=chrome
QWEN_BROWSER_REFRESH_TIMEOUT_SEC=120.0
QWEN_CDP_URL=http://127.0.0.1:9222
```

---

## 4. Как получить HAR

HAR нужен, чтобы сервис получил реальные browser-session headers и шаблоны файловых API-запросов Qwen.

Правильный порядок:

1. Открыть `https://chat.qwen.ai` в обычном Chrome/Edge/Firefox.
2. Авторизоваться вручную.
3. Открыть DevTools → Network.
4. Включить:
   ```text
   Preserve log
   Disable cache
   ```
5. Очистить Network log.
6. Загрузить небольшой файл на сайте Qwen.
7. Дождаться, что файл обработался.
8. Убедиться, что в Network есть:
   ```text
   /api/v2/files/getstsToken
   PUT qwen-webui-prod.oss-accelerate.aliyuncs.com
   /api/v2/files/parse
   /api/v2/files/parse/status
   ```
9. Export HAR.
10. Положить HAR сюда:
    ```text
    qwen_service/har/
    ```

Если в HAR нет `/api/v2/files/*`, он не подходит для файловой загрузки.

---

## 5. Запуск сервиса

Из корня проекта:

```bat
cd /d D:\Project\Nickelfront
qwen_service\scripts\run_qwen_service.bat
```

Сервис поднимается на:

```text
http://127.0.0.1:8767
```

Порт должен быть свободен. Проверка:

```bat
netstat -ano | findstr :8767
```

---

## 6. Обновление session из HAR

После запуска сервиса:

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode har-refresh
```

Успешный результат должен содержать:

```text
has_qwen_cookie: true
has_qwen_bx_ua: true
has_qwen_bx_umidtoken: true
has_qwen_bx_v: true
has_qwen_user_agent: true
has_file_browser_session: true
has_file_sts_payload_template: true
has_file_parse_payload_template: true
has_file_parse_status_payload_template: true
```

Если `.env` заблокирован, может быть warning:

```text
env_saved: false
.env is locked, runtime session was updated but persistence failed
```

Это не мешает текущему runtime. Но после перезапуска сервиса session может не сохраниться.

---

## 7. Проверочные команды

### Health

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode health
```

### Проверка текстового чата

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode text
```

### Проверка загрузки TXT + prompt

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-and-send
```

Ожидаемо:

```text
Passed: YES
upload_attempts: 1
```

### Проверка двухшаговой загрузки TXT

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode two-step --sleep-after-upload 5
```

### Проверка PDF

Положить файл:

```text
qwen_service/scripts/test.pdf
```

Запуск:

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-pdf --pdf-file test.pdf
```

### Двухшаговая проверка PDF

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode pdf-two-step --pdf-file test.pdf --sleep-after-upload 5
```

### Универсальный файл

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-file --file test.pdf
```

Файл ищется относительно:

```text
qwen_service/scripts/
```

или по абсолютному пути, если указан абсолютный путь.

### Multi-file upload

До 5 файлов в одном сообщении:

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-multi --files qwen_upload_probe.txt,test.pdf
```

---

## 8. Ограничения

### Количество файлов

```text
Максимум: 5 файлов на одно сообщение
```

Если больше:

```text
qwen_too_many_files: maximum 5 files per message
```

### Размер файла

```text
Максимум: 20 МБ на файл
```

Настройка:

```env
QWEN_FILE_UPLOAD_MAX_SIZE_MB=20
```

Если файл больше:

```text
qwen_file_too_large
```

### Типы файлов

Pipeline универсальный. Тип определяется через `mimetypes`.

Поддерживаются все типы, которые принимает сам Qwen, например:

```text
.txt
.pdf
.png
.jpg
.jpeg
.webp
.doc
.docx
.xls
.xlsx
.csv
```

Если тип неизвестен:

```text
application/octet-stream
```

---

## 9. API endpoints

### Health

```http
GET /health
```

### Auth status

```http
GET /auth/status?force=true
```

### Обновить session из HAR-файла в папке

```http
POST /config/token/update-from-har-file?validate=false&require_file_api=true
```

### Посмотреть HAR-папку

```http
GET /config/har
```

### Загрузить один файл

```http
POST /files/upload
```

Тело:

```json
{
  "file_path": "qwen_service/scripts/test.pdf"
}
```

Ответ содержит:

```json
{
  "file_id": "...",
  "file_info": {
    "id": "...",
    "name": "test.pdf",
    "size": 977607,
    "content_type": "application/pdf",
    "parse_status": "success"
  }
}
```

### Загрузить файл и отправить prompt

```http
POST /files/upload-and-send
```

Один файл:

```json
{
  "file_path": "qwen_service/scripts/test.pdf",
  "message": "Прочитай файл и кратко перескажи"
}
```

Несколько файлов:

```json
{
  "file_paths": [
    "qwen_service/scripts/a.pdf",
    "qwen_service/scripts/b.png"
  ],
  "message": "Сравни эти файлы"
}
```

### Явный multi-file endpoint

```http
POST /files/upload-many
POST /files/upload-many-and-send
```

---

## 10. Python client

Пример:

```python
from qwen_service.client import QwenServiceClient

client = QwenServiceClient(base_url="http://127.0.0.1:8767")

result = client.upload_files_and_send_message(
    file_paths=[
        "qwen_service/scripts/test.pdf",
        "qwen_service/scripts/qwen_upload_probe.txt",
    ],
    message="Проанализируй оба файла и верни краткий JSON."
)

print(result["response"])
```

Один файл:

```python
result = client.upload_file_and_send_message(
    file_path="qwen_service/scripts/test.pdf",
    message="Кратко перескажи PDF."
)
```

---

## 11. Безопасность

Нельзя коммитить:

```text
QWEN_TOKEN
QWEN_COOKIE
QWEN_BX_UA
QWEN_BX_UMIDTOKEN
QWEN_BX_V
QWEN_USER_AGENT
HAR-файлы
signed OSS URLs
x-oss-security-token
x-oss-signature
x-oss-credential
```

HAR-файл содержит живую browser-session. Если он попал в архив, git или чат, session лучше переснять/обновить.

Probe маскирует sensitive query-параметры:

```text
x-oss-security-token=<redacted>
x-oss-signature=<redacted>
x-oss-credential=<redacted>
```

---

## 12. Troubleshooting

### `/config/har` возвращает 404

Запущен старый `qwen_service` или не заменён `service.py`.

Что сделать:

```bat
netstat -ano | findstr :8767
taskkill /PID <PID> /F
qwen_service\scripts\run_qwen_service.bat
```

---

### `qwen_file_auth_failed`

Файловые endpoints Qwen не приняли session.

Проверить:

```text
QWEN_COOKIE
QWEN_BX_UA
QWEN_BX_UMIDTOKEN
QWEN_BX_V
QWEN_USER_AGENT
```

И переснять HAR с реальным `/api/v2/files/*`.

---

### `SignatureDoesNotMatch`

Старый симптом неправильного OSS PUT.

В финальной версии должен использоваться:

```text
mode: sts_header_signed
uses_sts_header_signing: true
```

В логе должно быть:

```text
Qwen OSS PUT summary:
presigned=False
headers={'mode': 'sts_header_signed', ...}
```

Если снова появился `SignatureDoesNotMatch`, значит откатился старый `qwen_api.py` или используется старый patch.

---

### `.env is locked`

Windows не дал заменить `.env`.

Работа в текущем runtime не ломается, но session может не сохраниться после перезапуска.

Что сделать:

1. Закрыть редакторы, терминалы и процессы, которые могут держать `.env`.
2. Перезапустить `har-refresh`.
3. Проверить, что `env_saved: true`.

---

### `file_not_visible`

Файл загрузился, но Qwen не увидел его в chat message.

Проверить:

```text
parse_status: success
files[] содержит полный file_info
meta.parse_meta.parse_status = success
```

---

### Файл больше 20 МБ

Ошибка ожидаемая:

```text
qwen_file_too_large
```

Лимит:

```env
QWEN_FILE_UPLOAD_MAX_SIZE_MB=20
```

---

## 13. Рекомендуемый рабочий сценарий

```bat
cd /d D:\Project\Nickelfront

qwen_service\scripts\run_qwen_service.bat
```

В другом окне:

```bat
qwen_service\scripts\run_qwen_upload_probe.bat --mode har-refresh
qwen_service\scripts\run_qwen_upload_probe.bat --mode health
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-and-send
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-pdf --pdf-file test.pdf
qwen_service\scripts\run_qwen_upload_probe.bat --mode upload-multi --files qwen_upload_probe.txt,test.pdf
```

Если всё прошло:

```text
Passed: YES
```

значит Qwen file pipeline готов к использованию из Nickelfront.
