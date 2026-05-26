"""Domain profiles for optional PDF parser lexical hints.

The parser core must stay layout-first: reading order, bbox geometry, font size,
line density and table regularity decide the main extraction path. Domain words
from a profile are only small bonus signals for ambiguous blocks; they must not
be mandatory for a PDF to be parsed or for a table to survive validation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Pattern

_NEVER_RE = re.compile(r"a\A")

_GENERIC_TABLE_CONTEXT_RE = re.compile(
    r"\b(?:Table|Таблица|sample|samples|specimen|specimens|parameter|parameters|value|values|"
    r"property|properties|condition|conditions|measurement|measurements|temperature|density|"
    r"row|column|mean|median|std|"
    r"образец|образцы|параметр|значени[ея]|свойств[ао]|услови[ея]|измерени[ея]|температур[аы])\b",
    re.IGNORECASE,
)
_GENERIC_STRONG_TABLE_RE = re.compile(
    r"\b(?:Table|Таблица)\s+[SА-ЯA-Z]*\d+\b|\b(?:mean|median|std\.?|min\.?|max\.?)\s*(?:±|\+/-)?\s*[-+]?\d",
    re.IGNORECASE,
)
_GENERIC_UNIT_RE = re.compile(
    r"\b(?:MPa|GPa|Pa|kPa|°C|K|h|min|s|ms|kg|g|mg|m|cm|mm|μm|um|nm|A|V|W|J|mol|bar)\b|%",
    re.IGNORECASE,
)
_GENERIC_TABLE_SEMANTIC_RE = re.compile(
    r"\b(?:sample|samples|specimen|specimens|parameter|parameters|value|values|property|properties|"
    r"condition|conditions|measurement|measurements|row|column|mean|median|std|"
    r"образец|образцы|параметр|значени[ея]|свойств[ао]|услови[ея]|измерени[ея])\b",
    re.IGNORECASE,
)
_GENERIC_PROSE_GUARD_RE = re.compile(
    r"\b(?:the|and|or|with|from|where|which|that|this|these|those|therefore|because|"
    r"respectively|prepared|using|shown|observed|measured|reported|obtained|indicates|described|"
    r"представл|показан|получен|использ|содерж|наблюд|измерен|установлен|соответств|является|были|было|после)\b",
    re.IGNORECASE,
)
_GENERIC_PLOT_ARTIFACT_RE = re.compile(
    r"\b(?:Fig\.?|Figure|Рис\.?|Рисунок|panel|plot|chart|graph|spectrum|spectra|"
    r"axis|axes|legend|xlabel|ylabel|x-axis|y-axis|scale|tick|ticks|"
    r"curve|curves|histogram|diagram)\b",
    re.IGNORECASE,
)

_MATERIALS_TABLE_CONTEXT_RE = re.compile(
    r"\b(?:Table|Таблица|composition|compositions|alloy|alloys|superalloy|superalloys|sample|specimen|"
    r"wt\.?\s*%|at\.?\s*%|mol\.?\s*%|mass\s*%|temperature|strength|creep|oxidation|oxide|"
    r"corrosion|hardness|heat\s+treatment|microstructure|phase|density|yield|tensile|elongation|"
    r"element|elements|состав|сплав|жаропроч|ползуч|окислен|оксид|корроз|прочност|температур|"
    r"припо[йяе]|пайк|микроструктур|ГТО|ЭП\d+|ВКНА-?\d+|ВПр\d+)\b",
    re.IGNORECASE,
)
_MATERIALS_STRONG_TABLE_RE = re.compile(
    r"\b(?:chemical\s+composition|nominal\s+composition|composition\s*\(|wt\.?\s*%|at\.?\s*%|mass\s*%|"
    r"element(?:al)?\s+composition|alloy(?:s)?|superalloy(?:s)?|heat\s+treatment|creep|oxidation|oxide|"
    r"corrosion|hardness|yield\s+strength|tensile\s+strength|elongation|microstructure|phase|density|"
    r"содержание\s+элементов|химический\s+состав|мас\.?\s*%|ат\.?\s*%|сплав(?:ы)?|"
    r"жаропроч|ползуч|окислен|оксид|корроз|прочност|термообработ|ЭП\d+|ВКНА-?\d+|ВПр\d+)\b",
    re.IGNORECASE,
)
_MATERIALS_UNIT_RE = re.compile(
    r"\b(?:MPa|GPa|Pa|kPa|°C|K|h|min|s|ms|kg|g|mg|m|cm|mm|μm|um|nm|A|V|W|J|mol|bar|"
    r"wt\.?\s*%|at\.?\s*%|mass\s*%|mol\.?\s*%|мас\.?\s*%|ат\.?\s*%)\b|%",
    re.IGNORECASE,
)
_MATERIALS_TABLE_SEMANTIC_RE = re.compile(
    r"\b(?:composition|alloy|alloys|superalloy|superalloys|sample|samples|specimen|specimens|"
    r"element|elements|phase|microstructure|oxide|oxidation|corrosion|состав|сплав|элемент|фаз|"
    r"микроструктур|оксид|окислен|корроз)\b",
    re.IGNORECASE,
)
_MATERIALS_ELEMENT_RE = re.compile(r"\b(?:Ni|Al|Cr|Co|Mo|W|Re|Ru|Ta|Ti|Nb|Hf|Fe|Mn|C|B|Y|Zr|Si|V|La|Ce)\b")
_MATERIALS_PROSE_GUARD_RE = re.compile(
    r"\b(?:сплав|припо[йяе]|пайк|микроструктур|температур|прочност|ВКНА-?\d+|ЭП\d+|ВПр\d+|ГОСТ|"
    r"alloy|superalloy|microstructure|temperature|strength|hardness|yield|tensile|elongation|braz)\b",
    re.IGNORECASE,
)
_MATERIALS_PLOT_ARTIFACT_RE = re.compile(
    _GENERIC_PLOT_ARTIFACT_RE.pattern[:-3] + r"|Fe\s+K|Ni\s+K)\b",
    re.IGNORECASE,
)

_PATENT_TABLE_CONTEXT_RE = re.compile(
    r"\b(?:Table|Таблица|claim|claims|example|examples|embodiment|embodiments|inventive\s+example|"
    r"comparative\s+example|патент|формул[аы]\s+изобретения|пример|вариант|изобретени[ея])\b",
    re.IGNORECASE,
)
_PATENT_STRONG_TABLE_RE = re.compile(
    r"\b(?:claim\s+\d+|example\s+\d+|comparative\s+example\s+\d+|inventive\s+example\s+\d+|"
    r"п\.\s*\d+|пример\s+\d+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParserDomainProfile:
    name: str
    table_context_hint_re: Pattern[str]
    strong_table_hint_re: Pattern[str]
    table_unit_hint_re: Pattern[str]
    table_semantic_context_re: Pattern[str]
    element_re: Pattern[str]
    prose_guard_re: Pattern[str]
    plot_artifact_context_re: Pattern[str]
    patent_marker_re: Pattern[str] = _NEVER_RE


GENERIC_PROFILE = ParserDomainProfile(
    name="generic",
    table_context_hint_re=_GENERIC_TABLE_CONTEXT_RE,
    strong_table_hint_re=_GENERIC_STRONG_TABLE_RE,
    table_unit_hint_re=_GENERIC_UNIT_RE,
    table_semantic_context_re=_GENERIC_TABLE_SEMANTIC_RE,
    element_re=_NEVER_RE,
    prose_guard_re=_GENERIC_PROSE_GUARD_RE,
    plot_artifact_context_re=_GENERIC_PLOT_ARTIFACT_RE,
)

MATERIALS_PROFILE = ParserDomainProfile(
    name="materials",
    table_context_hint_re=_MATERIALS_TABLE_CONTEXT_RE,
    strong_table_hint_re=_MATERIALS_STRONG_TABLE_RE,
    table_unit_hint_re=_MATERIALS_UNIT_RE,
    table_semantic_context_re=_MATERIALS_TABLE_SEMANTIC_RE,
    element_re=_MATERIALS_ELEMENT_RE,
    prose_guard_re=re.compile(
        rf"(?:{_GENERIC_PROSE_GUARD_RE.pattern}|{_MATERIALS_PROSE_GUARD_RE.pattern})",
        re.IGNORECASE,
    ),
    plot_artifact_context_re=_MATERIALS_PLOT_ARTIFACT_RE,
)

PATENTS_PROFILE = ParserDomainProfile(
    name="patents",
    table_context_hint_re=re.compile(
        rf"(?:{_GENERIC_TABLE_CONTEXT_RE.pattern}|{_PATENT_TABLE_CONTEXT_RE.pattern})",
        re.IGNORECASE,
    ),
    strong_table_hint_re=re.compile(
        rf"(?:{_GENERIC_STRONG_TABLE_RE.pattern}|{_PATENT_STRONG_TABLE_RE.pattern})",
        re.IGNORECASE,
    ),
    table_unit_hint_re=_GENERIC_UNIT_RE,
    table_semantic_context_re=re.compile(
        rf"(?:{_GENERIC_TABLE_SEMANTIC_RE.pattern}|{_PATENT_TABLE_CONTEXT_RE.pattern})",
        re.IGNORECASE,
    ),
    element_re=_NEVER_RE,
    prose_guard_re=_GENERIC_PROSE_GUARD_RE,
    plot_artifact_context_re=_GENERIC_PLOT_ARTIFACT_RE,
    patent_marker_re=_PATENT_TABLE_CONTEXT_RE,
)

_PROFILES = {
    GENERIC_PROFILE.name: GENERIC_PROFILE,
    MATERIALS_PROFILE.name: MATERIALS_PROFILE,
    PATENTS_PROFILE.name: PATENTS_PROFILE,
}
_PROFILE_ALIASES = {
    "": "generic",
    "default": "generic",
    "base": "generic",
    "generic": "generic",
    "material": "materials",
    "materials": "materials",
    "materials_science": "materials",
    "metallurgy": "materials",
    "alloys": "materials",
    "superalloy": "materials",
    "superalloys": "materials",
    "nickel": "materials",
    "patent": "patents",
    "patents": "patents",
}


def normalize_domain_profile_name(value: object | None) -> str:
    key = str(value or "generic").strip().lower().replace("-", "_")
    return _PROFILE_ALIASES.get(key, "generic")


def is_domain_bonus_profile(value: object | None = None) -> bool:
    """Return True only for explicit non-generic profile hints.

    Core parsing remains structural-first. This helper centralizes legacy aliases
    so parser mixins do not hardcode subject-specific words outside profiles.py.
    """

    return normalize_domain_profile_name(value) != "generic"


def get_domain_profile(value: object | None = None) -> ParserDomainProfile:
    return _PROFILES[normalize_domain_profile_name(value)]


__all__ = [
    "ParserDomainProfile",
    "GENERIC_PROFILE",
    "MATERIALS_PROFILE",
    "PATENTS_PROFILE",
    "get_domain_profile",
    "is_domain_bonus_profile",
    "normalize_domain_profile_name",
]
