"""Shared regexes and tuning constants for PDF extraction heuristics.

These constants were previously module globals in ``pdf_content_parser.py``. They stay
private by name, but ``__all__`` exports them for the legacy mixin modules.
"""

from __future__ import annotations

import re


_MATH_SYMBOL_RE = re.compile(r"[=∑∫√≈≤≥±×÷→←↔∞αβγδλμσΩωπθ{}^_]|\\(?:frac|sum|int|sqrt|begin|end|alpha|beta|gamma)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_PAGE_NUMBER_RE = re.compile(r"^\s*(?:[-–—]\s*)?\d{1,4}\s*(?:[-–—])?\s*$")
_DOI_FOOTER_RE = re.compile(r"\b(?:doi\s*:?\s*10\.|https?://doi\.org/10\.)", re.IGNORECASE)
_ARXIV_FOOTER_RE = re.compile(
    r"^\s*arXiv:\d{4}\.\d{4,5}v\d+\s+(?:\[[^\]]+\]\s*)?(?:\d{1,2}\s+[A-Za-z]+\s+\d{4})?\s*$",
    re.IGNORECASE,
)
_ARXIV_ID_RE = re.compile(r"\barXiv:(\d{4}\.\d{4,5}v\d+)\b", re.IGNORECASE)
_REFERENCE_HEADING_RE = re.compile(
    r"^\s*(?:references|bibliography|literature\s+cited|литература|список\s+литературы)\s*$",
    re.IGNORECASE,
)
_REFERENCE_STOP_HEADING_RE = re.compile(
    r"^\s*(?:appendix|supplementary\s+(?:material|information)|supporting\s+information|"
    r"author\s+contributions?|data\s+availability|acknowledg(?:e)?ments?|funding|"
    r"conflict\s+of\s+interest|competing\s+interests?|"
    r"приложение|благодарност[ьи]|финансировани[ея]|конфликт\s+интересов|"
    r"доступност[ьи]\s+данных|вклад\s+авторов)\b",
    re.IGNORECASE,
)
_CAPTION_LABEL_TOKEN = r"(?:S?\d+[A-Za-zА-Яа-я]?|[A-ZА-Я]\s*\d+[A-Za-zА-Яа-я]?|[IVXLCDM]+(?=\s*[|.:\-–—]))"
_CAPTION_START_RE = re.compile(
    r"^\s*(?:fig\.?|figure|table|scheme|algorithm|рис\.?|рисунок|табл\.?|таблица)\s*"
    + _CAPTION_LABEL_TOKEN
    + r"(?:\s*\([a-zа-я]\))?\s*(?:[|.:\-–—]|\b)",
    re.IGNORECASE,
)
_INLINE_CAPTION_MARK_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я])(?:FIG\.?|Fig\.?|Figure|Table|Рис\.?|Рисунок|Табл\.?|Таблица)\s+"
    + _CAPTION_LABEL_TOKEN
    + r"(?:\s*\([a-zа-я]\))?\s*(?:[|.:\-–—]|\b)",
    re.IGNORECASE,
)
_CONTENT_BLOCK_TYPES = ("body", "heading", "caption", "formula", "table", "reference", "footnote", "affiliation", "abstract", "unknown", "noise", "graph_axis", "page_number", "arxiv_footer", "watermark")
_MATH_MICRO_LINE_RE = re.compile(r"^[A-Za-zΑ-Ωα-ω𝑎-𝑧𝜂𝛺𝜉𝑈Ωηξπσ]+$|^[0-9]{1,2}$|^[()/\^=+−\-.,]+.*$")





_CID_GLYPH_REPLACEMENTS = {



    "0": "(",
    "1": ")",
    "16": "(",
    "17": ")",
    "18": "(",
    "19": ")",
    "20": "[",
    "21": "]",
    "32": "(",
    "33": ")",
    "101": "~",
}
_CID_TOKEN_RE = re.compile(r"\(cid:(\d{1,4})\)|\bcid:(\d{1,4})\b", re.IGNORECASE)






_PUA_GLYPH_RE = re.compile(r"[\ue000-\uf8ff]")
_PUA_GLYPH_REPLACEMENTS = {
    "\uf020": " ",
    "\uf021": "!",
    "\uf022": "∀",
    "\uf023": "#",
    "\uf024": "∃",
    "\uf025": "′",
    "\uf026": "&",
    "\uf027": "∋",
    "\uf028": "(",
    "\uf029": ")",
    "\uf02a": "*",
    "\uf02b": "+",
    "\uf02c": ",",
    "\uf02d": "-",
    "\uf02e": ".",
    "\uf02f": "/",
    "\uf03c": "<",
    "\uf03d": "=",
    "\uf03e": ">",
    "\uf05b": "[",
    "\uf05c": "\\",
    "\uf05d": "]",
    "\uf05e": "⊥",
    "\uf05f": "_",
    "\uf061": "α",
    "\uf062": "β",
    "\uf063": "χ",
    "\uf064": "δ",
    "\uf065": "ε",
    "\uf066": "φ",
    "\uf067": "γ",
    "\uf068": "η",
    "\uf069": "ι",
    "\uf06a": "ϕ",
    "\uf06b": "κ",
    "\uf06c": "λ",
    "\uf06d": "μ",
    "\uf06e": "ν",
    "\uf06f": "ο",
    "\uf070": "π",
    "\uf071": "θ",
    "\uf072": "ρ",
    "\uf073": "σ",
    "\uf074": "τ",
    "\uf075": "υ",
    "\uf076": "ϖ",
    "\uf077": "ω",
    "\uf078": "ξ",
    "\uf079": "ψ",
    "\uf07a": "ζ",
    "\uf0a2": "″",
    "\uf0a3": "≤",
    "\uf0a5": "∞",
    "\uf0b3": "≥",
    "\uf0b4": "×",
    "\uf0b5": "∝",
    "\uf0b6": "∂",
    "\uf0b7": "•",
    "\uf0b8": "÷",
    "\uf0b9": "≠",
    "\uf0ba": "≡",
    "\uf0bb": "≈",
    "\uf0d7": "×",
    "\uf0e5": "∑",
    "\uf0e6": "∏",
    "\uf0e8": "∩",
    "\uf0e9": "∪",
    "\uf0ea": "⊃",
    "\uf0eb": "⊇",
    "\uf0ec": "⊄",
    "\uf0ed": "⊂",
    "\uf0ee": "⊆",
    "\uf0ef": "∈",
    "\uf0f0": "∉",
    "\uf0f1": "∠",
    "\uf0f2": "∇",
    "\uf0f3": "®",
    "\uf0f4": "©",
    "\uf0f5": "™",
    "\uf0f6": "∏",
    "\uf0f7": "÷",
    "\uf0f8": "≠",
    "\uf0fa": "⋅",
}







_LATEXIT_TAG_RE = re.compile(r"<+\s*latexit\b[^>]*>?", re.IGNORECASE)
_REPEATED_LATEXIT_TAG_RE = re.compile(r"(?:l+\s*a+\s*t+\s*e+\s*x+\s*i+\s*t+)", re.IGNORECASE)
_BASE64ISH_RE = re.compile(r"^[A-Za-z0-9+/=\s]{40,}$")




_PRESERVE_HYPHEN_PREFIXES = {
    "anti",
    "carbon",
    "co",
    "cross",
    "energy",
    "field",
    "gas",
    "atmospheric",
    "high",
    "hot",
    "hydrogen",
    "inter",
    "iron",
    "low",
    "multi",
    "microwave",
    "nano",
    "non",
    "pressure",
    "quasi",
    "radio",
    "self",
    "semi",
    "sub",
    "two",
    "ultra",
    "water",
    "well",
}





_REMOVE_HYPHEN_PREFIXES = {
    "abil",
    "con",
    "de",
    "di",
    "elec",
    "en",
    "ex",
    "ge",
    "geo",
    "hy",
    "in",
    "mi",
    "pre",
    "pro",
    "re",
    "serpentiniza",
    "stimula",
    "thermo",
}



_COMMON_PDF_HYPHEN_REPAIRS = {
    "abil-ity": "ability",
    "con-version": "conversion",
    "con-ventional": "conventional",
    "de-livery": "delivery",
    "di-electric": "dielectric",
    "electro-magnetic": "electromagnetic",
    "en-hance": "enhance",
    "en-hanced": "enhanced",
    "en-hancement": "enhancement",
    "ex-posure": "exposure",
    "ex-tend": "extend",
    "geo-logic": "geologic",
    "hydro-gen": "hydrogen",
    "hy-drogen": "hydrogen",
    "inter-preta-tion": "interpretation",
    "interpreta-tion": "interpretation",
    "meas-ure": "measure",
    "measure-ment": "measurement",
    "mi-crowave": "microwave",
    "prelimi-nary": "preliminary",
    "re-action": "reaction",
    "re-actions": "reactions",
    "serpentiniza-tion": "serpentinization",
    "stimula-tion": "stimulation",
    "thermody-namic": "thermodynamic",
    "thermody-namics": "thermodynamics",
}


_KNOWN_CROSS_BLOCK_SPLIT_WORDS = {
    "conditions",
    "conductively",
    "conversion",
    "direct",
    "estimate",
    "formation",
    "increase",
    "inductively",
    "metrics",
    "produced",
    "response",
    "result",
    "tion",
}

_SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+|[IVXLCDM]+\.\s+)?"
    r"(?:Abstract|Keywords?|Introduction|Background|Related\s+Work|Prior\s+Work|"
    r"Methodology|Methods?|Materials?|Experimental\s+Setup|Experimental\s+Procedure|Experiments?|"
    r"Implementation|Evaluation|Analysis|Results?|Discussion|Case\s+Study|Ablation|"
    r"Limitations?|Future\s+Work|Nomenclature|Conclusion|Conclusions|References|"
    r"Funding|Data\s+Availability|Code\s+Availability|Author\s+Contributions?|"
    r"Conflict\s+of\s+Interest|Competing\s+Interests|Ethics|"
    r"Acknowledg(?:e)?ments?|Appendix|Supplementary(?:\s+Information|\s+Material)?)\b",
    re.IGNORECASE,
)
_CAPTION_RE = re.compile(
    r"^(?:Fig\.?|Figure|Table|Algorithm|Scheme|Equation|Рис\.?|Рисунок|Табл\.?|Таблица)\s+"
    + _CAPTION_LABEL_TOKEN,
    re.IGNORECASE,
)
_WATERMARK_WORD_RE = re.compile(
    r"^(?:DRAFT|PREPRINT|MANUSCRIPT|ACCEPTED|SUBMITTED|CONFIDENTIAL|COPYRIGHT|PROOF|UNCORRECTED|AUTHOR|VERSION)$",
    re.IGNORECASE,
)
_WATERMARK_LINE_RE = re.compile(
    r"\b(?:DRAFT|CONFIDENTIAL|UNCORRECTED\s+PROOF|ACCEPTED\s+MANUSCRIPT|SUBMITTED\s+VERSION|AUTHOR\s+VERSION)\b",
    re.IGNORECASE,
)
_FOOTNOTE_MARKER_RE = re.compile(
    r"^(?:[*†‡§¶]+|\(?[a-z]\)|[a-z]\)|"
    r"\d{1,2}[).]?\s+(?:Department|Institute|School|Faculty|Laboratory|Correspond|Email|E-mail|Present|Equal|Author|Affiliation))\b",
    re.IGNORECASE,
)
_GRAPH_AXIS_LINE_RE = re.compile(
    r"^\s*(?:\(?[a-z]\)?\s*)?(?:[-+]?\d+(?:[.,]\d+)?(?:\s+|$)){2,}(?:[A-Za-z%°/\-]+)?\s*$",
    re.IGNORECASE,
)
_AXIS_LABEL_LINE_RE = re.compile(
    r"^\s*(?:x\s+in\b|1/T\b|T\s*\(|Temperature\b|Energy\b|Formation\b|MSD\b|D\s*[A-Za-z+]*\s*/|Relative\s+Energy\b|Images?\b)",
    re.IGNORECASE,
)
_REVERSED_AXIS_LABEL_RE = re.compile(
    r"^\s*(?:\)?Ve\(?|ygrenE|noitamroF|erutarepmeT|ytisneD|ecnatsiseR|ytivitsiseR|egatloV|tnerruC|DMS|segamI)(?:\s|$|\))",
    re.IGNORECASE,
)
_BIBLIOGRAPHIC_SIGNAL_RE = re.compile(
    r"\b(?:doi|https?://|journal|vol\.?|volume|pp\.?|pages?|et\s+al\.|arxiv|"
    r"proceedings|phys\.?|chem\.?|science|nature|acta|springer|elsevier|wiley|mdpi|"
    r"изд\.?|журнал|вестник|труды|\d{4})\b",
    re.IGNORECASE,
)
_REFERENCE_ENUMERATOR_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.|\d{1,3}\)|\(\d{1,3}\))\s+")
_EQUATION_NUMBERED_BODY_RE = re.compile(
    r"^\s*\(\d{1,3}\)\s+(?:[a-zа-я]|[A-ZА-Я]?[a-zа-я]{2,})"
)
_PROTECTED_REFERENCE_SECTION_RE = re.compile(
    r"^\s*(?:conflict\s+of\s+interest|competing\s+interests?|acknowledg(?:e)?ments?|"
    r"funding|data\s+availability|code\s+availability|author\s+contributions?|ethics|"
    r"конфликт\s+интересов|благодарност[ьи]|финансировани[ея]|доступност[ьи]\s+данных|"
    r"вклад\s+авторов)\b",
    re.IGNORECASE,
)
_REFERENCE_LINE_RE = re.compile(
    r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.|\d{1,3}\)|\(\d{1,3}\))\s+"
    r"(?:[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}(?:,|\s+et\s+al\.|\s+and\s+|\s*&\s+)|"
    r"[A-ZА-Я][A-Za-zА-Яа-я'’.-]{2,}\s+[A-ZА-Я]\.)"
    r"[^\n]{20,}(?:doi|https?://|journal|vol\.?|pp\.?|arxiv|proceedings|phys\.?|chem\.?|"
    r"science|nature|acta|журнал|вестник|труды|\d{4})",
    re.IGNORECASE,
)
_TABLE_NUMERIC_ROW_RE = re.compile(
    r"^\s*(?:[A-Za-z][A-Za-z0-9%/°().-]*\s+)?(?:[-+]?\d+(?:[.,]\d+)?(?:\s+|$)){3,}.*$"
)
_TABLE_CANDIDATE_RE = re.compile(r"^\s*\[Table candidate(?:\s+\d+)?\]\s*$", re.IGNORECASE)
_MARKDOWN_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_CONTEXT_HINT_RE = re.compile(



    r"\b(?:Table|Таблица|sample|specimen|parameter|parameters|value|values|unit|units|"
    r"method|methods|group|groups|type|class|category|condition|conditions|result|results|"
    r"mean|median|std|sd|error|rate|ratio|index|number|no\.?|id|temperature|pressure|"
    r"time|duration|mass|weight|volume|density|length|area|count|score|accuracy|"
    r"precision|recall|параметр|значени[ея]|единиц[аы]?|групп[аы]?|тип|класс|категор|"
    r"услови[ея]|результат|средн|ошибк[аи]?|номер|температур|давлен|время|масса|"
    r"объ[её]м|плотност|длина|площад|количеств|точност)\b",
    re.IGNORECASE,
)
_PLOT_ARTIFACT_CONTEXT_RE = re.compile(
    r"\b(?:Fig\.?|Figure|Рис\.?|Рисунок|panel|plot|chart|graph|spectrum|spectra|"
    r"axis|axes|legend|xlabel|ylabel|x-axis|y-axis|scale|tick|ticks|"
    r"curve|curves|histogram|diagram)\b",
    re.IGNORECASE,
)
_TABLE_SEPARATOR_ROW_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")
_TABLE_CELL_SPLIT_RE = re.compile(r"\s{2,}|\t+|\s*\|\s*")
_PROSE_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|been|being|has|have|had|show|shown|shows|indicate|indicates|"
    r"observed|prepared|obtained|measured|calculated|reported|used|using|contains|consists|"
    r"представл|показан|получен|использ|содерж|наблюд|измерен)\b",
    re.IGNORECASE,
)
_FIGURE_LABEL_LINE_RE = re.compile(
    r"^\s*(?:\([a-z]\)\s*){2,}\s*$|"
    r"^\s*(?:Fig\.?|Figure|Table|Рис\.?|Рисунок|Табл\.?|Таблица)\s+"
    r"S?\d+[A-Za-zА-Яа-я]?(?:\s*\([a-zа-я]\))?\s*(?:[|.:\-–—]|$|\s)",
    re.IGNORECASE,
)
_LABEL_ONLY_LINE_RE = re.compile(
    r"^\s*(?:(?:\([a-z]\)|[a-z])(?:\s+|$)){2,}(?:S?\d+)?\s*$|^\s*S\d+\s*$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^(?:[-*•]|\(?[a-zA-Z0-9]{1,3}\)|\d+[.)])\s+")
_SENTENCE_END_RE = re.compile(r'[.!?;:]$|[.!?;:][\]})"\']$')
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_MOJIBAKE_CYRILLIC_RE = re.compile(r"(?:Р.|С.|Ð.|Ñ.|В«|В»|вЂ[“”™ўќ¦])")




__all__ = [name for name in globals() if name.startswith("_") and not name.startswith("__")]
