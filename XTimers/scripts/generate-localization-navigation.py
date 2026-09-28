#!/usr/bin/env python3
"""Generate flag-free product-page language menus and alternate links."""

from __future__ import annotations

import argparse
from html import escape as html_escape
import json
import re
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


BASE_URL = "https://xintechllc.com/XTimers/"
LEGAL_BASE_URL = "https://xintechllc.com/FlexibleTimers/"
MENU_PATTERN = re.compile(
    r'<details class="language-menu">.*?</details>', re.DOTALL
)
ALTERNATE_TAG_PATTERN = re.compile(
    r'<link\b(?=[^>]*\brel=["\']alternate["\'])[^>]*>',
    re.IGNORECASE,
)
CANONICAL_PATTERN = re.compile(r'<link\b(?=[^>]*\brel="canonical")[^>]*>')
HEAD_CLOSE_PATTERN = re.compile(r'</head>', re.IGNORECASE)
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
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
IDENTIFIER_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z][A-Za-z]{1,7})?$")
ENGLISH_SITEMAP_URLS = (
    BASE_URL,
    BASE_URL + "support.html",
    LEGAL_BASE_URL + "terms.html",
    LEGAL_BASE_URL + "privacy.html",
    LEGAL_BASE_URL + "privacy-choices.html",
    LEGAL_BASE_URL + "extension-privacy.html",
    LEGAL_BASE_URL + "sms-terms.html",
    LEGAL_BASE_URL + "sms-opt-in.html",
    LEGAL_BASE_URL + "compliance.html",
)


def validate_inventory(localizations: list[dict]) -> None:
    for item in localizations:
        identifier = item.get("identifier")
        direction = item.get("direction")
        route = item.get("route")
        native_name = item.get("nativeName")
        if not isinstance(identifier, str) or IDENTIFIER_PATTERN.fullmatch(identifier) is None:
            raise RuntimeError(f"Unsafe localization identifier: {identifier!r}")
        if direction not in {"ltr", "rtl"}:
            raise RuntimeError(f"Unsafe localization direction for {identifier}: {direction!r}")
        expected_route = "flexible-timers.html" if identifier == "en" else f"{identifier}/"
        if route != expected_route:
            raise RuntimeError(f"Unsafe localization route for {identifier}: {route!r}")
        if (
            not isinstance(native_name, str)
            or not native_name.strip()
            or len(native_name) > 80
            or any(ord(character) < 0x20 for character in native_name)
        ):
            raise RuntimeError(f"Unsafe native language name for {identifier}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "generated"
        / "localizations.json",
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--translation-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "generated"
        / "WebsiteTranslations",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def menu(
    localizations: list[dict],
    current: str,
    localized_page: bool,
    translated_label: str = "Language",
) -> str:
    current_name = next(
        item["nativeName"] for item in localizations if item["identifier"] == current
    )
    lines = [
        '<details class="language-menu">',
        f"            <summary>🌐 · {html_escape(current_name)}</summary>",
        f'            <div class="language-menu-list" aria-label="{html_escape(translated_label, quote=True)}">',
    ]
    for item in localizations:
        identifier = item["identifier"]
        if identifier == "en":
            href = "../" if localized_page else "./"
        else:
            prefix = "../" if localized_page else ""
            href = prefix + item["route"]
        current_attribute = ' aria-current="page"' if identifier == current else ""
        lines.append(
            f'              <a href="{html_escape(href, quote=True)}" '
            f'lang="{html_escape(identifier, quote=True)}"'
            f' dir="{html_escape(item["direction"], quote=True)}"'
            f'{current_attribute}>{html_escape(item["nativeName"])}</a>'
        )
    lines.extend(["            </div>", "          </details>"])
    return "\n".join(lines)


def alternates(
    localizations: list[dict], indent: str, file_name: str, product_page: bool
) -> str:
    lines: list[str] = []
    uses_product_base = product_page or file_name == "support.html"
    for item in localizations:
        if product_page:
            href = (
                BASE_URL
                if item["identifier"] == "en"
                else BASE_URL + item["route"]
            )
        elif uses_product_base and item["identifier"] == "en":
            href = BASE_URL + file_name
        elif uses_product_base:
            href = BASE_URL + item["identifier"] + "/" + file_name
        elif item["identifier"] == "en":
            href = LEGAL_BASE_URL + file_name
        else:
            href = LEGAL_BASE_URL + item["identifier"] + "/" + file_name
        lines.append(
            f'{indent}<link rel="alternate" hreflang="{item["identifier"]}" '
            f'href="{href}">'
        )
    if product_page:
        default_href = BASE_URL
    elif uses_product_base:
        default_href = BASE_URL + file_name
    else:
        default_href = LEGAL_BASE_URL + file_name
    lines.append(
        f'{indent}<link rel="alternate" hreflang="x-default" '
        f'href="{default_href}">'
    )
    return "\n".join(lines)


def with_alternates(
    content: str,
    localizations: list[dict],
    file_name: str,
    product_page: bool,
    path: Path,
) -> str:
    matches = list(ALTERNATE_TAG_PATTERN.finditer(content))
    if matches:
        for left, right in zip(matches, matches[1:]):
            if content[left.end() : right.start()].strip():
                raise RuntimeError(
                    f"Alternate links are not one contiguous block in {path}"
                )
        line_start = content.rfind("\n", 0, matches[0].start()) + 1
        indentation = content[line_start : matches[0].start()]
        if indentation.strip():
            block_start = matches[0].start()
            indentation = ""
        else:
            block_start = line_start
        block_end = matches[-1].end()
        leading = (
            ""
            if block_start == 0 or content[:block_start].endswith(("\n", "\r"))
            else "\n"
        )
        trailing = "" if content[block_end:].startswith(("\n", "\r")) else "\n"
        return (
            content[:block_start]
            + leading
            + alternates(localizations, indentation, file_name, product_page)
            + trailing
            + content[block_end:]
        )

    canonical = CANONICAL_PATTERN.search(content)
    if canonical is None:  # Protected by with_canonical; retain fail-closed behavior.
        raise RuntimeError(f"Expected a canonical link in {path}")
    line_start = content.rfind("\n", 0, canonical.start()) + 1
    indentation = content[line_start : canonical.start()]
    if indentation.strip():
        indentation = ""
    return (
        content[: canonical.end()]
        + "\n"
        + alternates(localizations, indentation, file_name, product_page)
        + content[canonical.end() :]
    )


def canonical_href(
    path: Path,
    current: str,
    localized_page: bool,
    file_name: str,
    product_page: bool,
) -> str:
    if product_page:
        if localized_page:
            return BASE_URL + current + "/"
        return BASE_URL
    base = BASE_URL if file_name == "support.html" else LEGAL_BASE_URL
    if localized_page:
        return base + current + "/" + file_name
    return base + file_name


def with_canonical(content: str, href: str, path: Path) -> str:
    tag = f'<link rel="canonical" href="{href}">'
    if CANONICAL_PATTERN.search(content) is not None:
        return CANONICAL_PATTERN.sub(tag, content, count=1)
    match = HEAD_CLOSE_PATTERN.search(content)
    if match is None:
        raise RuntimeError(f"Expected a head element in {path}")
    return content[: match.start()] + "  " + tag + "\n" + content[match.start() :]


def normalize_localized_assets(content: str) -> str:
    for attribute in ("href", "src"):
        content = content.replace(f'{attribute}="assets/', f'{attribute}="../assets/')
        content = content.replace(f"{attribute}='assets/", f"{attribute}='../assets/")
    return content


def load_language_label(translation_root: Path, identifier: str) -> str:
    if identifier == "en":
        return "Language"
    path = translation_root / f"{identifier}.lproj" / "Website.strings"
    process = subprocess.run(
        ["plutil", "-extract", "Language", "raw", "-o", "-", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        reason = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Missing localized language-menu label in {path}: {reason}")
    label = process.stdout.decode("utf-8").strip()
    if not label or "XQZTIMERS" in label:
        raise RuntimeError(f"Invalid localized language-menu label in {path}")
    return label


def updated_page(
    path: Path,
    localizations: list[dict],
    current: str,
    localized_page: bool,
    file_name: str,
    product_page: bool,
    translated_label: str,
) -> str:
    content = path.read_text(encoding="utf-8")
    if localized_page:
        content = normalize_localized_assets(content)
    content = with_canonical(
        content,
        canonical_href(
            path, current, localized_page, file_name, product_page
        ),
        path,
    )
    if product_page:
        content, menu_count = MENU_PATTERN.subn(
            menu(localizations, current, localized_page, translated_label),
            content,
            count=1,
        )
        if menu_count != 1:
            raise RuntimeError(f"Expected one language menu in {path}, found {menu_count}")

    return with_alternates(
        content,
        localizations,
        file_name,
        product_page,
        path,
    )


def expected_sitemap_urls(localizations: list[dict]) -> list[str]:
    expected_urls = list(ENGLISH_SITEMAP_URLS)
    for item in localizations:
        identifier = item["identifier"]
        if identifier == "en":
            continue
        expected_urls.append(BASE_URL + item["route"])
        expected_urls.append(BASE_URL + identifier + "/support.html")
        expected_urls.extend(
            LEGAL_BASE_URL + identifier + "/" + page
            for page in PAGE_NAMES
            if page not in {"index.html", "support.html"}
        )
    return expected_urls


def updated_sitemap(content: str, localizations: list[dict]) -> str:
    ET.register_namespace("", SITEMAP_NAMESPACE)
    root = ET.fromstring(content)
    if root.tag != f"{{{SITEMAP_NAMESPACE}}}urlset":
        raise RuntimeError("Unexpected sitemap root element")
    location_tag = f"{{{SITEMAP_NAMESPACE}}}loc"
    url_tag = f"{{{SITEMAP_NAMESPACE}}}url"
    root.clear()
    for url in expected_sitemap_urls(localizations):
        element = ET.Element(url_tag)
        ET.SubElement(element, location_tag).text = url
        root.append(element)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    document = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + document + "\n"


def main() -> int:
    arguments = parse_arguments()
    inventory = json.loads(arguments.inventory.read_text(encoding="utf-8"))
    localizations = inventory.get("localizations")
    if not isinstance(localizations, list) or len(localizations) != 45:
        raise RuntimeError("Website inventory must contain exactly 45 localizations")
    identifiers = [item["identifier"] for item in localizations]
    if len(set(identifiers)) != 45 or "en" not in identifiers:
        raise RuntimeError("Website localization identifiers must be unique and include en")
    validate_inventory(localizations)

    pages: list[tuple[Path, str, bool, str, bool]] = [
        (arguments.root / "index.html", "en", False, "index.html", True),
        (
            arguments.root / "flexible-timers.html",
            "en",
            False,
            "index.html",
            True,
        ),
    ]
    pages.extend(
        (arguments.root / file_name, "en", False, file_name, False)
        for file_name in PAGE_NAMES
        if file_name != "index.html"
    )
    pages.extend(
        (
            arguments.root / identifier / file_name,
            identifier,
            True,
            file_name,
            file_name == "index.html",
        )
        for identifier in identifiers
        if identifier != "en"
        for file_name in PAGE_NAMES
    )

    stale: list[str] = []
    for path, current, localized_page, file_name, product_page in pages:
        if not path.is_file():
            raise RuntimeError(f"Missing localized product page: {path}")
        expected = updated_page(
            path,
            localizations,
            current,
            localized_page,
            file_name,
            product_page,
            load_language_label(arguments.translation_root, current),
        )
        actual = path.read_text(encoding="utf-8")
        if arguments.check:
            if actual != expected:
                stale.append(str(path))
        elif actual != expected:
            path.write_text(expected, encoding="utf-8")

    sitemap_path = arguments.root / "sitemap.xml"
    sitemap_actual = sitemap_path.read_text(encoding="utf-8")
    sitemap_expected = updated_sitemap(sitemap_actual, localizations)
    if arguments.check:
        if sitemap_actual != sitemap_expected:
            stale.append(str(sitemap_path))
    elif sitemap_actual != sitemap_expected:
        sitemap_path.write_text(sitemap_expected, encoding="utf-8")

    if stale:
        raise RuntimeError("Stale generated language navigation: " + ", ".join(stale))
    print(f"Localization navigation valid for {len(pages)} product pages.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
