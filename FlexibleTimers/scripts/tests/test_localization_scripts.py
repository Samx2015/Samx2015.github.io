from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "scripts" / name
    module_name = name.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


navigation = load_script("generate-localization-navigation.py")
checker = load_script("check-localizations.py")
authoring = load_script("prepare-localized-page-drafts.py")


class WebsiteLocalizationScriptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(
            (ROOT / "generated" / "localizations.json").read_text(encoding="utf-8")
        )["localizations"]

    def test_inventory_and_menu_are_flag_free_and_complete(self) -> None:
        self.assertEqual(len(self.inventory), 45)
        identifiers = [item["identifier"] for item in self.inventory]
        self.assertEqual(len(set(identifiers)), 45)
        self.assertEqual(
            sum(item.get("lifecycle") == "new-2026" for item in self.inventory),
            11,
        )
        self.assertEqual(
            sum(item.get("lifecycle") == "existing" for item in self.inventory),
            34,
        )
        rendered = navigation.menu(self.inventory, "ur", True)
        self.assertEqual(rendered.count("<a "), 45)
        self.assertNotRegex(rendered, "[\U0001F1E6-\U0001F1FF]")
        self.assertIn('lang="ur" dir="rtl"', rendered)
        self.assertIn('lang="en" dir="ltr"', rendered)
        self.assertIn('aria-current="page">اردو</a>', rendered)

    def test_support_and_legal_routes_use_the_intended_canonical_hosts(self) -> None:
        support = navigation.alternates(
            self.inventory, "", "support.html", False
        )
        privacy = navigation.alternates(
            self.inventory, "", "privacy.html", False
        )
        self.assertIn(
            'hreflang="ur" href="https://xintechllc.com/XTimers/ur/support.html"',
            support,
        )
        self.assertIn(
            'hreflang="ur" href="https://xintechllc.com/FlexibleTimers/ur/privacy.html"',
            privacy,
        )
        self.assertEqual(
            checker.expected_alternates(self.inventory, "support.html", False)["ur"],
            "https://xintechllc.com/XTimers/ur/support.html",
        )

    def test_alternate_replacement_accepts_reordered_attributes_and_is_idempotent(self) -> None:
        content = (
            '<head>\n  <link rel="canonical" href="https://example.com/">\n'
            '  <link href="https://old.example/ar" hreflang="ar" rel="alternate"/>'
            '<link rel="alternate" hreflang="x-default" href="https://old.example/">\n'
            '</head>'
        )
        first = navigation.with_alternates(
            content,
            self.inventory,
            "index.html",
            True,
            Path("fixture.html"),
        )
        second = navigation.with_alternates(
            first,
            self.inventory,
            "index.html",
            True,
            Path("fixture.html"),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(navigation.ALTERNATE_TAG_PATTERN.findall(first)), 46)

    def test_canonical_and_asset_normalization_are_deterministic(self) -> None:
        path = ROOT / "ca" / "support.html"
        self.assertEqual(
            navigation.canonical_href(path, "ca", True, "support.html", False),
            "https://xintechllc.com/XTimers/ca/support.html",
        )
        source = '<link href="assets/site.css"><img src="assets/icon.png">'
        expected = '<link href="../assets/site.css"><img src="../assets/icon.png">'
        self.assertEqual(navigation.normalize_localized_assets(source), expected)
        self.assertEqual(navigation.normalize_localized_assets(expected), expected)

    def test_existing_translation_import_ignores_generated_structure(self) -> None:
        source = """<!doctype html><html><head>
        <meta name="description" content="Product description">
        <link rel="canonical" href="https://example.com/">
        </head><body><main><h1>Hello</h1>
        <details class="language-menu"><summary>English</summary>
        <div aria-label="Language"><a>English</a></div></details>
        <p>Support</p></main></body></html>"""
        localized = """<!doctype html><html><head>
        <meta name="description" content="Description du produit">
        <link rel="alternate" href="https://example.com/fr/">
        <link rel="canonical" href="https://example.com/fr/">
        </head><body><main>
        <p class="quote translation-note">Brouillon</p><h1>Bonjour</h1>
        <details class="language-menu"><summary>Français</summary>
        <div aria-label="Langue"><a>Français</a></div></details>
        <p>Assistance</p></main></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            localized_path = Path(directory) / "index.html"
            localized_path.write_text(localized, encoding="utf-8")
            values = authoring.imported_page_values(source, localized_path)
        self.assertEqual(values["Product description"], "Description du produit")
        self.assertEqual(values["Hello"], "Bonjour")
        self.assertEqual(values["Language"], "Langue")
        self.assertEqual(values["Support"], "Assistance")

    def test_localized_drafts_keep_local_pages_and_rebase_root_references(self) -> None:
        source = """<body>
        <a href="support.html">Support</a>
        <a href="terms.html">Terms</a>
        <a href="privacy-choices.html?source=footer#choices">Choices</a>
        <img src="assets/icon.png">
        <a href="https://example.com/">External</a>
        </body>"""
        soup = authoring.BeautifulSoup(source, "html.parser")
        authoring.adjust_relative_references(soup)
        self.assertEqual(soup.find(string="Support").parent["href"], "support.html")
        self.assertEqual(soup.find(string="Terms").parent["href"], "../terms.html")
        self.assertEqual(
            soup.find(string="Choices").parent["href"],
            "../privacy-choices.html?source=footer#choices",
        )
        self.assertEqual(soup.find("img")["src"], "../assets/icon.png")
        self.assertEqual(
            soup.find(string="External").parent["href"], "https://example.com/"
        )

    def test_localized_copy_preserves_the_html_doctype(self) -> None:
        soup = authoring.BeautifulSoup(
            "<!doctype html><html><body><p>Hello</p></body></html>",
            "html.parser",
        )
        authoring.replace_copy(soup, {"html": "visible artifact", "Hello": "Bonjour"})
        document = str(soup)
        self.assertTrue(document.startswith("<!DOCTYPE html>"))
        self.assertNotIn("visible artifact", document)
        self.assertIn("<p>Bonjour</p>", document)

    def test_landing_page_footer_does_not_repeat_the_final_section_divider(self) -> None:
        stylesheet = (ROOT / "assets" / "flexible-timers" / "site.css").read_text(
            encoding="utf-8"
        )
        footer_rule = stylesheet.split("    footer {", 1)[1].split("    }", 1)[0]
        self.assertNotIn("border-top", footer_rule)

    def test_website_checker_rejects_content_before_the_doctype(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "localized.html"
            path.write_text("html\n<html lang=\"fr\"></html>", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "doctype missing"):
                checker.parsed_page(path)

    def test_website_checker_rejects_empty_translation_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "1 empty values for fr"):
            checker.validate_translation_values(
                {"Empty": "Translate me", "Valid": "English"},
                {"Empty": "", "Valid": "Français"},
                "fr",
            )

    def test_website_checker_rejects_wrong_script_and_repeated_output(self) -> None:
        checker.validate_translation_values(
            {"Built": "Built for timers"},
            {"Built": "টাইমারের জন্য নির্মিত।"},
            "bn",
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected devanagari script for pa"):
            checker.validate_translation_values(
                {"Open": "Open settings"},
                {"Open": "सेटिंग्स खोलें"},
                "pa",
            )
        with self.assertRaisesRegex(RuntimeError, "repeated alphanumeric run for or"):
            checker.validate_translation_values(
                {"Open": "Open settings"},
                {"Open": "୯" * 32},
                "or",
            )

    def test_sitemap_generation_is_complete_and_idempotent(self) -> None:
        source = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://xintechllc.com/XTimers/</loc></url>
  <url><loc>https://xintechllc.com/XTimers/ur/</loc></url>
  <url><loc>https://xintechllc.com/XTimers/support.html</loc></url>
</urlset>
"""
        generated = navigation.updated_sitemap(source, self.inventory)
        self.assertEqual(generated.count("<loc>"), 46)
        self.assertIn("https://xintechllc.com/XTimers/bn/", generated)
        self.assertIn("https://xintechllc.com/XTimers/ur/", generated)
        self.assertEqual(navigation.updated_sitemap(generated, self.inventory), generated)

    def test_publisher_excludes_localization_authoring_artifacts(self) -> None:
        publisher = (ROOT / "scripts" / "publish.sh").read_text(encoding="utf-8")
        for exclusion in [
            "--exclude 'generated'",
            "--exclude 'requirements-localization.txt'",
            "--exclude '__pycache__'",
            "--exclude '*.pyc'",
        ]:
            self.assertIn(exclusion, publisher)
        self.assertIn('"$LOCALIZATION_RELEASE_GATE" --release', publisher)
        self.assertLess(
            publisher.index('"$LOCALIZATION_RELEASE_GATE" --release'),
            publisher.index('publish_to "$DEST_DIR_NEW"'),
        )
        compliance_check = (ROOT / "scripts" / "check-compliance-pages.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("-x .DS_Store", compliance_check)


if __name__ == "__main__":
    unittest.main()
