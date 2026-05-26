"""Source registry with reliability metadata and capability contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from parsers_pkg.errors import MisconfigurationError

SourceType = Literal["api", "scraper", "browser_automation"]
SourceStability = Literal["high", "medium", "low"]
AntiBotRisk = Literal["low", "medium", "high"]
MaturityLevel = Literal["experimental", "beta", "stable", "deprecated"]
AccessMode = Literal["official", "unofficial", "browser_automation"]


@dataclass(frozen=True)
class SourceCapabilities:
    search: bool = True
    full_text: bool = False
    citations: bool = False
    keywords: bool = False
    abstract: bool = True
    date: bool = True
    author_affiliations: bool = False
    pdf_url: bool = False
    doi: bool = False
    institution_metadata: bool = False


@dataclass(frozen=True)
class SourceRuntimeDefaults:
    enabled: bool = True
    timeout: float = 30.0
    max_retries: int = 3
    retry_base_delay: float = 1.5
    retry_backoff_base: float = 2.0
    retry_jitter_max: float = 0.7
    browser_enabled: bool = True
    require_api_key: bool = False
    headless: bool = True
    headers_profile: str = "default"


@dataclass(frozen=True)
class SourceMetadata:
    name: str
    source_type: SourceType
    stability: SourceStability
    requires_js: bool
    requires_auth: bool
    anti_bot_risk: AntiBotRisk
    capabilities: SourceCapabilities
    priority: int = 100
    requires_api_key: bool = False
    api_key_env: str | None = None
    requires_browser: bool = False
    supports_batch_search: bool = False
    supports_async: bool = True
    runtime_defaults: SourceRuntimeDefaults = SourceRuntimeDefaults()
    notes: str | None = None
    maturity: MaturityLevel = "beta"
    access_mode: AccessMode = "official"
    compliance_notes: str | None = None

    @property
    def is_fragile(self) -> bool:
        return self.stability == "low" or self.source_type != "api"


class SourceRegistry:
    def __init__(self, sources: list[SourceMetadata]):
        self._by_name = {source.name: source for source in sources}
        self._canonical_names = {source.name.casefold(): source.name for source in sources}

    def _canonicalize(self, name: str | None) -> str | None:
        raw = (name or "").strip()
        if not raw:
            return None
        return self._canonical_names.get(raw.casefold())

    def list_names(self) -> list[str]:
        return sorted(self._by_name)

    def list_sources(self) -> list[SourceMetadata]:
        return sorted(self._by_name.values(), key=lambda source: source.priority)

    def get(self, name: str) -> SourceMetadata:
        canonical = self._canonicalize(name)
        source = self._by_name.get(canonical or "")
        if source is None:
            supported = ", ".join(self.list_names())
            raise MisconfigurationError(
                source=name or "unknown",
                message=f"Unsupported source: {name}. Supported: {supported}",
            )
        return source

    def is_supported(self, name: str) -> bool:
        return self._canonicalize(name) is not None


def build_default_source_registry() -> SourceRegistry:
    return SourceRegistry(
        sources=[
            SourceMetadata(
                name="arXiv",
                source_type="api",
                stability="high",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                ),
                priority=10,
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=4,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.8,
                ),
                notes="Stable public API source.",
                maturity="stable",
                access_mode="official",
                compliance_notes="Public API with documented usage expectations.",
            ),
            SourceMetadata(
                name="CORE",
                source_type="api",
                stability="medium",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                ),
                priority=20,
                requires_api_key=False,
                api_key_env="CORE_API_KEY",
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=4,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.7,
                ),
                notes="Works without API key, but key is recommended for better limits.",
                maturity="beta",
                access_mode="official",
                compliance_notes="Public API; key recommended for higher limits.",
            ),
            SourceMetadata(
                name="OpenAlex",
                source_type="api",
                stability="high",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=False,
                    citations=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                    institution_metadata=True,
                ),
                priority=30,
                requires_api_key=False,
                api_key_env="OPENALEX_API_KEY",
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.0,
                ),
                maturity="stable",
                access_mode="official",
                compliance_notes="Metadata API is public; OPENALEX_API_KEY enables the official metered Content API PDF endpoint.",
            ),
            SourceMetadata(
                name="Crossref",
                source_type="api",
                stability="high",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=False,
                    citations=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                    institution_metadata=True,
                ),
                priority=40,
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.0,
                ),
                maturity="stable",
                access_mode="official",
                compliance_notes="Public metadata API with rate-limit guidance.",
            ),
            SourceMetadata(
                name="EuropePMC",
                source_type="api",
                stability="high",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=False,
                    keywords=False,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                ),
                priority=60,
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.0,
                ),
                maturity="stable",
                access_mode="official",
                compliance_notes="Public API endpoint for biomedical metadata.",
            ),
            SourceMetadata(
                name="CyberLeninka",
                source_type="scraper",
                stability="medium",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="medium",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                ),
                priority=70,
                supports_batch_search=False,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=2.0,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.5,
                ),
                notes="Russian scientific library. Uses web scraping (no official API).",
                maturity="beta",
                access_mode="unofficial",
                compliance_notes="Web scraping; respect rate limits and robots.txt.",
            ),
            SourceMetadata(
                name="eLibrary",
                source_type="scraper",
                stability="medium",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="medium",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=False,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=True,
                ),
                priority=80,
                supports_batch_search=False,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=2.0,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.5,
                ),
                notes="Russian scientific library and citation index (best-effort scraping).",
                maturity="beta",
                access_mode="unofficial",
                compliance_notes="Best-effort parsing; pages may require auth/session for full metadata.",
            ),
            SourceMetadata(
                name="Rospatent",
                source_type="api",
                stability="medium",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=False,
                ),
                priority=85,
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.0,
                ),
                notes="Rospatent Search Platform API endpoints (integral search path).",
                maturity="beta",
                access_mode="official",
                compliance_notes="Public search endpoints; response schema may vary.",
            ),
            SourceMetadata(
                name="FreePatent",
                source_type="scraper",
                stability="low",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="medium",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=False,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=False,
                ),
                priority=90,
                supports_batch_search=False,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=2.0,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.5,
                ),
                notes="FreePatent registry via Yandex site-search index.",
                maturity="beta",
                access_mode="unofficial",
                compliance_notes="Parsed from site-search HTML results; not an official API.",
            ),
            SourceMetadata(
                name="GooglePatents",
                source_type="scraper",
                stability="medium",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=True,
                    keywords=False,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=False,
                ),
                priority=92,
                supports_batch_search=False,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=2.0,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.5,
                ),
                notes="Google Patents detail pages; query must be a publication ID or patent URL.",
                maturity="beta",
                access_mode="unofficial",
                compliance_notes="Reads allowed /patent/ detail pages only; automated search-result crawling is not enabled.",
            ),
            SourceMetadata(
                name="PATENTSCOPE",
                source_type="scraper",
                stability="low",
                requires_js=False,
                requires_auth=False,
                anti_bot_risk="low",
                capabilities=SourceCapabilities(
                    search=True,
                    full_text=False,
                    keywords=True,
                    abstract=True,
                    date=True,
                    pdf_url=True,
                    doi=False,
                ),
                priority=95,
                supports_batch_search=True,
                runtime_defaults=SourceRuntimeDefaults(
                    timeout=30.0,
                    max_retries=3,
                    retry_base_delay=1.5,
                    retry_backoff_base=2.0,
                    retry_jitter_max=0.0,
                ),
                notes="WIPO PATENTSCOPE HTML result parser; automated use requires compliance review.",
                maturity="stable",
                access_mode="unofficial",
                compliance_notes=(
                    "WIPO PATENTSCOPE FAQ prohibits automatic robot usage; "
                    "do not expand or operate this HTML parser without an approved access path."
                ),
            ),
        ]
    )
