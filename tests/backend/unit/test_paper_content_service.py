from app.core.config import settings
from app.services.paper_content_service import prepare_pdf_request


def test_openalex_pdf_key_is_added_only_to_outgoing_request():
    original_key = settings.OPENALEX_API_KEY
    settings.OPENALEX_API_KEY = "server-secret"
    try:
        stored_url = "https://content.openalex.org/works/W123.pdf"
        request_url, headers = prepare_pdf_request(stored_url)
    finally:
        settings.OPENALEX_API_KEY = original_key

    assert "server-secret" not in stored_url
    assert request_url == "https://content.openalex.org/works/W123.pdf?api_key=server-secret"
    assert "application/pdf" in headers["Accept"]


def test_regular_pdf_url_does_not_receive_openalex_key():
    original_key = settings.OPENALEX_API_KEY
    settings.OPENALEX_API_KEY = "server-secret"
    try:
        request_url, _ = prepare_pdf_request("https://publisher.example/paper.pdf")
    finally:
        settings.OPENALEX_API_KEY = original_key

    assert request_url == "https://publisher.example/paper.pdf"
