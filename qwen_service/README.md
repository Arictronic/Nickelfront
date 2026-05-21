# Qwen Service

���������� HTTP-������ ��� ������ � Qwen API ����� REST.

������ ������ runtime-��������� � `.env`, ������������ ������, �������� ���������, ����������� �������, ����-����������� � ������� �������� � �������/�������������.

## ��� ����� �����

- ������ ������ `.env` �� ����� ������� (`../.env` ������������ `qwen_service/service.py`).
- ���� `QWEN_API_KEY` �� �����, API �������� ��� �����������.
- ���� `QWEN_API_KEY` �����, ����������� `Authorization: Bearer <QWEN_API_KEY>`.
- ���������, ���������� ����� `/config*`, ����������� ������� � `.env`.
- ��� ������� `session_id` ������������ ��������� ��������� Qwen-������� � ����������� �� ������ ������.

## ������� �����

### 1. ��������� ������������

�� ����� �������:

```bash
pip install fastapi uvicorn[standard] pydantic requests httpx python-dotenv
```

### 2. ��������� `.env`

����������:

```env
QWEN_TOKEN=your_qwen_token
QWEN_API_KEY=your_service_api_key
```

������ ����� (� ���������):

```env
QWEN_SERVICE_HOST=127.0.0.1
QWEN_SERVICE_PORT=8767
QWEN_TOKEN=
QWEN_API_KEY=
QWEN_MODEL=qwen3.6-plus
QWEN_THINKING_ENABLED=true
QWEN_SEARCH_ENABLED=true
QWEN_AUTO_CONTINUE_ENABLED=true
QWEN_MAX_CONTINUES=5
QWEN_STREAM_RETRIES=2
QWEN_HISTORY_RECOVERY_ATTEMPTS=3
QWEN_HISTORY_RECOVERY_INTERVAL_SEC=1.0
LOG_LEVEL=DEBUG
```

### 3. ������ �������

�� ����� �������:

```bash
python qwen_service/service.py
```

### 4. ��������

```bash
python qwen_service/client.py
```

������������� �����:

```bash
python qwen_service/client.py --chat
```

## API

## ���������

- `GET /health` � ������ ������� � ������� ����������� Qwen.
- `GET /config` � ��������� runtime-��������� (��� ��������).
- `POST /config` � ��������� ���������� runtime-��������.

������ `POST /config`:

```json
{
  "model": "qwen3.6-plus",
  "thinking_enabled": true,
  "search_enabled": false,
  "auto_continue_enabled": true,
  "max_continues": 5,
  "stream_retries": 2,
  "history_recovery_attempts": 3,
  "history_recovery_interval_sec": 1.0
}
```

## ������ ����-�����������

- `GET /config/auto_continue`
- `POST /config/auto_continue?enabled=true&max_continues=3`

## ����� � API-����

- `POST /config/token` � body:

```json
{ "token": "..." }
```

- `POST /config/api_key` � body:

```json
{ "api_key": "..." }
```

## ������

- `GET /config/model`
- `POST /config/model` � body:

```json
{
  "model": "qwen3.6-plus",
  "thinking_enabled": true,
  "search_enabled": true,
  "auto_continue_enabled": true,
  "max_continues": 5
}
```

- `GET /models`

## ������

- `POST /sessions` (����������� `{"title": "..."}`)
- `GET /sessions`
- `GET /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `POST /sessions/{session_id}/rename` � body `{"title": "..."}`

## ���������

- `POST /messages`
- `POST /messages/continue`

������ `POST /messages`:

```json
{
  "session_id": "session-id",
  "message": "������ ������ �� Python",
  "thinking_enabled": true,
  "search_enabled": false,
  "file_ids": [],
  "auto_continue": true
}
```

�������� ���� ������:

```json
{
  "session_id": "session-id",
  "response": "...",
  "thinking": "...",
  "message_id": 123,
  "last_message_id": 123,
  "can_continue": false,
  "auto_continue_performed": true,
  "continue_count": 1,
  "auto_continue_reason": "content analysis"
}
```

������ `POST /messages/continue`:

```json
{
  "session_id": "session-id",
  "message_id": 123,
  "thinking_enabled": true
}
```

�������� `auto_continue` ��� `/messages/continue` ���������� query-����������.

## ����� � ������������

- `POST /files/upload` � body `{"file_path": "..."}`
- `GET /files/{file_id}`
- `GET /user/info`

����������: ���� standalone-������ ���������� �� ������������ `upload_file` ��� `fetch_files`, ������ ������ `501`.

## ����-����������� � ������������������

- ��� ������ ��������� ������ ������� ������ ������� send, ����� ��� ������������� ������������� �������� continue.
- ������� � ����������� �������� �� `can_continue` �� ���������� � ������� ������ ������.
- ���� ������ �� ������������ ����� (��������� ��� ���������� ���������).
- ��� �������/��������� ����� ������:
  - ������ ������ (`QWEN_STREAM_RETRIES`),
  - �������� ������������ ����� �� ������� (`QWEN_HISTORY_RECOVERY_*`).
- ��� ������ `Model not found` ������ ������� fallback-������ � ��������� ��������� ������ � `.env`.

## ����

���� ������� �:

- `logs/qwen_service.log` (� ��������)
- `stdout`

������� ����������� �������� `LOG_LEVEL`.