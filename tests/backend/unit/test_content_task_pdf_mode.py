from app.tasks.content_tasks import _normalize_pdf_mode_override


def test_pdf_mode_override_accepts_public_modes() -> None:
    assert _normalize_pdf_mode_override("auto") == "auto"
    assert _normalize_pdf_mode_override("AI") == "ai"


def test_pdf_mode_override_preserves_legacy_settings_or_falls_back_safely() -> None:
    assert _normalize_pdf_mode_override(None) is None
    assert _normalize_pdf_mode_override("unknown") == "auto"
