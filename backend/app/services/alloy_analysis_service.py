from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings

ALLOY_ANALYSIS_RESULTS_DIR = Path(settings.resolve_path("./storage/alloy_analysis"))
ALLOY_ANALYSIS_PROMPT_PATH = ALLOY_ANALYSIS_RESULTS_DIR / "prompt.txt"
RU_OUTPUT_RULE = (
    "Все текстовые значения, которые формулируешь сам, возвращай на русском языке: "
    "alloy_class, processing_state, applications, warnings, notes, text-описания свойств "
    "и любые пояснения. Названия марок сплавов, стандарты, химические элементы и единицы "
    "измерения оставляй в оригинальном виде."
)

ALLOY_ANALYSIS_PROMPT = """
Ты - высокоточный экстрактор данных для построения аналитической базы знаний по никелевым суперсплавам (Ni-based superalloys).

На вход подается OCR-текст технической документации: научные статьи, паспорта материалов, спецификации AMS/ASTM, отчеты об испытаниях.
Верни строго один JSON-объект без markdown, комментариев и пояснений:
{
  "extraction_metadata": {
    "total_alloys_found": 0,
    "extraction_timestamp": "<ISO 8601>",
    "document_id": "<document_id или unknown>",
    "warnings": []
  },
  "items": []
}

Каждый items[] - один сплав:
{
  "alloy_name": "",
  "alloy_class": "<string|null>",
  "processing_state": "<string|null>",
  "source_text_snippet": "",
  "chemical_composition": { "Ni": 54.2, "Cr": 18.5 },
  "properties": {
    "physical": {},
    "mechanical": {},
    "high_temperature": {}
  },
  "applications": [],
  "standards": [],
  "quality_flags": {
    "composition_sum_valid": <bool|null>,
    "ocr_corrections_applied": false,
    "units_inferred": false,
    "conflicting_properties": []
  }
}

Правила:
- Все текстовые значения, которые формулируешь сам, возвращай на русском языке: alloy_class, processing_state, applications, warnings, notes, text-описания свойств и любые пояснения. Названия марок сплавов, стандарты, химические элементы и единицы измерения оставляй в оригинальном виде.
- Извлекай только данные, явно относящиеся к сплаву. Если данных мало, сохраняй сплав, если есть название и хотя бы одно свойство/состав/стандарт.
- Диапазоны состава усредняй. Элемент "bal." вычисляй как 100 минус сумма остальных. Если больше одного "bal.", не вычисляй и добавь warning.
- composition_sum_valid=true, если сумма массовых процентов 95-105; false, если вне диапазона; null, если состава нет.
- Не извлекай атомные проценты без способа пересчета.
- Свойства нормализуй, но исходное значение сохраняй в reported: { "raw_text": "", "value": <number>, "unit": "" }.
- Температура -> °C. °F пересчитывай как (°F - 32) * 5/9.
- Напряжение -> MPa. ksi*6.895, psi*0.006895, GPa*1000.
- Плотность -> kg/m3. г/см3*1000, lb/in3*27679.9.
- Модуль упругости -> GPa. Твердость не пересчитывай, оставляй шкалу HB/HRC/HV.
- Текстовые свойства возвращай как { "value": null, "text": "...", "reported": { "raw_text": "..." } }.
- Категории properties: physical, mechanical, high_temperature.
- Для high_temperature обязательно выделяй stress_rupture массивом объектов: value MPa, unit "MPa", reported, temperature °C, rupture_time hours, larson_miller_parameter null, condition.
- Исправляй очевидные OCR-ошибки в известных сплавах: Inconel 718/625/706/738/792, Waspaloy, Rene 41/88/95, Hastelloy X/C-276, Nimonic 80A/90/105/263, Udimet 500/700, Mar-M-247, CMSX-4. Если исправил - ocr_corrections_applied=true.
- Если единицы подразумеваются из контекста, укажи reported.unit как "inferred: <unit>" и units_inferred=true.
- При конфликте >10% выбери наиболее достоверное значение, альтернативы положи в alternative_values, имя свойства добавь в conflicting_properties.
- Приоритет: точность и единообразие важнее полноты.
"""


def build_alloy_analysis_prompt(document_id: str, text: str) -> str:
    return f"""{get_alloy_analysis_prompt()}

document_id: {document_id.strip() or "unknown"}

Текст для анализа:
{text.strip()}

Сгенерируй JSON-ответ на основе предоставленного текста."""


def get_alloy_analysis_prompt() -> str:
    if ALLOY_ANALYSIS_PROMPT_PATH.exists():
        saved = ALLOY_ANALYSIS_PROMPT_PATH.read_text(encoding="utf-8").strip()
        if saved:
            if "возвращай на русском языке" not in saved:
                saved = f"{saved}\n\nДополнительное правило:\n- {RU_OUTPUT_RULE}"
                ALLOY_ANALYSIS_PROMPT_PATH.write_text(saved, encoding="utf-8")
            return saved
    return ALLOY_ANALYSIS_PROMPT.strip()


def save_alloy_analysis_prompt(prompt: str) -> str:
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Prompt cannot be empty")
    if "возвращай на русском языке" not in cleaned:
        cleaned = f"{cleaned}\n\nДополнительное правило:\n- {RU_OUTPUT_RULE}"
    ALLOY_ANALYSIS_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALLOY_ANALYSIS_PROMPT_PATH.write_text(cleaned, encoding="utf-8")
    return cleaned


def extract_json_object(raw: str) -> dict[str, Any]:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.removeprefix("```json").removeprefix("```").strip()
    if clean.endswith("```"):
        clean = clean[:-3].strip()

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        if start < 0:
            raise ValueError("В ответе Qwen нет JSON-объекта")

        depth = 0
        in_string = False
        escape = False
        parsed = None

        for index in range(start, len(clean)):
            char = clean[index]
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    parsed = json.loads(clean[start:index + 1])
                    break

        if parsed is None:
            raise ValueError("Не удалось выделить полный JSON-объект из ответа Qwen")

    if not isinstance(parsed, dict):
        raise ValueError("Qwen вернул JSON, но корневой элемент не объект")

    metadata = parsed.get("extraction_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        parsed["extraction_metadata"] = metadata

    items = parsed.get("items")
    if not isinstance(items, list):
        parsed["items"] = []

    metadata.setdefault("total_alloys_found", len(parsed["items"]))
    metadata.setdefault("extraction_timestamp", datetime.now().isoformat())
    metadata.setdefault("document_id", "unknown")
    metadata.setdefault("warnings", [])

    return parsed


def list_saved_alloy_analysis_results(limit: int = 200) -> list[dict[str, Any]]:
    if not ALLOY_ANALYSIS_RESULTS_DIR.exists():
        return []

    summaries = sorted(
        ALLOY_ANALYSIS_RESULTS_DIR.glob("paper_*/summary.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    results: list[dict[str, Any]] = []
    for path in summaries[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        summary = payload.get("summary") if isinstance(payload, dict) else None
        items = summary.get("items", []) if isinstance(summary, dict) else []
        metadata = summary.get("extraction_metadata", {}) if isinstance(summary, dict) else {}
        warnings = metadata.get("warnings", []) if isinstance(metadata, dict) else []

        results.append(
            {
                "paper_id": payload.get("paper_id"),
                "paper_title": payload.get("paper_title") or "",
                "source": payload.get("source") or "",
                "text_length": payload.get("text_length") or 0,
                "chunks_total": payload.get("chunks_total") or 0,
                "items_count": len(items) if isinstance(items, list) else 0,
                "warnings_count": len(warnings) if isinstance(warnings, list) else 0,
                "summary_path": str(path),
                "chunk_files": payload.get("chunk_files") or [],
                "extraction": summary or {},
                "error": payload.get("error"),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )

    return results
