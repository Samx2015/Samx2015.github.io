#!/usr/bin/env python3
"""Validate the static website localization inventory and generated routes."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
PRODUCT_BASE = "https://xintechllc.com/XTimers/"
LEGAL_BASE = "https://xintechllc.com/FlexibleTimers/"
PAGE_NAMES = ("index.html", "support.html", "privacy.html", "sms-terms.html", "sms-opt-in.html")
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
        self.menu_count = 0
        self.menu_depth = 0
        self.menu_anchors: list[dict[str, str]] = []
        self.current_menu_anchor: dict[str, str] | None = None
        self.menu_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "html" and self.html_attributes is None:
            self.html_attributes = attributes
        classes = set(attributes.get("class", "").split())
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
        for attribute in ("href", "src"):
            value = attributes.get(attribute)
            if value and is_relative(value):
                self.relative_references.append(value)

    def handle_endtag(self, tag: str) -> None:
        if self.menu_depth and tag == "a":
            self.current_menu_anchor = None
        if self.menu_depth and tag not in VOID_TAGS:
            self.menu_depth -= 1

    def handle_data(self, data: str) -> None:
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


def has_regional_indicator(value: str) -> bool:
    return any(0x1F1E6 <= ord(character) <= 0x1F1FF for character in value)


def expected_alternates(
    inventory: list[dict], file_name: str, product_page: bool
) -> dict[str, str]:
    result: dict[str, str] = {}
    uses_product_base = product_page or file_name == "support.html"
    for item in inventory:
        if product_page:
            result[item["identifier"]] = PRODUCT_BASE + item["route"]
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
        result["x-default"] = PRODUCT_BASE + "flexible-timers.html"
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
        if path.name == "flexible-timers.html":
            return PRODUCT_BASE + "flexible-timers.html"
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


def validate_translation_values(
    source: dict[str, str], translation: dict[str, str], identifier: str
) -> None:
    if set(translation) != set(source):
        raise RuntimeError(f"Website translation key mismatch for {identifier}")
    empty = sorted(
        key
        for key, source_value in source.items()
        if source_value.strip() and not translation[key].strip()
    )
    if empty:
        raise RuntimeError(
            f"Website translation has {len(empty)} empty values for {identifier}"
        )
    allowed = ALLOWED_SCRIPTS.get(identifier, set())
    for key, translated in translation.items():
        source_value = source[key]
        if len(translated) > max(512, len(source_value) * 8 + 128):
            raise RuntimeError(
                f"Website translation has suspicious expansion for {identifier}: {key!r}"
            )
        run_character = ""
        run_count = 0
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


def validate_sitemap(path: Path, inventory: list[dict]) -> None:
    root = ET.parse(path).getroot()
    location_tag = f"{{{SITEMAP_NAMESPACE}}}loc"
    locations = [
        element.text or ""
        for element in root.iter(location_tag)
    ]
    if len(locations) != len(set(locations)):
        raise RuntimeError("Sitemap contains duplicate URLs")
    expected = {
        PRODUCT_BASE + item["route"]
        for item in inventory
        if item["identifier"] != "en"
    }
    localized_product_urls = {
        location
        for location in locations
        if location.startswith(PRODUCT_BASE)
        and location != PRODUCT_BASE
        and location.endswith("/")
    }
    if localized_product_urls != expected:
        raise RuntimeError("Sitemap localized product routes do not match the inventory")


def main() -> int:
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
    validate_sitemap(ROOT / "sitemap.xml", inventory)

    ignored_directories = {"assets", "generated", "scripts"}
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

    for path, identifier, file_name, product_page in pages:
        if not path.is_file():
            raise RuntimeError(f"Missing localized website page: {path}")
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

        for reference in parser.relative_references:
            target = resolved_reference(path, reference)
            if not target.exists():
                raise RuntimeError(f"Broken relative reference in {path}: {reference}")

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

    source = load_strings(ROOT / "generated" / "WebsiteSource.strings")
    for identifier in identifiers:
        if identifier == "en":
            continue
        translation = load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / f"{identifier}.lproj"
            / "Website.strings"
        )
        validate_translation_values(source, translation, identifier)

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
