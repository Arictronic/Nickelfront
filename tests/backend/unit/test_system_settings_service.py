from app.services.system_settings_service import sanitize_section


def test_google_patents_is_enabled_by_default_for_direct_lookup() -> None:
    parser_settings = sanitize_section("parser", {})

    assert parser_settings["enabled_sources"]["GooglePatents"] is True


def test_explicit_google_patents_disable_is_preserved() -> None:
    parser_settings = sanitize_section(
        "parser",
        {"enabled_sources": {"GooglePatents": False}},
    )

    assert parser_settings["enabled_sources"]["GooglePatents"] is False
