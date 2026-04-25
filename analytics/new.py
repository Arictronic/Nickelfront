#!/usr/bin/env python3
"""
extractor.py
Однофайловый модуль: загрузка файлов в GigaChat → извлечение данных → CSV.
Зависимости: pip install requests pandas python-dotenv
"""
import os, json, time, base64, uuid, re, urllib3
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Отключаем предупреждения о самоподписанных сертификатах (для локальных тестов)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# ================= НАСТРОЙКИ =================
CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")
CLIENT_SECRET = os.getenv("GIGACHAT_CLIENT_SECRET")
SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
BASE_URL = "https://gigachat.devices.sberbank.ru/api/v2"
PROMPT_PATH = Path(__file__).parent / "prompt.md"
INPUT_DIR = Path(__file__).parent / "./input_files"
OUTPUT_CSV = Path(__file__).parent / "./alloys_data.csv"
ALLOWED_EXTS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".html", ".htm", ".txt"}

# ================= TOKEN MANAGER =================
_token = None
_expires = 99

def get_token() -> str:
    global _token, _expires
    if _token and time.time() < _expires - 60:
        return _token
    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Accept": "application/json",
        "Authorization": f"Basic {auth}",
        "RqUID": str(uuid.uuid4()),                  # ← обязательно для трекинга
        "Content-Type": "application/x-www-form-urlencoded"  # ← критично!
    }
    resp = requests.post(
        "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        headers=headers,
        data={"scope": SCOPE},  # ← именно data, не json
        verify=False,
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _expires = time.time() + data["expires_in"]
    print("  🔑 Токен GigaChat обновлён")
    return _token

# ================= GIGACHAT API =================
def upload_file(filepath: Path) -> str:
    """Загружает файл в хранилище GigaChat и возвращает file_id."""
    headers = {"Authorization": f"Bearer {get_token()}"}
    with open(filepath, "rb") as f:
        resp = requests.post(f"{BASE_URL}/files", headers=headers, files={"file": (filepath.name, f)}, verify=False)
    resp.raise_for_status()
    return resp.json()["id"]

def ask_gigachat(file_id: str) -> dict:
    """Отправляет промпт + файл в GigaChat и возвращает распарсенный JSON."""
    if not PROMPT_PATH.exists():
        raise SystemExit(f"❌ Файл промпта не найден: {PROMPT_PATH.absolute()}")
        
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    
    payload = {
        "model": "GigaChat-2",
        "messages": [{
            "role": "user",
            "content": prompt_text,
            "attachments": [{"type": "file", "id": file_id}]
        }],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
        "RqUID": str(uuid.uuid4())
    }

    for attempt in range(3):
        try:
            resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=300, verify=False)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            
            # Чистим markdown-обёртки
            clean = re.sub(r'^```(?:json)?\s*', '', raw).strip()
            clean = re.sub(r'\s*```$', '', clean).strip()
            return json.loads(clean)
        except Exception as e:
            print(f"  ⚠️ Попытка {attempt+1} не удалась: {e}")
            time.sleep(2 ** attempt)
    return {}

# ================= FLATTEN & EXPORT =================
def flatten_item(item: dict, source_file: str) -> dict:
    """Превращает сложный JSON-ответ в плоскую строку для CSV."""
    props = item.get("properties", {})
    mech = props.get("mechanical", [])
    ht = props.get("high_temperature", {})
    
    sr = ht.get("stress_rupture", []) or []
    creep = ht.get("creep", []) or []
    
    ts_obj = mech[0].get("tensile_strength", {}) if mech else {}
    sr0 = sr[0] if sr else {}
    cr0 = creep[0] if creep else {}

    return {
        "source_file": source_file,
        "alloy_name": item.get("alloy_name"),
        "crystallization_type": item.get("crystallization_type"),
        "chemical_composition": json.dumps(item.get("chemical_composition", {}), ensure_ascii=False),
        "tensile_strength_mpa": ts_obj.get("value"),
        "tensile_temp_c": mech[0].get("temperature") if mech else None,
        "rupture_strength_mpa": sr0.get("value"),
        "rupture_temp_c": sr0.get("temperature"),
        "rupture_time_h": sr0.get("rupture_time"),
        "creep_rate": cr0.get("creep_rate"),
        "creep_stress_mpa": cr0.get("stress"),
        "creep_temp_c": cr0.get("temperature"),
        "status": "ok"
    }

# ================= MAIN =================
def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit("❌ Укажи GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET в .env")
    if not INPUT_DIR.exists():
        INPUT_DIR.mkdir(parents=True)
        print(f"📁 Создана папка {INPUT_DIR}. Положи туда файлы и запусти снова.")
        return

    files = [f for f in INPUT_DIR.iterdir() if f.suffix.lower() in ALLOWED_EXTS and f.is_file()]
    if not files:
        print("❌ Нет поддерживаемых файлов в папке.")
        return

    print(f"🚀 Найдено файлов: {len(files)}")
    results = []

    for f in files:
        print(f"\n📄 {f.name} | Загрузка...")
        try:
            file_id = upload_file(f)
            print(f"  🆔 ID получен. Отправка в GigaChat...")
            response = ask_gigachat(file_id)
            
            if response and isinstance(response.get("items"), list):
                for item in response["items"]:
                    results.append(flatten_item(item, f.name))
                print(f"  ✅ Извлечено сплавов: {len(response['items'])}")
            else:
                print("  ⚠️ Модель вернула пустой или невалидный ответ")
                results.append({"source_file": f.name, "alloy_name": "PARSE_FAILED", "status": "empty_response"})
                
        except Exception as e:
            pass
            print(f"  ❌ Критическая ошибка: {e}")
            results.append({"source_file": f.name, "alloy_name": "ERROR", "status": str(e)})

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n💾 Готово! {len(df)} строк сохранено в {OUTPUT_CSV}")

if __name__ == "__main__":
    main()