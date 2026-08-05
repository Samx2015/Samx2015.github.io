#!/usr/bin/env python3
"""Extract website copy and materialize unreviewed localized page drafts.

The script intentionally keeps translations in a separate .strings package so
the source checksum and page generation can be reviewed independently. It does
not publish the website.
"""

from __future__ import annotations

import argparse
from html import escape as html_escape
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup, Comment, Doctype, NavigableString, Tag
except ImportError as error:  # pragma: no cover - authoring environment guard
    raise SystemExit("BeautifulSoup 4 is required to prepare website drafts") from error


ROOT = Path(__file__).resolve().parent.parent
SOURCE_PAGES = ("index.html", "support.html", "privacy.html", "sms-terms.html", "sms-opt-in.html")
TRANSLATION_NOTE = (
    "This translation is provided for convenience. The English version is authoritative."
)
BASE_PRODUCT_URL = "https://xintechllc.com/XTimers/"
BASE_LEGAL_URL = "https://xintechllc.com/FlexibleTimers/"
MENU_PATTERN = re.compile(r'<details class="language-menu">.*?</details>', re.DOTALL)
INITIAL_POLICY_LOCALIZATION_REVISION = (
    "f340d4531b42c5a52ded1b717f0f4135cc70a22f"
)
EXPANDED_LOCALIZATION_REVISION = "d72a30da4721504c02bfc898b11016849cf5226c"
EXPANDED_EXISTING_LOCALES = {"ca", "el", "he", "hr", "hu", "pt-PT", "ro", "sk"}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--inventory", type=Path, default=ROOT / "generated" / "localizations.json"
    )
    parser.add_argument(
        "--source-strings",
        type=Path,
        default=ROOT / "generated" / "WebsiteSource.strings",
    )
    parser.add_argument(
        "--translation-root",
        type=Path,
        default=ROOT / "generated" / "WebsiteTranslations",
    )
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--import-existing", action="store_true")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--locales", nargs="*")
    return parser.parse_args()


def escaped(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def strings_document(values: set[str]) -> str:
    lines = [
        "/* Canonical English website copy for the 2026 localization expansion. */",
        "",
    ]
    lines.extend(f'"{escaped(value)}" = "{escaped(value)}";' for value in sorted(values))
    return "\n".join(lines) + "\n"


def localized_strings_document(values: dict[str, str]) -> str:
    lines = [
        "/* Imported website translation source. Qualified review is required for the 2026 delta. */",
        "",
    ]
    lines.extend(
        f'"{escaped(key)}" = "{escaped(values[key])}";' for key in sorted(values)
    )
    return "\n".join(lines) + "\n"


def load_strings(path: Path) -> dict[str, str]:
    process = subprocess.run(
        ["plutil", "-convert", "json", "-o", "-", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        reason = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Invalid .strings file {path}: {reason}")
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected string dictionary at {path}")
    return {str(key): str(item) for key, item in value.items()}


def is_translatable(value: str) -> bool:
    return bool(value.strip() and re.search(r"[A-Za-z]", value))


def excluded_text_node(node) -> bool:
    parent = node.parent
    if parent is None or parent.name in {"script", "style", "noscript"}:
        return True
    if parent.find_parent("details", class_="language-menu") is not None:
        return True
    if parent.name == "details" and "language-menu" in (parent.get("class") or []):
        return True
    return isinstance(node, Comment)


def extracted_values(root: Path) -> set[str]:
    values: set[str] = {TRANSLATION_NOTE}
    for file_name in SOURCE_PAGES:
        soup = BeautifulSoup((root / file_name).read_text(encoding="utf-8"), "html.parser")
        for node in soup.find_all(string=True):
            if excluded_text_node(node):
                continue
            value = str(node).strip()
            if is_translatable(value):
                values.add(value)
        for tag in soup.find_all(True):
            for attribute in ("aria-label", "alt", "title", "placeholder"):
                value = tag.get(attribute)
                if isinstance(value, str) and is_translatable(value):
                    values.add(value)
            if tag.name == "meta" and (
                tag.get("name") == "description"
                or tag.get("property") in {"og:description", "twitter:description"}
            ):
                value = tag.get("content")
                if isinstance(value, str) and is_translatable(value):
                    values.add(value)
    return values


def is_import_ignored_root(tag: Tag) -> bool:
    classes = tag.get("class") or []
    if tag.name == "details" and "language-menu" in classes:
        return True
    if tag.name == "p" and "translation-note" in classes:
        return True
    if tag.name == "link" and set(tag.get("rel") or []) & {"alternate", "canonical"}:
        return True
    return False


def is_within_import_ignored_structure(tag: Tag) -> bool:
    current: Tag | None = tag
    while current is not None:
        if is_import_ignored_root(current):
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def direct_child_tags(parent) -> list[Tag]:
    return [
        child
        for child in parent.children
        if isinstance(child, Tag) and not is_import_ignored_root(child)
    ]


def tag_path(tag: Tag, soup: BeautifulSoup) -> tuple[tuple[str, int], ...]:
    components: list[tuple[str, int]] = []
    current: Tag | BeautifulSoup = tag
    while current is not soup:
        parent = current.parent
        if parent is None:
            raise RuntimeError("Detached website element while importing translations")
        siblings = [child for child in direct_child_tags(parent) if child.name == current.name]
        components.append((current.name, siblings.index(current)))
        current = parent
    return tuple(reversed(components))


def tag_at_path(soup: BeautifulSoup, path: tuple[tuple[str, int], ...]) -> Tag:
    current: BeautifulSoup | Tag = soup
    for name, index in path:
        children = [child for child in direct_child_tags(current) if child.name == name]
        if index >= len(children):
            raise RuntimeError(f"Localized website structure diverged at tag path {path}")
        current = children[index]
    if not isinstance(current, Tag):
        raise RuntimeError(f"Localized website path is not a tag: {path}")
    return current


def direct_text_nodes(tag: Tag) -> list[NavigableString]:
    return [
        child
        for child in tag.children
        if isinstance(child, NavigableString)
        and not isinstance(child, Comment)
        and str(child).strip()
    ]


def add_imported_value(
    translations: dict[str, str], source: str, translated: str, context: str
) -> None:
    source = source.strip()
    translated = translated.strip()
    if not source or not translated:
        raise RuntimeError(f"Empty website translation at {context}")
    existing = translations.get(source)
    if existing is not None and existing != translated:
        print(
            f"warning: preserving first existing website translation for {source!r}; "
            f"skipping {translated!r} at {context}",
            file=sys.stderr,
        )
        return
    translations[source] = translated


def import_source_document(root: Path, locale: str, file_name: str) -> str:
    if file_name == "index.html":
        return (root / file_name).read_text(encoding="utf-8")
    revision = (
        EXPANDED_LOCALIZATION_REVISION
        if locale in EXPANDED_EXISTING_LOCALES
        else INITIAL_POLICY_LOCALIZATION_REVISION
    )
    process = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{file_name}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        reason = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Unable to read historical website source {revision}:{file_name}: {reason}"
        )
    return process.stdout.decode("utf-8")


def imported_page_values(
    source_document: str, localized_path: Path
) -> dict[str, str]:
    source = BeautifulSoup(source_document, "html.parser")
    localized = BeautifulSoup(localized_path.read_text(encoding="utf-8"), "html.parser")
    translations: dict[str, str] = {}

    for node in source.find_all(string=True):
        if excluded_text_node(node):
            continue
        source_value = str(node).strip()
        if not is_translatable(source_value) or not isinstance(node.parent, Tag):
            continue
        source_siblings = direct_text_nodes(node.parent)
        ordinal = source_siblings.index(node)
        try:
            localized_parent = tag_at_path(localized, tag_path(node.parent, source))
        except RuntimeError:
            continue
        localized_siblings = direct_text_nodes(localized_parent)
        if ordinal >= len(localized_siblings):
            continue
        add_imported_value(
            translations,
            source_value,
            str(localized_siblings[ordinal]),
            f"{localized_path}:{tag_path(node.parent, source)}:{ordinal}",
        )

    for source_tag in source.find_all(True):
        if is_within_import_ignored_structure(source_tag):
            continue
        try:
            localized_tag = tag_at_path(localized, tag_path(source_tag, source))
        except RuntimeError:
            continue
        for attribute in ("aria-label", "alt", "title", "placeholder"):
            source_value = source_tag.get(attribute)
            if isinstance(source_value, str) and is_translatable(source_value):
                translated = localized_tag.get(attribute)
                if not isinstance(translated, str):
                    continue
                add_imported_value(
                    translations,
                    source_value,
                    translated,
                    f"{localized_path}:{tag_path(source_tag, source)}:{attribute}",
                )
        if source_tag.name == "meta" and (
            source_tag.get("name") == "description"
            or source_tag.get("property") in {"og:description", "twitter:description"}
        ):
            source_value = source_tag.get("content")
            if isinstance(source_value, str) and is_translatable(source_value):
                translated = localized_tag.get("content")
                if not isinstance(translated, str):
                    continue
                add_imported_value(
                    translations,
                    source_value,
                    translated,
                    f"{localized_path}:{tag_path(source_tag, source)}:content",
                )

    source_menu = source.select_one("details.language-menu [aria-label]")
    localized_menu = localized.select_one("details.language-menu [aria-label]")
    if source_menu is not None:
        source_value = source_menu.get("aria-label")
        translated = localized_menu.get("aria-label") if localized_menu is not None else None
        if not isinstance(source_value, str) or not isinstance(translated, str):
            raise RuntimeError(f"Localized language-menu label missing in {localized_path}")
        add_imported_value(
            translations,
            source_value,
            translated,
            f"{localized_path}:language-menu:aria-label",
        )
    return translations


def import_existing_locale(root: Path, locale: str, output: Path) -> None:
    translations: dict[str, str] = {}
    expected = extracted_values(root) - {TRANSLATION_NOTE}
    for file_name in SOURCE_PAGES:
        localized_path = root / locale / file_name
        if not localized_path.is_file():
            raise RuntimeError(f"Missing existing localized page: {localized_path}")
        for source, translated in imported_page_values(
            import_source_document(root, locale, file_name), localized_path
        ).items():
            if source not in expected:
                continue
            add_imported_value(
                translations,
                source,
                translated,
                f"{locale}/{file_name}",
            )
    if len(translations) < 50:
        raise RuntimeError(
            f"Existing website import recovered only {len(translations)} of "
            f"{len(expected)} current keys for {locale}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(localized_strings_document(translations), encoding="utf-8")
    print(
        f"Preserved {len(translations)} existing translations for {locale}; "
        f"{len(expected - set(translations)) + 1} current keys require draft translation."
    )


def replace_copy(soup: BeautifulSoup, translations: dict[str, str]) -> None:
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Doctype) or excluded_text_node(node):
            continue
        original = str(node)
        stripped = original.strip()
        if stripped not in translations:
            continue
        leading = original[: len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()) :]
        node.replace_with(leading + translations[stripped] + trailing)
    for tag in soup.find_all(True):
        for attribute in ("aria-label", "alt", "title", "placeholder"):
            value = tag.get(attribute)
            if isinstance(value, str) and value in translations:
                tag[attribute] = translations[value]
        if tag.name == "meta" and (
            tag.get("name") == "description"
            or tag.get("property") in {"og:description", "twitter:description"}
        ):
            value = tag.get("content")
            if isinstance(value, str) and value in translations:
                tag["content"] = translations[value]


def adjust_relative_references(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        for attribute in ("href", "src"):
            value = tag.get(attribute)
            if not isinstance(value, str) or not value:
                continue
            if value.startswith(("/", "#", "?", "../", "./", "//")):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
                continue
            relative_path = value.split("#", 1)[0].split("?", 1)[0]
            if relative_path in SOURCE_PAGES:
                continue
            tag[attribute] = "../" + value


def set_canonical(soup: BeautifulSoup, locale: str, file_name: str) -> None:
    canonical = soup.find("link", rel="canonical")
    if canonical is None:
        canonical = soup.new_tag("link", rel="canonical")
        head = soup.find("head")
        if head is None:
            raise RuntimeError(f"English source lacks a head element: {file_name}")
        first_script = head.find("script")
        if first_script is not None:
            first_script.insert_before(canonical)
        else:
            head.append(canonical)
    if file_name == "index.html":
        canonical["href"] = f"{BASE_PRODUCT_URL}{locale}/"
    elif file_name == "support.html":
        canonical["href"] = f"{BASE_PRODUCT_URL}{locale}/{file_name}"
    else:
        canonical["href"] = f"{BASE_LEGAL_URL}{locale}/{file_name}"


def set_alternates(
    soup: BeautifulSoup, inventory: list[dict], file_name: str
) -> None:
    for link in list(soup.find_all("link", rel="alternate")):
        link.decompose()
    canonical = soup.find("link", rel="canonical")
    if canonical is None:
        raise RuntimeError(f"Page lacks canonical link: {file_name}")
    insertion_point = canonical
    for item in inventory:
        if file_name == "index.html":
            href = BASE_PRODUCT_URL + item["route"]
        elif file_name == "support.html":
            if item["identifier"] == "en":
                href = BASE_PRODUCT_URL + file_name
            else:
                href = BASE_PRODUCT_URL + item["identifier"] + "/" + file_name
        elif item["identifier"] == "en":
            href = BASE_LEGAL_URL + file_name
        else:
            href = BASE_LEGAL_URL + item["identifier"] + "/" + file_name
        link = soup.new_tag("link", rel="alternate", hreflang=item["identifier"], href=href)
        insertion_point.insert_after(link)
        insertion_point = link
    if file_name == "index.html":
        default_href = BASE_PRODUCT_URL + "flexible-timers.html"
    elif file_name == "support.html":
        default_href = BASE_PRODUCT_URL + file_name
    else:
        default_href = BASE_LEGAL_URL + file_name
    default = soup.new_tag("link", rel="alternate", hreflang="x-default", href=default_href)
    insertion_point.insert_after(default)


def add_translation_note(
    soup: BeautifulSoup, translated_note: str, file_name: str
) -> None:
    if file_name == "index.html":
        return
    heading = soup.find("h1")
    if heading is None:
        raise RuntimeError(f"English source lacks h1: {file_name}")
    note = soup.new_tag("p", attrs={"class": "quote translation-note"})
    note.append(translated_note + " ")
    link = soup.new_tag("a", href=f"../{file_name}")
    link.string = "English"
    note.append(link)
    heading.insert_after(note)


def language_menu(inventory: list[dict], locale: str, translated_label: str) -> str:
    native_name = next(item["nativeName"] for item in inventory if item["identifier"] == locale)
    lines = [
        '<details class="language-menu">',
        f"            <summary>🌐 · {native_name}</summary>",
        f'            <div class="language-menu-list" aria-label="{html_escape(translated_label, quote=True)}">',
    ]
    for item in inventory:
        current = ' aria-current="page"' if item["identifier"] == locale else ""
        lines.append(
            f'              <a href="../{item["route"]}" lang="{item["identifier"]}"'
            f'{current}>{item["nativeName"]}</a>'
        )
    lines.extend(["            </div>", "          </details>"])
    return "\n".join(lines)


def localized_document(
    root: Path,
    file_name: str,
    locale: str,
    direction: str,
    inventory: list[dict],
    translations: dict[str, str],
) -> str:
    soup = BeautifulSoup((root / file_name).read_text(encoding="utf-8"), "html.parser")
    replace_copy(soup, translations)
    html = soup.find("html")
    if html is None:
        raise RuntimeError(f"English source lacks html element: {file_name}")
    html["lang"] = locale
    if direction == "rtl":
        html["dir"] = "rtl"
    else:
        html.attrs.pop("dir", None)
    adjust_relative_references(soup)
    set_canonical(soup, locale, file_name)
    set_alternates(soup, inventory, file_name)
    add_translation_note(soup, translations[TRANSLATION_NOTE], file_name)
    document = str(soup)
    document = document.replace(
        "xintechllc.com/FlexibleTimers/support.html",
        f"xintechllc.com/FlexibleTimers/{locale}/support.html",
    )
    if file_name == "index.html":
        document, count = MENU_PATTERN.subn(
            language_menu(inventory, locale, translations["Language"]),
            document,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"Expected one product language menu for {locale}")
    return document.rstrip() + "\n"


def main() -> int:
    arguments = parse_arguments()
    if not arguments.extract and not arguments.import_existing and not arguments.generate:
        raise RuntimeError("Choose --extract, --import-existing, and/or --generate")
    inventory_document = json.loads(arguments.inventory.read_text(encoding="utf-8"))
    inventory = inventory_document.get("localizations")
    if not isinstance(inventory, list) or len(inventory) != 45:
        raise RuntimeError("Website inventory must contain exactly 45 localizations")

    source_values = extracted_values(arguments.root)
    if arguments.extract:
        arguments.source_strings.parent.mkdir(parents=True, exist_ok=True)
        arguments.source_strings.write_text(strings_document(source_values), encoding="utf-8")
        print(f"Extracted {len(source_values)} unique English website strings.")

    if arguments.import_existing:
        locales = arguments.locales or [
            item["identifier"]
            for item in inventory
            if item.get("identifier") != "en" and item.get("lifecycle") == "existing"
        ]
        descriptor_by_id = {item["identifier"]: item for item in inventory}
        for locale in locales:
            descriptor = descriptor_by_id.get(locale)
            if descriptor is None or descriptor.get("lifecycle") != "existing":
                raise RuntimeError(f"Invalid existing website import target: {locale}")
            import_existing_locale(
                arguments.root,
                locale,
                arguments.translation_root / f"{locale}.lproj" / "Website.strings",
            )
            print(f"Imported existing website translation source for {locale}.")

    if arguments.generate:
        locales = arguments.locales or [
            item["identifier"] for item in inventory if item.get("identifier") != "en"
        ]
        descriptor_by_id = {item["identifier"]: item for item in inventory}
        for locale in locales:
            descriptor = descriptor_by_id.get(locale)
            if descriptor is None or locale == "en":
                raise RuntimeError(f"Invalid localized website target: {locale}")
            translation_file = (
                arguments.translation_root / f"{locale}.lproj" / "Website.strings"
            )
            translations = load_strings(translation_file)
            missing = sorted(source_values - set(translations))
            if missing:
                raise RuntimeError(
                    f"Website translation package for {locale} is missing {len(missing)} keys"
                )
            output_directory = arguments.root / locale
            output_directory.mkdir(parents=True, exist_ok=True)
            for file_name in SOURCE_PAGES:
                output = localized_document(
                    arguments.root,
                    file_name,
                    locale,
                    descriptor["direction"],
                    inventory,
                    translations,
                )
                (output_directory / file_name).write_text(output, encoding="utf-8")
            print(f"Generated five unreviewed website pages for {locale}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
