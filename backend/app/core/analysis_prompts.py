ANALYSIS_SYSTEM_PROMPT = """
Ты — эксперт по материаловедению и анализу патентов.
Проанализируй предоставленный текст статьи/патента и верни структурированный JSON.
"""

ANALYSIS_OUTPUT_SCHEMA = """
{
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "methodology": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "conclusion": {"type": "string"}
    },
    "required": ["summary", "key_findings"]
}
"""
