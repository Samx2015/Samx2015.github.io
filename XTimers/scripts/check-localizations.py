#!/usr/bin/env python3
"""Validate the static website localization inventory and generated routes."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import unicodedata
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
PRODUCT_BASE = "https://xintechllc.com/XTimers/"
LEGAL_BASE = "https://xintechllc.com/FlexibleTimers/"
PAGE_NAMES = (
    "index.html",
    "support.html",
    "terms.html",
    "privacy.html",
    "privacy-choices.html",
    "extension-privacy.html",
    "sms-terms.html",
    "sms-opt-in.html",
)
POLICY_PAGES = {
    "terms.html",
    "privacy.html",
    "privacy-choices.html",
    "extension-privacy.html",
    "sms-terms.html",
}
POLICY_EFFECTIVE_DATE = "2026-08-23"
POLICY_VISIBLE_DATE_SOURCE = "August 23, 2026"
ALARM_UI_TERMS = (
    "Rings On",
    "This Device",
    "Scheduled",
    "Pending Apply",
    "Pending Cancellation",
    "Needs Permission",
    "Unavailable",
    "Failed",
    "Sync Pending",
)
ALARM_TERM_FALLBACK_MARKER = "⟦XTIMERS-TERM-FALLBACK⟧"
APPROVED_ENGLISH_EQUAL_VALUES = {
    "%1$@admin@xintechllc.com%2$@",
    "EULA",
    "Mac • iPhone • iPad",
    "Mac",
    "iPhone",
    "iPhone · iPad",
    "Mac · iPhone · iPad",
    # Native sound-collection label in the unchanged application screenshots.
    "World Ceremonial",
    "Xin Account",
    "XTimers",
    "admin@xintechllc.com",
    "xintechllc.com/FlexibleTimers/privacy.html",
    "xintechllc.com/FlexibleTimers/sms-opt-in.html",
    "xintechllc.com/XTimers/support.html",
    "© 2017-2026 Xintech LLC.",
}
APPROVED_ENGLISH_EQUAL_VALUES_BY_LOCALE = {
    # French uses the same established noun for this support heading.
    "fr": {
        "Contact", "Questions",
        "%1$@%2$@%3$@Archives%4$@%5$@",
        "%1$@%2$@Routines%3$@↘%4$@%5$@",
        "%1$@09%2$@Archives",
    },
    # German product support uses this established English loanword unchanged.
    "de": {"Support", "Mac · separate app"},
    # These are established, correctly spelled local-language words or phrases.
    "it": {"Privacy"},
    "nb": {"XTimers for Mac", "For Mac, iPhone & iPad", "XTimers for iPhone & iPad"},
    "nl": {"Contact", "Privacy", "%1$@%2$@Routines%3$@↘%4$@%5$@"},
    "ro": {"Contact"},
    "sv": {"Support"},
}
FORMAT_SPECIFIER = re.compile(
    r"%(?!%)(?:\d+\$)?[-+#0 ']*\d*(?:\.\d+)?[hlLjztq]*[@diuoxXfFeEgGaAcCsSp]"
)
URL_OR_EMAIL = re.compile(
    r"https?://[^\s<>\"'%(),;!?]+|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|"
    r"(?<!\w)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}"
    r"(?:/[^\s<>\"'%(),;!?]*)?"
)
PROTECTED_LITERALS = (
    "Flexible Timers",
    "Xin Account",
    "Xintech LLC",
    "XHelpers Pro",
    "XTimers Pro",
    "XTimers",
    "SwiftUI",
    "App Store",
    "AlarmKit",
    "EventKit",
    "MetricKit",
    "FileVault",
    "Keychain",
    "Mac",
    "macOS",
    "iPhones",
    "iPhone",
    "iPad",
    "iOS",
    "Apple",
    "APNs",
    "CPU",
    "CSV",
    "DOL",
    "EULA",
    "GB",
    "GMT",
    "HTML",
    "IP",
    "JSON",
    "PDF",
    "SMS",
    "UI",
    "URL",
    "STOP",
    "HELP",
    "START",
    "YES",
)
# These writing systems conventionally attach imported Latin product names to
# surrounding text. Every other locale must visibly separate protected Latin
# names from translated words so token-glue corruption cannot reach a page.
PROTECTED_ADJACENCY_ALLOWED_LOCALES = {"ja", "ko", "zh-Hans", "zh-Hant"}
PROTECTED_SUFFIXES_BY_LOCALE = {
    "fi": {
        "XTimers": ("in", "ista", "istä", "iin", "illa", "ille", "ilta", "iltä"),
        "Mac": ("in", "issa", "ista", "illa", "ille"),
        "iPhone": ("n", "ssa", "sta", "lla", "lle"),
        "iPad": ("in", "issa", "ista", "illa", "ille"),
    },
    "pl": {
        "XTimers": ("a", "em", "owi", "ie", "u"),
        "Mac": ("a", "iem", "owi", "u"),
        "iPhone": ("a", "em", "owi", "ie", "u"),
        "iPad": ("a", "em", "owi", "zie", "u"),
    },
    "gu": {
        # Gujarati case markers are conventionally attached to Latin product
        # names (for example, XTimersના / XTimersની). Keep this explicit and
        # narrow so accidental translated-word glue remains a hard failure.
        "XTimers": ("ના", "ની", "નો", "ને"),
    },
    "sv": {
        "Apple": ("s",),
    },
}
TERMINAL_SENTENCE_PUNCTUATION = re.compile(r"[.!?…。！？।؛؟۔](?:[\"'”’»)\]]*)$")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
SCRIPT_RANGES = {
    "arabic": ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
               (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
    "bengali": ((0x0980, 0x09FF),),
    "bopomofo": ((0x3100, 0x312F), (0x31A0, 0x31BF)),
    "cjk": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
            (0x20000, 0x2FA1F)),
    "cyrillic": ((0x0400, 0x052F),),
    "devanagari": ((0x0900, 0x097F),),
    "greek": ((0x0370, 0x03FF),),
    "gujarati": ((0x0A80, 0x0AFF),),
    "gurmukhi": ((0x0A00, 0x0A7F),),
    "hangul": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7AF)),
    "hebrew": ((0x0590, 0x05FF),),
    "hiragana": ((0x3040, 0x309F),),
    "kannada": ((0x0C80, 0x0CFF),),
    "katakana": ((0x30A0, 0x30FF), (0x31F0, 0x31FF)),
    "malayalam": ((0x0D00, 0x0D7F),),
    "odia": ((0x0B00, 0x0B7F),),
    "tamil": ((0x0B80, 0x0BFF),),
    "telugu": ((0x0C00, 0x0C7F),),
    "thai": ((0x0E00, 0x0E7F),),
}
# U+0964/U+0965 are Unicode Common punctuation used across multiple Indic
# scripts, even though their code points sit inside the Devanagari block.
COMMON_SCRIPT_CODEPOINTS = {0x0964, 0x0965}
ALLOWED_SCRIPTS = {
    "ar": {"arabic"}, "bn": {"bengali"}, "el": {"greek"},
    "gu": {"gujarati"}, "he": {"hebrew"}, "hi": {"devanagari"},
    "ja": {"cjk", "hiragana", "katakana"}, "kn": {"kannada"},
    "ko": {"cjk", "hangul"}, "ml": {"malayalam"},
    "mr": {"devanagari"}, "or": {"odia"}, "pa": {"gurmukhi"},
    "ru": {"cyrillic"}, "ta": {"tamil"}, "te": {"telugu"},
    "th": {"thai"}, "uk": {"cyrillic"}, "ur": {"arabic"},
    "zh-Hans": {"bopomofo", "cjk"}, "zh-Hant": {"bopomofo", "cjk"},
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attributes: dict[str, str] | None = None
        self.canonicals: list[str] = []
        self.alternates: list[dict[str, str]] = []
        self.relative_references: list[str] = []
        self.references: list[str] = []
        self.ids: list[str] = []
        self.menu_count = 0
        self.menu_depth = 0
        self.menu_anchors: list[dict[str, str]] = []
        self.current_menu_anchor: dict[str, str] | None = None
        self.menu_text: list[str] = []
        self.policy_effective_dates: list[str] = []
        self.policy_sections: list[str] = []
        self.policy_visible_dates: list[tuple[str, str]] = []
        self.current_policy_time: dict[str, str] | None = None
        self.translation_note_count = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "html" and self.html_attributes is None:
            self.html_attributes = attributes
        classes = set(attributes.get("class", "").split())
        if tag == "meta" and attributes.get("name") == "xtimers-policy-effective-date":
            self.policy_effective_dates.append(attributes.get("content", ""))
        if attributes.get("data-policy-section"):
            self.policy_sections.append(attributes["data-policy-section"])
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        if tag == "time":
            self.current_policy_time = {
                "datetime": attributes.get("datetime", ""),
                "text": "",
            }
        if tag == "p" and "translation-note" in classes:
            self.translation_note_count += 1
        if tag == "details" and "language-menu" in classes:
            self.menu_count += 1
            self.menu_depth = 1
        elif self.menu_depth and tag not in VOID_TAGS:
            self.menu_depth += 1
        if self.menu_depth and tag == "a":
            self.current_menu_anchor = dict(attributes)
            self.current_menu_anchor["text"] = ""
            self.menu_anchors.append(self.current_menu_anchor)
        if tag == "link":
            relationships = attributes.get("rel", "").split()
            if "canonical" in relationships:
                self.canonicals.append(attributes.get("href", ""))
            if "alternate" in relationships:
                self.alternates.append(attributes)
        for attribute in ("href", "src", "data-zoom"):
            value = attributes.get(attribute)
            if value:
                self.references.append(value)
                if is_relative(value):
                    self.relative_references.append(value)
        for candidate in attributes.get("srcset", "").split(","):
            parts = candidate.strip().split()
            if parts:
                self.references.append(parts[0])
                if is_relative(parts[0]):
                    self.relative_references.append(parts[0])

    def handle_endtag(self, tag: str) -> None:
        if tag == "time" and self.current_policy_time is not None:
            self.policy_visible_dates.append(
                (
                    self.current_policy_time["datetime"],
                    self.current_policy_time["text"].strip(),
                )
            )
            self.current_policy_time = None
        if self.menu_depth and tag == "a":
            self.current_menu_anchor = None
        if self.menu_depth and tag not in VOID_TAGS:
            self.menu_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.current_policy_time is not None:
            self.current_policy_time["text"] += data
        if not self.menu_depth:
            return
        self.menu_text.append(data)
        if self.current_menu_anchor is not None:
            self.current_menu_anchor["text"] += data


def is_relative(value: str) -> bool:
    lowered = value.lower()
    return not (
        lowered.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:", "//", "#"))
    )


def parsed_page(path: Path) -> PageParser:
    parser = PageParser()
    document = path.read_text(encoding="utf-8")
    if not document.lower().startswith("<!doctype html>"):
        raise RuntimeError(f"HTML doctype missing or preceded by visible content in {path}")
    if "XQZTIMERS" in document:
        raise RuntimeError(f"Internal translation sentinel leaked into {path}")
    parser.feed(document)
    parser.close()
    return parser


def resolved_reference(page: Path, reference: str) -> Path:
    path = urllib.parse.urlsplit(reference).path
    candidate = (page.parent / path).resolve()
    if path.endswith("/") or candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate


def internal_reference_target(
    root: Path, page: Path, reference: str
) -> tuple[Path, str] | None:
    parsed = urllib.parse.urlsplit(reference)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme or parsed.netloc:
        if hostname == "xintechllc.com" and parsed.scheme != "https":
            raise RuntimeError(f"Insecure internal XTimers URL: {reference}")
        if parsed.scheme != "https" or hostname != "xintechllc.com":
            return None
        # This companion product is owned by a separate website checkout.
        if parsed.path == "/XHelpersPro/":
            return None
        product_prefixes = ("/XTimers", "/FlexibleTimers")
        prefix = next(
            (
                candidate
                for candidate in product_prefixes
                if parsed.path == candidate or parsed.path.startswith(candidate + "/")
            ),
            None,
        )
        if prefix is None:
            raise RuntimeError(f"Unsupported internal XTimers URL: {reference}")
        relative = urllib.parse.unquote(parsed.path[len(prefix) :]).lstrip("/")
        target = (root / relative).resolve()
    elif parsed.path.startswith("/"):
        raise RuntimeError(f"Unsupported root-relative internal URL: {reference}")
    elif not parsed.path:
        target = page.resolve()
    else:
        target = resolved_reference(page, reference)
    if target.name != "index.html" and (parsed.path.endswith("/") or target.is_dir()):
        target = target / "index.html"
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise RuntimeError(f"Internal reference escapes the website root: {reference}") from error
    return target, urllib.parse.unquote(parsed.fragment)


def validate_internal_references(
    root: Path,
    page: Path,
    parser: PageParser,
    parser_cache: dict[Path, PageParser] | None = None,
) -> None:
    cache = parser_cache if parser_cache is not None else {}
    if len(parser.ids) != len(set(parser.ids)):
        raise RuntimeError(f"Duplicate fragment identifier in {page}")
    cache[page.resolve()] = parser
    for reference in parser.references:
        resolved = internal_reference_target(root, page, reference)
        if resolved is None:
            continue
        target, fragment = resolved
        if not target.is_file():
            raise RuntimeError(f"Broken internal reference in {page}: {reference}")
        if not fragment:
            continue
        if target.suffix.lower() != ".html":
            raise RuntimeError(
                f"Fragment points to a non-HTML internal target in {page}: {reference}"
            )
        target_parser = cache.get(target.resolve())
        if target_parser is None:
            target_parser = parsed_page(target)
            cache[target.resolve()] = target_parser
        if fragment not in target_parser.ids:
            raise RuntimeError(f"Broken internal fragment in {page}: {reference}")


def load_generation_script(file_name: str):
    path = ROOT / "scripts" / file_name
    module_name = "website_equivalence_" + file_name.replace("-", "_").removesuffix(".py")
    specification = importlib.util.spec_from_file_location(module_name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Unable to load website generator: {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


def expected_localized_document(
    authoring,
    navigation,
    path: Path,
    identifier: str,
    direction: str,
    file_name: str,
    product_page: bool,
    inventory: list[dict],
    translations: dict[str, str],
) -> str:
    content = authoring.localized_document(
        ROOT,
        file_name,
        identifier,
        direction,
        inventory,
        translations,
    )
    content = navigation.normalize_localized_assets(content)
    content = navigation.with_canonical(
        content,
        navigation.canonical_href(
            path, identifier, True, file_name, product_page
        ),
        path,
    )
    if product_page:
        content, menu_count = navigation.MENU_PATTERN.subn(
            navigation.menu(
                inventory,
                identifier,
                True,
                translations["Language"],
            ),
            content,
            count=1,
        )
        if menu_count != 1:
            raise RuntimeError(
                f"Expected one generated language menu in {path}, found {menu_count}"
            )
    return navigation.with_alternates(
        content,
        inventory,
        file_name,
        product_page,
        path,
    )


def validate_generated_page_equivalence(path: Path, expected: str) -> None:
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        mismatch = next(
            (
                index
                for index, (left, right) in enumerate(zip(actual, expected))
                if left != right
            ),
            min(len(actual), len(expected)),
        )
        raise RuntimeError(
            f"Localized page is not the exact generated catalog output: {path} "
            f"(first mismatch at character {mismatch})"
        )


def has_regional_indicator(value: str) -> bool:
    return any(0x1F1E6 <= ord(character) <= 0x1F1FF for character in value)


def expected_alternates(
    inventory: list[dict], file_name: str, product_page: bool
) -> dict[str, str]:
    result: dict[str, str] = {}
    uses_product_base = product_page or file_name == "support.html"
    for item in inventory:
        if product_page:
            result[item["identifier"]] = (
                PRODUCT_BASE
                if item["identifier"] == "en"
                else PRODUCT_BASE + item["route"]
            )
        elif uses_product_base and item["identifier"] == "en":
            result[item["identifier"]] = PRODUCT_BASE + file_name
        elif uses_product_base:
            result[item["identifier"]] = (
                PRODUCT_BASE + item["identifier"] + "/" + file_name
            )
        elif item["identifier"] == "en":
            result[item["identifier"]] = LEGAL_BASE + file_name
        else:
            result[item["identifier"]] = (
                LEGAL_BASE + item["identifier"] + "/" + file_name
            )
    if product_page:
        result["x-default"] = PRODUCT_BASE
    elif uses_product_base:
        result["x-default"] = PRODUCT_BASE + file_name
    else:
        result["x-default"] = LEGAL_BASE + file_name
    return result


def expected_canonical(
    path: Path, identifier: str, file_name: str, product_page: bool
) -> str:
    localized = identifier != "en"
    if product_page:
        if localized:
            return PRODUCT_BASE + identifier + "/"
        return PRODUCT_BASE
    base = PRODUCT_BASE if file_name == "support.html" else LEGAL_BASE
    if localized:
        return base + identifier + "/" + file_name
    return base + file_name


def load_strings(path: Path) -> dict[str, str]:
    process = subprocess.run(
        ["plutil", "-convert", "json", "-o", "-", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"Invalid .strings file: {path}")
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected string dictionary: {path}")
    if any("XQZTIMERS" in str(key) or "XQZTIMERS" in str(item) for key, item in value.items()):
        raise RuntimeError(f"Internal translation sentinel leaked into {path}")
    return value


def validate_source_extraction(
    source: dict[str, str], extracted: set[str], serialized: str, expected_serialized: str
) -> None:
    expected = {value: value for value in extracted}
    if source != expected:
        missing = sorted(set(expected) - set(source))
        unexpected = sorted(set(source) - set(expected))
        changed = sorted(
            key for key in set(source) & set(expected) if source[key] != expected[key]
        )
        raise RuntimeError(
            "Website source catalog does not exactly match current English pages; "
            f"missing={missing[:3]}, unexpected={unexpected[:3]}, changed={changed[:3]}"
        )
    if serialized != expected_serialized:
        raise RuntimeError(
            "Website source catalog is not the deterministic current extraction"
        )


def normalized_english(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = " ".join(value.split())
    return value.strip(" \t\r\n.,;:!?…'\"“”‘’()[]{}")


def exact_literal_occurrences(value: str) -> list[tuple[str, int, int]]:
    candidates = [
        (
            token,
            re.compile(
                re.escape(token).replace(r"\ ", r"\s+")
            ),
        )
        for token in sorted(PROTECTED_LITERALS, key=lambda item: (-len(item), item))
    ]
    occurrences: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(value):
        matches = [
            (token, match)
            for token, pattern in candidates
            if (match := pattern.match(value, cursor)) is not None
        ]
        matched = next(
            (
                item
                for item in matches
                if not (
                    item[1].end() < len(value)
                    and unicodedata.name(value[item[1].end()], "").startswith("LATIN")
                    and any(
                        len(shorter_token) < len(item[0])
                        and item[0].startswith(shorter_token)
                        for shorter_token, _shorter_match in matches
                    )
                )
            ),
            matches[-1] if matches else None,
        )
        if matched is None:
            cursor += 1
            continue
        token, match = matched
        occurrences.append((token, match.start(), match.end()))
        cursor = match.end()
    return occurrences


def validate_value_signature(source: str, translated: str, identifier: str) -> None:
    source_urls = Counter(URL_OR_EMAIL.findall(source))
    translated_urls = Counter(URL_OR_EMAIL.findall(translated))
    if source_urls != translated_urls:
        raise RuntimeError(
            f"Website translation changed a URL/email signature for {identifier}: {source!r}"
        )

    source_formats = FORMAT_SPECIFIER.findall(source)
    translated_formats = FORMAT_SPECIFIER.findall(translated)
    if Counter(source_formats) != Counter(translated_formats):
        raise RuntimeError(
            f"Website translation changed a format-specifier signature for {identifier}: {source!r}"
        )
    if any("$" not in item for item in source_formats) and source_formats != translated_formats:
        raise RuntimeError(
            f"Website translation reordered positional format bindings for {identifier}: {source!r}"
        )
    if (
        "%" in source
        and TERMINAL_SENTENCE_PUNCTUATION.search(source.rstrip())
        and TERMINAL_SENTENCE_PUNCTUATION.search(translated.rstrip()) is None
    ):
        raise RuntimeError(
            f"Website inline-block translation dropped terminal punctuation for "
            f"{identifier}: {source!r}"
        )

    source_literals = Counter(item[0] for item in exact_literal_occurrences(source))
    translated_occurrences = exact_literal_occurrences(translated)
    translated_literals = Counter(item[0] for item in translated_occurrences)
    if source_literals != translated_literals:
        raise RuntimeError(
            f"Website translation changed a protected-token signature for {identifier}: "
            f"source={source!r}, translated={translated!r}"
        )
    if identifier in PROTECTED_ADJACENCY_ALLOWED_LOCALES:
        return
    for token, start, end in translated_occurrences:
        before = translated[start - 1] if start else ""
        after = translated[end] if end < len(translated) else ""
        suffixes = PROTECTED_SUFFIXES_BY_LOCALE.get(identifier, {}).get(token, ())
        allowed_suffix = any(translated.startswith(suffix, end) for suffix in suffixes)
        if any(
            character
            and unicodedata.category(character).startswith(("L", "M"))
            for character in (before, after)
        ) and not (not before.isalpha() and allowed_suffix):
            raise RuntimeError(
                f"Website translation glues protected token {token!r} to letters "
                f"for {identifier}: {source!r}"
            )


def validate_translation_values(
    source: dict[str, str], translation: dict[str, str], identifier: str
) -> None:
    if set(translation) != set(source):
        raise RuntimeError(f"Website translation key mismatch for {identifier}")
    fallback_keys = sorted(
        key
        for key, value in translation.items()
        if ALARM_TERM_FALLBACK_MARKER in value
    )
    if fallback_keys:
        raise RuntimeError(
            f"Website translation retains an alarm-term authoring fallback for "
            f"{identifier}: {fallback_keys[0]!r}"
        )
    empty = sorted(
        key
        for key, source_value in source.items()
        if source_value.strip() and not translation[key].strip()
    )
    if empty:
        raise RuntimeError(
            f"Website translation has {len(empty)} empty values for {identifier}"
        )
    english_equal = sorted(
        key
        for key, source_value in source.items()
        if source_value not in APPROVED_ENGLISH_EQUAL_VALUES
        and source_value
        not in APPROVED_ENGLISH_EQUAL_VALUES_BY_LOCALE.get(identifier, set())
        and normalized_english(translation[key]) == normalized_english(source_value)
    )
    if english_equal:
        raise RuntimeError(
            f"Website translation has {len(english_equal)} English-equal values "
            f"for {identifier}: {english_equal[:3]!r}"
        )
    allowed = ALLOWED_SCRIPTS.get(identifier, set())
    for key, translated in translation.items():
        source_value = source[key]
        validate_value_signature(source_value, translated, identifier)
        if len(translated) > max(512, len(source_value) * 8 + 128):
            raise RuntimeError(
                f"Website translation has suspicious expansion for {identifier}: {key!r}"
            )
        run_character = ""
        run_count = 0
        coverage_value = URL_OR_EMAIL.sub(" ", translated)
        coverage_value = FORMAT_SPECIFIER.sub(" ", coverage_value)
        for _token, start, end in reversed(exact_literal_occurrences(coverage_value)):
            coverage_value = coverage_value[:start] + " " + coverage_value[end:]
        source_coverage_value = URL_OR_EMAIL.sub(" ", source_value)
        source_coverage_value = FORMAT_SPECIFIER.sub(" ", source_coverage_value)
        for _token, start, end in reversed(
            exact_literal_occurrences(source_coverage_value)
        ):
            source_coverage_value = (
                source_coverage_value[:start] + " " + source_coverage_value[end:]
            )
        for character in translated:
            if character == run_character and character.isalnum():
                run_count += 1
            else:
                run_character = character
                run_count = 1
            if run_count >= 32:
                raise RuntimeError(
                    f"Website translation has a repeated alphanumeric run for "
                    f"{identifier}: {key!r}"
                )
            codepoint = ord(character)
            if codepoint in COMMON_SCRIPT_CODEPOINTS:
                continue
            family = next(
                (
                    name
                    for name, ranges in SCRIPT_RANGES.items()
                    if any(lower <= codepoint <= upper for lower, upper in ranges)
                ),
                None,
            )
            if family is not None and family not in allowed:
                raise RuntimeError(
                    f"Website translation has unexpected {family} script for "
                    f"{identifier}: {key!r}"
                )
        alphabetic_characters = sum(
            character.isalpha() for character in coverage_value
        )
        target_script_characters = sum(
            any(
                lower <= ord(character) <= upper
                for family in allowed
                for lower, upper in SCRIPT_RANGES[family]
            )
            for character in coverage_value
        )
        source_alphabetic_characters = sum(
            character.isalpha() for character in source_coverage_value
        )
        substantive_prose = source_alphabetic_characters >= 20
        if (
            allowed
            and substantive_prose
            and target_script_characters * 5 < alphabetic_characters
        ):
            raise RuntimeError(
                f"Website translation has insufficient target-script coverage for "
                f"{identifier}: {key!r}"
            )


def embedded_alarm_term(value: str) -> str:
    return value.strip().rstrip(".!?。！？।؛،").strip()


def validate_alarm_ui_terminology(
    source: dict[str, str], translation: dict[str, str], identifier: str
) -> None:
    missing_terms = [term for term in ALARM_UI_TERMS if term not in source]
    if missing_terms:
        raise RuntimeError(
            "Website source is missing alarm UI terms: " + ", ".join(missing_terms)
        )
    for term in ALARM_UI_TERMS:
        localized = embedded_alarm_term(translation.get(term, ""))
        if not localized:
            raise RuntimeError(f"Website alarm UI term is empty for {identifier}: {term}")

    for source_value, translated in translation.items():
        if source_value in ALARM_UI_TERMS:
            continue
        referenced_terms = [
            term for term in ALARM_UI_TERMS if term in source_value
        ]
        if not referenced_terms or not (
            "Rings On" in source_value or "This Device" in source_value
        ):
            continue
        folded_translation = translated.casefold()
        for term in referenced_terms:
            localized = embedded_alarm_term(translation[term])
            if localized.casefold() not in folded_translation:
                raise RuntimeError(
                    f"Website alarm UI term mismatch for {identifier}: "
                    f"{term!r} is not consistent in {source_value!r}"
                )


def validate_reviewed_translation_corrections(
    source: dict[str, str],
    translations: dict[str, dict[str, str]],
    corrections: dict[str, dict[str, str]],
    exact_overlays: dict[str, dict[str, str]] | None = None,
) -> None:
    exact_overlays = exact_overlays or {}
    for identifier, localized_corrections in corrections.items():
        translation = translations.get(identifier)
        if translation is None:
            raise RuntimeError(
                f"Reviewed translation correction has no catalog: {identifier}"
            )
        for source_fragment, expected_fragment in localized_corrections.items():
            matching_keys = [key for key in source if source_fragment in key]
            if not matching_keys:
                # Historical review artifacts also retain retired website copy.
                # Only fragments present in the current source govern its catalog.
                continue
            for matching_key in matching_keys:
                if (
                    matching_key in exact_overlays.get(identifier, {})
                    and source_fragment != matching_key
                ):
                    # A reviewed complete-value overlay supersedes an older
                    # fragment repair for the same source sentence.
                    continue
                localized_value = translation.get(matching_key, "")
                if source_fragment == matching_key:
                    valid = localized_value == expected_fragment
                else:
                    valid = expected_fragment in localized_value
                if not valid:
                    raise RuntimeError(
                        f"Reviewed translation correction is missing for {identifier}: "
                        f"{source_fragment!r}"
                    )


def validate_alarm_terms_against_app(
    website_source: dict[str, str],
    translations: dict[str, dict[str, str]],
    localization_root: Path,
) -> None:
    if not localization_root.is_dir():
        raise RuntimeError(
            f"Alarm-term source directory does not exist: {localization_root}"
        )
    english_path = localization_root / "en.lproj" / "Localizable.strings"
    if not english_path.is_file():
        raise RuntimeError(f"Missing app alarm-term source catalog: {english_path}")
    english = load_strings(english_path)
    supported_terms = [term for term in ALARM_UI_TERMS if term in english]
    if not supported_terms:
        raise RuntimeError(
            f"App English catalog has no supported alarm UI terms: {english_path}"
        )
    for term in supported_terms:
        website_english = website_source.get(term)
        if website_english != term or english.get(term) != website_english:
            raise RuntimeError(
                f"App English alarm UI term differs from WebsiteSource: {term}; "
                f"website={website_english!r}, app={english.get(term)!r}"
            )
    comparisons = 0
    for identifier, website in sorted(translations.items()):
        app_path = localization_root / f"{identifier}.lproj" / "Localizable.strings"
        if not app_path.is_file():
            raise RuntimeError(f"Missing app alarm-term catalog: {app_path}")
        app = load_strings(app_path)
        for term in supported_terms:
            if not app.get(term, "").strip():
                raise RuntimeError(
                    f"App alarm UI localized value is missing for {identifier}: {term}"
                )
            if website.get(term) != app[term]:
                raise RuntimeError(
                    f"Website alarm UI term differs from app for {identifier}: {term}"
                )
            comparisons += 1
    print(
        f"Website alarm UI terminology matches app catalogs: {comparisons} values "
        f"across {len(supported_terms)} supported source keys."
    )


def validate_policy_date(
    parser: PageParser, path: Path, expected_visible_date: str
) -> None:
    if parser.policy_effective_dates != [POLICY_EFFECTIVE_DATE]:
        raise RuntimeError(f"Policy effective-date metadata mismatch in {path}")
    expected = [(POLICY_EFFECTIVE_DATE, expected_visible_date)]
    if parser.policy_visible_dates != expected:
        raise RuntimeError(
            f"Policy visible-date mismatch in {path}: expected {expected}, "
            f"found {parser.policy_visible_dates}"
        )


def expected_localized_policy_date(
    authoring, file_name: str, translations: dict[str, str]
) -> str:
    soup = authoring.BeautifulSoup(
        (ROOT / file_name).read_text(encoding="utf-8"), "html.parser"
    )
    candidates: list[tuple[str, list[dict[str, str]]]] = []
    for block in authoring.inline_translation_blocks(soup):
        template, placeholders = authoring.inline_translation_template(block)
        if any(
            item["kind"] == "open"
            and item["name"] == "time"
            and f'datetime="{POLICY_EFFECTIVE_DATE}"' in item["markup"]
            for item in placeholders
        ):
            candidates.append((template, placeholders))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one canonical visible policy date block in {file_name}, "
            f"found {len(candidates)}"
        )
    template, placeholders = candidates[0]
    translated = translations.get(template)
    if not translated:
        raise RuntimeError(
            f"Localized policy date block is missing for {file_name}: {template!r}"
        )
    restored = authoring.restored_inline_translation(translated, placeholders)
    times = restored.find_all("time", attrs={"datetime": POLICY_EFFECTIVE_DATE})
    if len(times) != 1 or not times[0].get_text(strip=True):
        raise RuntimeError(f"Localized policy date is missing for {file_name}")
    return times[0].get_text(strip=True)


def validate_english_only_compliance(inventory: list[dict]) -> None:
    path = ROOT / "compliance.html"
    parser = parsed_page(path)
    expected = LEGAL_BASE + "compliance.html"
    if parser.canonicals != [expected]:
        raise RuntimeError(
            f"English-only compliance canonical mismatch: {parser.canonicals}"
        )
    localized = [
        ROOT / item["identifier"] / "compliance.html"
        for item in inventory
        if item["identifier"] != "en"
        and (ROOT / item["identifier"] / "compliance.html").exists()
    ]
    if localized:
        raise RuntimeError(
            "English-only compliance page has unexpected locale variants: "
            + ", ".join(str(item) for item in localized[:3])
        )


def validate_sitemap(path: Path, expected_urls: list[str]) -> None:
    root = ET.parse(path).getroot()
    location_tag = f"{{{SITEMAP_NAMESPACE}}}loc"
    locations = [
        element.text or ""
        for element in root.iter(location_tag)
    ]
    if len(locations) != len(set(locations)):
        raise RuntimeError("Sitemap contains duplicate URLs")
    if locations != expected_urls:
        missing = sorted(set(expected_urls) - set(locations))
        unexpected = sorted(set(locations) - set(expected_urls))
        raise RuntimeError(
            "Sitemap URLs do not exactly match the canonical page inventory; "
            f"missing={missing[:3]}, unexpected={unexpected[:3]}"
        )


def expected_locale_ids(inventory: list[dict]) -> set[str]:
    return {item["identifier"] for item in inventory if item["identifier"] != "en"}


def validate_localized_html_inventory(root: Path, identifiers: list[str]) -> None:
    expected = set(PAGE_NAMES)
    for identifier in identifiers:
        if identifier == "en":
            continue
        locale_root = root / identifier
        actual = {
            path.name
            for path in locale_root.iterdir()
            if path.is_file() and path.suffix.lower() == ".html"
        }
        if actual != expected:
            raise RuntimeError(
                f"Localized HTML inventory mismatch for {identifier}; "
                f"missing={sorted(expected - actual)}, "
                f"unexpected={sorted(actual - expected)}"
            )


def validate_value_provenance(
    source_path: Path,
    translation_root: Path,
    translations: dict[str, dict[str, str]],
    provenance_path: Path,
) -> None:
    if not provenance_path.is_file():
        raise RuntimeError("Missing website value-provenance inventory")
    document = json.loads(provenance_path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1:
        raise RuntimeError("Unsupported website value-provenance schema")
    if document.get("sourceSHA256") != hashlib.sha256(source_path.read_bytes()).hexdigest():
        raise RuntimeError("Website value-provenance source checksum is stale")
    locales = document.get("locales")
    if not isinstance(locales, dict) or set(locales) != set(translations):
        raise RuntimeError("Website value-provenance locale inventory mismatch")
    rejected: list[tuple[str, str]] = []
    allowed = {"gpt-authored", "human-or-unknown", "non-gpt-provider-authored"}
    for identifier, catalog in translations.items():
        path = translation_root / f"{identifier}.lproj" / "Website.strings"
        locale = locales.get(identifier)
        if not isinstance(locale, dict):
            raise RuntimeError(f"Malformed website value provenance for {identifier}")
        if locale.get("catalogSHA256") != hashlib.sha256(path.read_bytes()).hexdigest():
            raise RuntimeError(f"Website value provenance is stale for {identifier}")
        entries = locale.get("values")
        if not isinstance(entries, list):
            raise RuntimeError(f"Malformed website value provenance for {identifier}")
        by_source: dict[str, dict[str, object]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
                raise RuntimeError(f"Malformed website value provenance for {identifier}")
            source = str(entry["source"])
            if source in by_source:
                raise RuntimeError(f"Duplicate website value provenance for {identifier}")
            by_source[source] = entry
        if set(by_source) != set(catalog):
            raise RuntimeError(f"Website value-provenance key mismatch for {identifier}")
        for source, translated in catalog.items():
            entry = by_source[source]
            classification = entry.get("classification")
            if classification not in allowed:
                raise RuntimeError(f"Unknown website value provenance for {identifier}")
            expected_hash = hashlib.sha256(translated.encode("utf-8")).hexdigest()
            if entry.get("translationSHA256") != expected_hash:
                raise RuntimeError(f"Website value provenance is stale for {identifier}")
            if classification == "non-gpt-provider-authored":
                rejected.append((identifier, source))
    if rejected:
        sample = ", ".join(f"{identifier}:{source!r}" for identifier, source in rejected[:3])
        raise RuntimeError(
            f"Website contains {len(rejected)} non-GPT provider-authored values; "
            f"direct Codex/GPT replacement is required ({sample})"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--alarm-term-source",
        type=Path,
        action="append",
        help=(
            "Require all localized central alarm UI terms to exactly match "
            "the supplied app Resources directory. May be repeated to bind "
            "multiple app catalogs."
        ),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    inventory_document = json.loads(
        (ROOT / "generated" / "localizations.json").read_text(encoding="utf-8")
    )
    inventory = inventory_document.get("localizations")
    if not isinstance(inventory, list) or len(inventory) != 45:
        raise RuntimeError("Generated inventory must contain exactly 45 routes")
    identifiers = [item["identifier"] for item in inventory]
    if len(set(identifiers)) != 45 or identifiers.count("en") != 1:
        raise RuntimeError("Generated localization identifiers must be unique")
    descriptors = {item["identifier"]: item for item in inventory}
    authoring = load_generation_script("prepare-localized-page-drafts.py")
    source_path = ROOT / "generated" / "WebsiteSource.strings"
    source = load_strings(source_path)
    extracted = authoring.extracted_values(ROOT)
    validate_source_extraction(
        source,
        extracted,
        source_path.read_text(encoding="utf-8"),
        authoring.strings_document(extracted),
    )
    translations_by_identifier = {
        identifier: load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / f"{identifier}.lproj"
            / "Website.strings"
        )
        for identifier in identifiers
        if identifier != "en"
    }
    validate_value_provenance(
        source_path,
        ROOT / "generated" / "WebsiteTranslations",
        translations_by_identifier,
        ROOT / "generated" / "WebsiteValueProvenance.json",
    )
    validate_reviewed_translation_corrections(
        source,
        translations_by_identifier,
        authoring.REVIEWED_TRANSLATION_CORRECTIONS,
        authoring.reviewed_overlay,
    )
    navigation = load_generation_script("generate-localization-navigation.py")
    expected_policy_sections = {
        file_name: parsed_page(ROOT / file_name).policy_sections
        for file_name in POLICY_PAGES
    }
    validate_sitemap(
        ROOT / "sitemap.xml", navigation.expected_sitemap_urls(inventory)
    )
    validate_english_only_compliance(inventory)

    # `auth` holds the branded OAuth completion pages, which are a fixed
    # endpoint the provider redirects to rather than product content: they are
    # not localized routes, and treating every top-level directory as a locale
    # made this check fail on them.
    # Guides, press materials, and the historical download archive are English pages.
    ignored_directories = {"assets", "generated", "scripts", "auth", "guides", "press", "History"}
    actual_directories = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name not in ignored_directories
    }
    expected_directories = set(identifiers) - {"en"}
    if actual_directories != expected_directories:
        raise RuntimeError(
            f"Localized directory mismatch; missing={sorted(expected_directories - actual_directories)}, "
            f"unexpected={sorted(actual_directories - expected_directories)}"
        )
    validate_localized_html_inventory(ROOT, identifiers)

    pages: list[tuple[Path, str, str, bool]] = [
        (ROOT / "index.html", "en", "index.html", True),
        (ROOT / "flexible-timers.html", "en", "index.html", True),
    ]
    pages.extend(
        (ROOT / file_name, "en", file_name, False)
        for file_name in PAGE_NAMES
        if file_name != "index.html"
    )
    pages.extend(
        (ROOT / identifier / file_name, identifier, file_name, file_name == "index.html")
        for identifier in identifiers
        if identifier != "en"
        for file_name in PAGE_NAMES
    )

    reference_parsers: dict[Path, PageParser] = {}
    for path, identifier, file_name, product_page in pages:
        if not path.is_file():
            raise RuntimeError(f"Missing localized website page: {path}")
        if identifier != "en":
            expected_document = expected_localized_document(
                authoring,
                navigation,
                path,
                identifier,
                descriptors[identifier]["direction"],
                file_name,
                product_page,
                inventory,
                translations_by_identifier[identifier],
            )
            validate_generated_page_equivalence(path, expected_document)
        parser = parsed_page(path)
        html = parser.html_attributes or {}
        declared_language = html.get("lang")
        if identifier == "en":
            if declared_language not in {"en", "en-US"}:
                raise RuntimeError(f"Incorrect English lang value in {path}: {declared_language}")
        elif declared_language != identifier:
            raise RuntimeError(f"Incorrect lang value in {path}: {declared_language}")
        expected_direction = descriptors[identifier]["direction"]
        if expected_direction == "rtl" and html.get("dir") != "rtl":
            raise RuntimeError(f"Missing RTL direction in {path}")
        if expected_direction == "ltr" and html.get("dir") == "rtl":
            raise RuntimeError(f"Unexpected RTL direction in {path}")

        canonical = expected_canonical(path, identifier, file_name, product_page)
        if parser.canonicals != [canonical]:
            raise RuntimeError(
                f"Canonical URL mismatch in {path}: expected {canonical}, "
                f"found {parser.canonicals}"
            )

        alternates = {item.get("hreflang", ""): item.get("href", "") for item in parser.alternates}
        expected = expected_alternates(inventory, file_name, product_page)
        if alternates != expected or len(parser.alternates) != len(expected):
            raise RuntimeError(f"Alternate-language links are incomplete or duplicated in {path}")

        validate_internal_references(ROOT, path, parser, reference_parsers)

        if file_name in POLICY_PAGES:
            expected_visible_date = (
                POLICY_VISIBLE_DATE_SOURCE
                if identifier == "en"
                else expected_localized_policy_date(
                    authoring,
                    file_name,
                    translations_by_identifier[identifier],
                )
            )
            validate_policy_date(parser, path, expected_visible_date)
            if parser.policy_sections != expected_policy_sections[file_name]:
                raise RuntimeError(f"Policy section parity mismatch in {path}")
            if identifier != "en" and parser.translation_note_count != 1:
                raise RuntimeError(f"Expected one English-governs notice in {path}")
            if (
                identifier != "en"
                and "https://xintechllc.com/XTimers/support.html" in parser.references
            ):
                raise RuntimeError(f"Localized policy links to English support in {path}")

        if product_page:
            if parser.menu_count != 1:
                raise RuntimeError(f"Expected one language menu in {path}")
            menu_ids = [anchor.get("lang") for anchor in parser.menu_anchors]
            if menu_ids != identifiers:
                raise RuntimeError(f"Language menu inventory/order mismatch in {path}")
            if has_regional_indicator("".join(parser.menu_text)):
                raise RuntimeError(f"Country flag found in language menu: {path}")
            for anchor, expected_identifier in zip(parser.menu_anchors, identifiers):
                if anchor.get("text", "").strip() != descriptors[expected_identifier]["nativeName"]:
                    raise RuntimeError(f"Language menu label mismatch in {path}")
                target = resolved_reference(path, anchor.get("href", ""))
                if not target.is_file():
                    raise RuntimeError(f"Language menu target missing in {path}: {anchor.get('href')}")
            current = [
                anchor.get("lang")
                for anchor in parser.menu_anchors
                if anchor.get("aria-current") == "page"
            ]
            if current != [identifier]:
                raise RuntimeError(f"Language menu current-page marker mismatch in {path}")

    for identifier in identifiers:
        if identifier == "en":
            continue
        translation = translations_by_identifier[identifier]
        validate_translation_values(source, translation, identifier)
        validate_alarm_ui_terminology(source, translation, identifier)

    for alarm_term_source in arguments.alarm_term_source or []:
        validate_alarm_terms_against_app(
            source, translations_by_identifier, alarm_term_source.resolve()
        )

    print(
        f"Website localization valid: {len(identifiers)} routes, "
        f"{len(pages)} pages, no language-menu flags."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
