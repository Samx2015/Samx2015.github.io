from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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
release_verifier = load_script("verify-published-localizations.py")


class WebsiteLocalizationScriptsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(
            (ROOT / "generated" / "localizations.json").read_text(encoding="utf-8")
        )["localizations"]

    def test_value_provenance_rejects_non_gpt_provider_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "WebsiteSource.strings"
            source_path.write_text('"Hello" = "Hello";\n', encoding="utf-8")
            catalog_path = root / "fr.lproj" / "Website.strings"
            catalog_path.parent.mkdir()
            catalog_path.write_text('"Hello" = "Bonjour";\n', encoding="utf-8")
            provenance_path = root / "WebsiteValueProvenance.json"

            def document(classification: str) -> dict[str, object]:
                return {
                    "schemaVersion": 1,
                    "sourceSHA256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    "locales": {
                        "fr": {
                            "catalogSHA256": hashlib.sha256(
                                catalog_path.read_bytes()
                            ).hexdigest(),
                            "values": [
                                {
                                    "source": "Hello",
                                    "translationSHA256": hashlib.sha256(
                                        "Bonjour".encode("utf-8")
                                    ).hexdigest(),
                                    "classification": classification,
                                    "evidence": "test",
                                }
                            ],
                        }
                    },
                }

            provenance_path.write_text(
                json.dumps(document("gpt-authored")), encoding="utf-8"
            )
            checker.validate_value_provenance(
                source_path,
                root,
                {"fr": {"Hello": "Bonjour"}},
                provenance_path,
            )
            provenance_path.write_text(
                json.dumps(document("non-gpt-provider-authored")), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                RuntimeError, "non-GPT provider-authored values"
            ):
                checker.validate_value_provenance(
                    source_path,
                    root,
                    {"fr": {"Hello": "Bonjour"}},
                    provenance_path,
                )

    def test_direct_gpt_full_catalog_reviews_are_complete(self) -> None:
        source = checker.load_strings(ROOT / "generated" / "WebsiteSource.strings")
        for path in sorted(
            (ROOT / "generated" / "DirectGPTWebsiteTranslations").glob("*.json")
        ):
            identifier = path.stem
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["locale"], identifier)
            self.assertEqual(document["authorship"], "direct-codex-gpt")
            self.assertEqual(
                document["reviewScope"],
                f"all-{len(source)}-values-retranslated-or-reaffirmed-from-English",
            )
            catalog = checker.load_strings(
                ROOT
                / "generated"
                / "WebsiteTranslations"
                / f"{identifier}.lproj"
                / "Website.strings"
            )
            self.assertEqual(set(document["translations"]), set(source))
            self.assertEqual(document["translations"], catalog)
            checker.validate_translation_values(source, catalog, identifier)

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
        self.assertIn('<a href="../" lang="en"', rendered)

    def test_reviewed_overlay_is_hash_bound_and_merged(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(authoring.REVIEWED_OVERLAY_PATH.read_bytes()).hexdigest(),
            authoring.REVIEWED_OVERLAY_SHA256,
        )
        overlay = json.loads(authoring.REVIEWED_OVERLAY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(overlay), 30)
        self.assertEqual(sum(len(values) for values in overlay.values()), 45)
        current_source = authoring.load_strings(
            ROOT / "generated" / "WebsiteSource.strings"
        )
        for identifier, values in overlay.items():
            for source, target in values.items():
                if source not in current_source:
                    continue
                direct_path = (
                    ROOT
                    / "generated"
                    / "DirectGPTWebsiteTranslations"
                    / f"{identifier}.json"
                )
                expected = target
                if direct_path.is_file():
                    expected = json.loads(direct_path.read_text(encoding="utf-8"))[
                        "translations"
                    ][source]
                self.assertEqual(
                    authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][source],
                    expected,
                )
        sample_source, sample_target = next(iter(overlay["ar"].items()))
        source = {sample_source: sample_source}
        defective = {sample_source: "ترجمة معيبة"}
        with mock.patch.dict(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS,
            {"test": {sample_source: sample_target}},
        ):
            corrected, count = authoring.reviewed_correction_values(
                source, defective, "test"
            )
        self.assertEqual(count, 1)
        self.assertEqual(corrected[sample_source], sample_target)

    def test_reviewed_alarm_terms_are_hash_bound_and_applied(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_ALARM_TERMS_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_ALARM_TERMS_SHA256,
        )
        overlay = json.loads(
            authoring.REVIEWED_ALARM_TERMS_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(len(overlay), 18)
        self.assertEqual(sum(len(values) for values in overlay.values()), 56)
        self.assertEqual(
            set(authoring.REVIEWED_ALARM_TERM_PREVIOUS_VALUES),
            set(overlay) | {"kn", "pa"},
        )
        for identifier, values in overlay.items():
            self.assertEqual(
                set(authoring.REVIEWED_ALARM_TERM_PREVIOUS_VALUES[identifier]),
                set(values),
            )
            for term, value in values.items():
                self.assertNotEqual(
                    authoring.REVIEWED_ALARM_TERM_PREVIOUS_VALUES[identifier][term],
                    value,
                )
        source = {term: term for term in authoring.ALARM_UI_TERMS}
        defective = dict(source)
        with mock.patch.object(authoring, "REVIEWED_TRANSLATION_CORRECTIONS", {}):
            corrected, count = authoring.reviewed_correction_values(
                source, defective, "bn"
            )
        self.assertEqual(count, len(overlay["bn"]))
        for term, expected in overlay["bn"].items():
            self.assertEqual(corrected[term], expected)

    def test_reviewed_kannada_overlays_are_hash_bound_and_applied(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_KANNADA_OVERLAY_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_KANNADA_OVERLAY_SHA256,
        )
        website_overlay = json.loads(
            authoring.REVIEWED_KANNADA_OVERLAY_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(website_overlay), {"kn"})
        self.assertEqual(len(website_overlay["kn"]), 39)
        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_KANNADA_SECOND_AUDIT_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_KANNADA_SECOND_AUDIT_SHA256,
        )
        second_audit_overlay = json.loads(
            authoring.REVIEWED_KANNADA_SECOND_AUDIT_PATH.read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(set(second_audit_overlay), {"kn"})
        self.assertEqual(len(second_audit_overlay["kn"]), 58)
        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_KANNADA_ALARM_TERMS_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_KANNADA_ALARM_TERMS_SHA256,
        )
        alarm_overlay = json.loads(
            authoring.REVIEWED_KANNADA_ALARM_TERMS_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(alarm_overlay), {"kn"})
        self.assertEqual(len(alarm_overlay["kn"]), 5)
        source = authoring.load_strings(ROOT / "generated" / "WebsiteSource.strings")
        catalog = authoring.load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / "kn.lproj"
            / "Website.strings"
        )
        direct = json.loads(
            (ROOT / "generated" / "DirectGPTWebsiteTranslations" / "kn.json").read_text(
                encoding="utf-8"
            )
        )["translations"]
        defective = dict(catalog)
        sample_key = next(key for key in website_overlay["kn"] if key in source)
        second_audit_key = next(
            key for key in second_audit_overlay["kn"] if key in source
        )
        sample_term = next(iter(alarm_overlay["kn"]))
        defective[sample_key] = "ದೋಷಪೂರಿತ ಅನುವಾದ"
        defective[second_audit_key] = "ಮತ್ತೊಂದು ದೋಷಪೂರಿತ ಅನುವಾದ"
        defective[sample_term] = "ತಪ್ಪಾದ ಸ್ಥಿತಿ"
        corrected, count = authoring.reviewed_correction_values(
            source, defective, "kn"
        )
        self.assertGreaterEqual(count, 2)
        for key in website_overlay["kn"].keys() & source.keys():
            self.assertEqual(corrected[key], direct[key])
        for key in second_audit_overlay["kn"].keys() & source.keys():
            self.assertEqual(corrected[key], direct[key])
        for term in alarm_overlay["kn"]:
            self.assertEqual(corrected[term], direct[term])
        self.assertNotIn(
            authoring.ALARM_TERM_FALLBACK_MARKER, "".join(corrected.values())
        )
        checker.validate_alarm_ui_terminology(source, corrected, "kn")
        checker.validate_translation_values(source, corrected, "kn")
        replayed, replay_count = authoring.reviewed_correction_values(
            source, corrected, "kn"
        )
        self.assertEqual(replay_count, 0)
        self.assertEqual(replayed, corrected)

    def test_kannada_second_audit_supersedes_stale_first_review(self) -> None:
        source_key = next(
            key
            for key in authoring.reviewed_kannada_second_audit["kn"]
            if key.startswith("XTimers uses your Xin Account")
        )
        expected = authoring.reviewed_kannada_second_audit["kn"][source_key]
        self.assertEqual(expected.count("XTimers"), source_key.count("XTimers"))
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["kn"][source_key],
            expected,
        )

    def test_inventory_validation_rejects_markup_and_path_injection(self) -> None:
        navigation.validate_inventory(self.inventory)
        authoring.validate_inventory(self.inventory)
        malicious = [dict(item) for item in self.inventory]
        malicious[0]["route"] = '../"><script>alert(1)</script>'
        with self.assertRaisesRegex(RuntimeError, "Unsafe localization route"):
            navigation.validate_inventory(malicious)
        malicious = [dict(item) for item in self.inventory]
        malicious[0]["identifier"] = 'ar" onmouseover="alert(1)'
        with self.assertRaisesRegex(RuntimeError, "Unsafe localization identifier"):
            authoring.validate_inventory(malicious)
        escaped = [dict(item) for item in self.inventory]
        escaped[0]["nativeName"] = "Arabic <Test> & More"
        rendered = navigation.menu(escaped, "ur", True)
        self.assertIn("Arabic &lt;Test&gt; &amp; More", rendered)
        self.assertNotIn("Arabic <Test>", rendered)

    def test_localized_html_inventory_rejects_an_extra_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locale_root = root / "fr"
            locale_root.mkdir()
            for page in checker.PAGE_NAMES:
                (locale_root / page).write_text("<!doctype html>", encoding="utf-8")
            checker.validate_localized_html_inventory(root, ["en", "fr"])
            (locale_root / "obsolete-policy.html").write_text(
                "<!doctype html>", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "unexpected=.*obsolete-policy"):
                checker.validate_localized_html_inventory(root, ["en", "fr"])

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
        for legal_page in (
            "terms.html",
            "privacy.html",
            "privacy-choices.html",
            "extension-privacy.html",
            "sms-terms.html",
        ):
            self.assertIn(legal_page, authoring.SOURCE_PAGES)
            self.assertIn(legal_page, checker.PAGE_NAMES)
            self.assertEqual(
                checker.expected_alternates(self.inventory, legal_page, False)["ur"],
                f"https://xintechllc.com/FlexibleTimers/ur/{legal_page}",
            )
        for legal_page in ("privacy-choices.html", "extension-privacy.html"):
            html = (ROOT / legal_page).read_text(encoding="utf-8")
            self.assertIn(
                f'<link rel="canonical" '
                f'href="https://xintechllc.com/FlexibleTimers/{legal_page}">',
                html,
            )

    def test_internal_link_validation_checks_local_and_absolute_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.html"
            target.write_text(
                '<!doctype html><html><body><h2 id="details">Details</h2></body></html>',
                encoding="utf-8",
            )
            page = root / "index.html"
            page.write_text(
                '<!doctype html><html><body id="top">'
                '<a href="#top">Top</a>'
                '<a href="target.html#details">Relative</a>'
                '<a href="https://xintechllc.com/XTimers/target.html#details">'
                "Absolute product</a>"
                '<a href="https://xintechllc.com/FlexibleTimers/target.html#details">'
                "Absolute legal</a></body></html>",
                encoding="utf-8",
            )
            checker.validate_internal_references(
                root, page, checker.parsed_page(page)
            )
            page.write_text(
                '<!doctype html><html><body><a href="target.html#missing">'
                "Broken</a></body></html>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "Broken internal fragment"):
                checker.validate_internal_references(
                    root, page, checker.parsed_page(page)
                )

    def test_internal_directory_links_resolve_once_and_http_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ar").mkdir()
            (root / "ar" / "index.html").write_text(
                '<!doctype html><html><body id="top"></body></html>',
                encoding="utf-8",
            )
            (root / "nested").mkdir()
            page = root / "nested" / "index.html"
            page.write_text(
                '<!doctype html><html><body>'
                '<a href="../ar/">Arabic</a>'
                '<a href="https://xintechllc.com/XTimers/ar/">Absolute</a>'
                '</body></html>',
                encoding="utf-8",
            )
            checker.validate_internal_references(
                root, page, checker.parsed_page(page)
            )
            self.assertEqual(
                checker.internal_reference_target(root, page, "../ar/")[0],
                (root / "ar" / "index.html").resolve(),
            )
            self.assertEqual(
                checker.internal_reference_target(root, root / "index.html", "ar/")[0],
                (root / "ar" / "index.html").resolve(),
            )
            with self.assertRaisesRegex(RuntimeError, "Insecure internal"):
                checker.internal_reference_target(
                    root, page, "http://xintechllc.com/XTimers/ar/"
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

    def test_product_root_is_the_only_english_canonical(self) -> None:
        alias = ROOT / "flexible-timers.html"
        self.assertEqual(
            navigation.canonical_href(alias, "en", False, "index.html", True),
            "https://xintechllc.com/XTimers/",
        )
        alternates = navigation.alternates(self.inventory, "", "index.html", True)
        self.assertIn(
            'hreflang="en" href="https://xintechllc.com/XTimers/"', alternates
        )
        self.assertIn(
            'hreflang="x-default" href="https://xintechllc.com/XTimers/"', alternates
        )
        self.assertNotIn(
            'href="https://xintechllc.com/XTimers/flexible-timers.html"', alternates
        )
        self.assertEqual(
            (ROOT / "index.html").read_text(encoding="utf-8"),
            alias.read_text(encoding="utf-8"),
            "The legacy alias is an exact canonicalized copy, not a divergent product page",
        )

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

    def test_social_title_and_description_metadata_are_localized(self) -> None:
        source = """<!doctype html><html><head>
        <meta name="description" content="Product description">
        <meta property="og:title" content="Product title">
        <meta property="og:description" content="Social description">
        <meta name="twitter:title" content="Twitter title">
        <meta name="twitter:description" content="Twitter description">
        </head><body><main><h1>Hello</h1></main></body></html>"""
        localized = """<!doctype html><html><head>
        <meta name="description" content="Description du produit">
        <meta property="og:title" content="Titre du produit">
        <meta property="og:description" content="Description sociale">
        <meta name="twitter:title" content="Titre Twitter">
        <meta name="twitter:description" content="Description Twitter">
        </head><body><main><h1>Bonjour</h1></main></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            localized_path = Path(directory) / "index.html"
            localized_path.write_text(localized, encoding="utf-8")
            values = authoring.imported_page_values(source, localized_path)
        self.assertEqual(values["Product title"], "Titre du produit")
        self.assertEqual(values["Social description"], "Description sociale")
        self.assertEqual(values["Twitter title"], "Titre Twitter")
        self.assertEqual(values["Twitter description"], "Description Twitter")

        soup = authoring.BeautifulSoup(source, "html.parser")
        authoring.replace_copy(soup, values)
        self.assertEqual(
            soup.find("meta", attrs={"name": "twitter:title"})["content"],
            "Titre Twitter",
        )
        self.assertEqual(
            soup.find("meta", attrs={"name": "twitter:description"})["content"],
            "Description Twitter",
        )

    def test_legacy_import_scope_stays_separate_from_expanded_generation(self) -> None:
        self.assertEqual(
            authoring.LEGACY_IMPORT_PAGES,
            (
                "index.html",
                "support.html",
                "privacy.html",
                "sms-terms.html",
                "sms-opt-in.html",
            ),
        )
        self.assertTrue(set(authoring.LEGACY_IMPORT_PAGES) < set(authoring.SOURCE_PAGES))
        for page in ("terms.html", "privacy-choices.html", "extension-privacy.html"):
            self.assertNotIn(page, authoring.LEGACY_IMPORT_PAGES)

    def test_localized_drafts_keep_local_pages_and_rebase_root_references(self) -> None:
        source = """<body>
        <a href="support.html">Support</a>
        <a href="terms.html">Terms</a>
        <a href="privacy-choices.html?source=footer#choices">Choices</a>
        <img src="assets/icon.png">
        <source srcset="assets/small.webp 320w, assets/large.webp 640w">
        <a href="https://example.com/">External</a>
        </body>"""
        soup = authoring.BeautifulSoup(source, "html.parser")
        authoring.adjust_relative_references(soup)
        self.assertEqual(soup.find(string="Support").parent["href"], "support.html")
        self.assertEqual(soup.find(string="Terms").parent["href"], "terms.html")
        self.assertEqual(
            soup.find(string="Choices").parent["href"],
            "privacy-choices.html?source=footer#choices",
        )
        self.assertEqual(soup.find("img")["src"], "../assets/icon.png")
        self.assertEqual(
            soup.find("source")["srcset"],
            "../assets/small.webp 320w, ../assets/large.webp 640w",
        )
        self.assertEqual(
            soup.find(string="External").parent["href"], "https://example.com/"
        )

    def test_share_metadata_uses_local_copy_and_canonical_locale_url(self) -> None:
        soup = authoring.BeautifulSoup(
            '<html><head><link rel="canonical" href="https://xintechllc.com/XTimers/">'
            '<meta property="og:url" content="https://xintechllc.com/XTimers/">'
            '<meta property="og:image:alt" content="Preview image">'
            '<meta name="twitter:image:alt" content="Preview image">'
            '</head></html>', 'html.parser',
        )
        authoring.replace_copy(soup, {"Preview image": "Image d’aperçu"})
        authoring.set_canonical(soup, "fr", "index.html")
        self.assertEqual(
            soup.find("meta", property="og:url")["content"],
            "https://xintechllc.com/XTimers/fr/",
        )
        for attribute, name in [("property", "og:image:alt"), ("name", "twitter:image:alt")]:
            self.assertEqual(soup.find("meta", attrs={attribute: name})["content"], "Image d’aperçu")

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

    def test_source_extraction_never_creates_a_doctype_html_key(self) -> None:
        document = "<!doctype html><html><body><p>Hello</p></body></html>"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for page in authoring.SOURCE_PAGES:
                (root / page).write_text(document, encoding="utf-8")
            values = authoring.extracted_values(root)
        self.assertIn("Hello", values)
        self.assertNotIn("html", values)

    def test_source_catalog_must_match_current_english_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for page in authoring.SOURCE_PAGES:
                (root / page).write_text(
                    "<!doctype html><html><body><p>Hello</p></body></html>",
                    encoding="utf-8",
                )
            extracted = authoring.extracted_values(root)
            source = {value: value for value in extracted}
            serialized = authoring.strings_document(extracted)
            checker.validate_source_extraction(
                source, extracted, serialized, serialized
            )
            (root / "privacy.html").write_text(
                "<!doctype html><html><body><p>Changed English policy</p></body></html>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                RuntimeError, "does not exactly match current English pages"
            ):
                checker.validate_source_extraction(
                    source,
                    authoring.extracted_values(root),
                    serialized,
                    serialized,
                )

    def test_inline_blocks_translate_as_complete_placeholder_safe_units(self) -> None:
        soup = authoring.BeautifulSoup(
            '<p>For <a href="support.html">Support</a>, use '
            '<code>127.0.0.1</code> on '
            '<time datetime="2026-08-23">August 23, 2026</time>.</p>',
            "html.parser",
        )
        block = authoring.inline_translation_blocks(soup)[0]
        template, placeholders = authoring.inline_translation_template(block)
        self.assertEqual(
            template,
            "For %1$@Support%2$@, use %3$@ on %4$@August 23, 2026%5$@.",
        )
        restored = authoring.restored_inline_translation(
            "Le %4$@23 août 2026%5$@, utilisez %3$@ via "
            "%1$@l’assistance%2$@ & restez <prudent>.",
            placeholders,
        )
        rendered = str(restored)
        self.assertIn('<a href="support.html">l’assistance</a>', rendered)
        self.assertIn('<code>127.0.0.1</code>', rendered)
        self.assertIn('<time datetime="2026-08-23">23 août 2026</time>', rendered)
        self.assertIn("&amp; restez &lt;prudent&gt;", rendered)

        with self.assertRaisesRegex(RuntimeError, "emptied <a> content"):
            authoring.restored_inline_translation(
                "%1$@%2$@ Assistance, utilisez %3$@ le "
                "%4$@23 août 2026%5$@.",
                placeholders,
            )
        with self.assertRaisesRegex(RuntimeError, "emptied <time> content"):
            authoring.restored_inline_translation(
                "%1$@Assistance%2$@, utilisez %3$@ le %4$@%5$@.",
                placeholders,
            )
        with self.assertRaisesRegex(RuntimeError, "placeholder signature"):
            authoring.restored_inline_translation(
                "%1$@Assistance, utilisez %3$@ le %4$@23 août%5$@.",
                placeholders,
            )

        siblings = authoring.BeautifulSoup(
            '<p><a href="support.html">Support</a> and <strong>privacy</strong>.</p>',
            "html.parser",
        )
        sibling_block = authoring.inline_translation_blocks(siblings)[0]
        _, sibling_placeholders = authoring.inline_translation_template(sibling_block)
        with self.assertRaisesRegex(RuntimeError, "changed tag containment"):
            authoring.restored_inline_translation(
                "%1$@Assistance and %3$@confidentialité%4$@%2$@.",
                sibling_placeholders,
            )

        anchors = authoring.BeautifulSoup(
            '<p><a href="terms.html">Terms</a> and '
            '<a href="privacy.html">Privacy</a>.</p>',
            "html.parser",
        )
        anchor_block = authoring.inline_translation_blocks(anchors)[0]
        _, anchor_placeholders = authoring.inline_translation_template(anchor_block)
        with self.assertRaisesRegex(RuntimeError, "changed tag containment|nested an anchor"):
            authoring.restored_inline_translation(
                "%1$@Conditions and %3$@confidentialité%4$@%2$@.",
                anchor_placeholders,
            )

    def test_inline_block_extraction_fails_closed_on_unknown_markup(self) -> None:
        soup = authoring.BeautifulSoup(
            "<p>Review the <mark>important policy</mark> now.</p>", "html.parser"
        )
        with self.assertRaisesRegex(RuntimeError, "Unsupported inline translation tags"):
            authoring.inline_translation_blocks(soup)

    def test_landing_icons_and_footer_markup_survive_localization(self) -> None:
        soup = authoring.BeautifulSoup(
            '<li><a href="#timers"><img src="assets/icon.png" alt=""/>'
            '<span>Timers</span></a></li>'
            '<p><svg aria-hidden="true"><use href="#check"/></svg>Offline</p>'
            '<p><small>Copyright</small><span>Your time</span></p>',
            "html.parser",
        )
        translations = {
            "%1$@%2$@%3$@Timers%4$@%5$@": "%1$@%2$@%3$@Minuteurs%4$@%5$@",
            "%1$@Offline": "%1$@Hors ligne",
            "%1$@Copyright%2$@%3$@Your time%4$@": "%1$@Droits d’auteur%2$@%3$@Votre temps%4$@",
        }
        authoring.replace_copy(soup, translations)
        self.assertEqual(soup.select_one("li span").text, "Minuteurs")
        self.assertEqual(soup.select_one("img")["src"], "assets/icon.png")
        self.assertEqual(soup.select_one("svg use")["href"], "#check")
        self.assertIn("Hors ligne", soup.text)
        self.assertEqual(soup.select_one("small").text, "Droits d’auteur")

    def test_screenshot_and_navigation_runtime_labels_are_localized(self) -> None:
        soup = authoring.BeautifulSoup(
            '<button data-caption="Your timer" data-zoom="assets/timer.png" '
            'data-open-label="Open navigation" data-close-label="Close navigation" '
            'aria-label="Your timer"></button>', "html.parser",
        )
        authoring.replace_copy(soup, {
            "Your timer": "Votre minuteur",
            "Open navigation": "Ouvrir le menu",
            "Close navigation": "Fermer le menu",
        })
        authoring.adjust_relative_references(soup)
        button = soup.button
        self.assertEqual(button["data-caption"], "Votre minuteur")
        self.assertEqual(button["data-open-label"], "Ouvrir le menu")
        self.assertEqual(button["data-close-label"], "Fermer le menu")
        self.assertEqual(button["data-zoom"], "../assets/timer.png")

    def test_owner_support_links_follow_the_localized_support_route(self) -> None:
        extension_policy = (ROOT / "extension-privacy.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'href="https://xintechllc.com/XTimers/support.html"', extension_policy
        )
        document = (
            '<a href="https://xintechllc.com/XTimers/support.html">'
            "xintechllc.com/XTimers/support.html</a>"
            '<a href="https://xintechllc.com/XTimers/support.html">legacy</a>'
            '<a href="https://xintechllc.com/FlexibleTimers/sms-terms.html">SMS</a>'
        )
        localized = authoring.localize_owner_support_urls(document, "fr")
        self.assertEqual(localized.count("xintechllc.com/XTimers/fr/support.html"), 3)
        self.assertIn("xintechllc.com/FlexibleTimers/sms-terms.html", localized)

    def test_policy_prose_does_not_split_sentences_with_inline_emphasis(self) -> None:
        for page in checker.POLICY_PAGES:
            with self.subTest(page=page):
                soup = authoring.BeautifulSoup(
                    (ROOT / page).read_text(encoding="utf-8"), "html.parser"
                )
                self.assertEqual(soup.select("p strong, li strong"), [])

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

    def test_website_checker_requires_target_script_for_substantive_prose(self) -> None:
        source = (
            "A device target is a request and does not prove that an alarm was "
            "scheduled or canceled successfully."
        )
        with self.assertRaisesRegex(
            RuntimeError, "insufficient target-script coverage for kn"
        ):
            checker.validate_translation_values(
                {source: source},
                {
                    source: (
                        "Device target request does not prove alarm delivery "
                        "ಕನ್ನಡ"
                    )
                },
                "kn",
            )
        checker.validate_translation_values(
            {source: source},
            {
                source: (
                    "ಸಾಧನದ ಗುರಿ ಒಂದು ವಿನಂತಿಯಾಗಿದೆ; ಅಲಾರಂ ಯಶಸ್ವಿಯಾಗಿ ನಿಗದಿಯಾಗಿದೆ "
                    "ಅಥವಾ ರದ್ದಾಗಿದೆ ಎಂಬುದಕ್ಕೆ ಇದು ಸಾಕ್ಷಿಯಲ್ಲ."
                )
            },
            "kn",
        )

    def test_target_script_coverage_excludes_protected_urls_and_tokens(self) -> None:
        source = "For support, see %1$@xintechllc.com/XTimers/support.html%2$@."
        checker.validate_translation_values(
            {source: source},
            {source: "如需支持，请参阅 %1$@xintechllc.com/XTimers/support.html%2$@。"},
            "zh-Hans",
        )

    def test_hindi_bounded_row_has_a_reviewed_translation(self) -> None:
        source = (
            "A Xin Account can authorize access to XTimers and other connected products\n"
            "      listed in the account controls."
        )
        expected = (
            "एक Xin Account, XTimers और खाता नियंत्रण में सूचीबद्ध अन्य कनेक्टेड "
            "उत्पादों तक पहुँच को अधिकृत कर सकता है।"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["hi"][source], expected
        )
        checker.validate_translation_values({source: source}, {source: expected}, "hi")
        deletion_source = (
            "Deleting only XTimers data leaves the Xin Account and other connected\n"
            "      products available."
        )
        deletion_expected = (
            "केवल XTimers डेटा हटाने पर Xin Account और अन्य कनेक्टेड उत्पाद उपलब्ध "
            "रहते हैं।"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["hi"][deletion_source],
            deletion_expected,
        )
        checker.validate_translation_values(
            {deletion_source: deletion_source},
            {deletion_source: deletion_expected},
            "hi",
        )
        marketing_source = (
            "XTimers does not send marketing SMS and does not allow SMS to arbitrary "
            "third-party recipients."
        )
        marketing_expected = (
            "XTimers मार्केटिंग SMS नहीं भेजता और मनमाने तृतीय-पक्ष प्राप्तकर्ताओं "
            "को SMS भेजने की अनुमति नहीं देता।"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["hi"][marketing_source],
            marketing_expected,
        )
        checker.validate_translation_values(
            {marketing_source: marketing_source},
            {marketing_source: marketing_expected},
            "hi",
        )
        for reviewed_source in (
            "SMS is not a two-way chat\n      service.",
            "After a signed-in user gives explicit consent, XTimers may attempt to "
            "send a setup verification code to the user-entered proposed account "
            "phone number.",
            "User-created reminder SMS may be attempted only after successful "
            "verification and opt-in, and only to that same phone number.",
            "SMS use is also governed by the %1$@SMS Terms%2$@ and "
            "%3$@Privacy Policy%4$@.",
        ):
            reviewed_value = authoring.REVIEWED_TRANSLATION_CORRECTIONS["hi"][
                reviewed_source
            ]
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "hi",
            )
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["hi"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "hi",
            )

    def test_urdu_bounded_row_has_a_reviewed_translation(self) -> None:
        source = (
            "After you send STOP,\n"
            "      XTimers will stop sending SMS messages to that phone number\n"
            "      unless you opt in again."
        )
        expected = (
            "آپ کے STOP بھیجنے کے بعد، XTimers اس فون نمبر پر SMS پیغامات بھیجنا "
            "بند کر دے گا، جب تک کہ آپ دوبارہ آپٹ اِن نہ کریں۔"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][source], expected
        )
        checker.validate_translation_values({source: source}, {source: expected}, "ur")
        carrier_source = (
            "Carrier and\n"
            "      provider handling may vary; XTimers does not promise a particular\n"
            "      automated response message for any keyword."
        )
        carrier_expected = (
            "کیریئر اور فراہم کنندہ کا طریقۂ کار مختلف ہو سکتا ہے؛ XTimers کسی بھی "
            "کلیدی لفظ کے لیے کسی مخصوص خودکار جوابی پیغام کا وعدہ نہیں کرتا۔"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][carrier_source],
            carrier_expected,
        )
        checker.validate_translation_values(
            {carrier_source: carrier_source},
            {carrier_source: carrier_expected},
            "ur",
        )
        sign_out_source = (
            "Signing out preserves local timers and other local data;\n"
            "      XTimers does not currently provide a separate whole-app local-data reset\n"
            "      on Mac, iPhone, or iPad."
        )
        sign_out_expected = (
            "سائن آؤٹ کرنے سے مقامی ٹائمرز اور دیگر مقامی ڈیٹا برقرار رہتے ہیں؛ "
            "XTimers فی الحال Mac، iPhone یا iPad پر پوری ایپ کے مقامی ڈیٹا کو الگ "
            "سے ری سیٹ کرنے کا اختیار فراہم نہیں کرتا۔"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][sign_out_source],
            sign_out_expected,
        )
        checker.validate_translation_values(
            {sign_out_source: sign_out_source},
            {sign_out_source: sign_out_expected},
            "ur",
        )
        workspace_source = (
            "Bring timers, countdowns and world clocks into one workspace. Add "
            "reusable routines, reminders and reports, with layouts and appearance "
            "you can make your own."
        )
        workspace_expected = (
            "ٹائمر، کاؤنٹ ڈاؤن اور عالمی گھڑیاں ایک ہی ورک اسپیس میں جمع کریں۔ "
            "دوبارہ استعمال ہونے والے معمولات، یاددہانیاں اور رپورٹیں شامل کریں، "
            "اور ترتیب و ظاہری شکل کو اپنی پسند کا بنائیں۔"
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][workspace_source],
            workspace_expected,
        )
        checker.validate_translation_values(
            {workspace_source: workspace_source},
            {workspace_source: workspace_expected},
            "ur",
        )
        active_tab_source = (
            "The active-tab report is delivered only to the XTimers Pro app running on "
            "your own computer — either through the app's local native-messaging host or "
            "a loopback (%1$@) connection to the app on the same machine."
        )
        active_tab_expected = authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][
            active_tab_source
        ]
        checker.validate_translation_values(
            {active_tab_source: active_tab_source},
            {active_tab_source: active_tab_expected},
            "ur",
        )
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "ur",
            )

    def test_malayalam_bounded_rows_have_reviewed_translations(self) -> None:
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ml"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "ml",
            )

    def test_marathi_bounded_rows_have_reviewed_translations(self) -> None:
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["mr"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "mr",
            )

    def test_odia_bounded_rows_have_reviewed_translations(self) -> None:
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["or"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "or",
            )

    def test_tamil_bounded_rows_have_reviewed_translations(self) -> None:
        for reviewed_source, reviewed_value in (
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ta"].items()
        ):
            checker.validate_translation_values(
                {reviewed_source: reviewed_source},
                {reviewed_source: reviewed_value},
                "ta",
            )

    def test_reviewed_semantic_corrections_are_exact_and_gate_catalogs(self) -> None:
        expected = {
            "es": "%1$@Aprenda cómo funcionan las capas de la cuenta.%2$@",
            "fr": "%1$@Découvrez comment fonctionnent les couches du compte.%2$@",
            "hr": "%1$@Saznajte kako funkcioniraju slojevi računa.%2$@",
            "ru": "%1$@Узнайте, как работают уровни учётной записи.%2$@",
        }
        source_fragment = "%1$@Learn how the account layers work.%2$@"
        for identifier, value in expected.items():
            self.assertEqual(
                authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][source_fragment],
                value,
            )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["cs"]["No Emergency Use"],
            "Nepoužívat v nouzových situacích",
        )
        shared_identity_source = (
            "The Xin Account, shared sign-in identity, and any other connected "
            "products remain available."
        )
        shared_identity_expected = {
            "cs": "Účet Xin Account, sdílená přihlašovací identita a všechny ostatní propojené produkty zůstávají k dispozici.",
            "nb": "Xin Account, den delte påloggingsidentiteten og alle andre tilknyttede produkter forblir tilgjengelige.",
            "sv": "Xin Account, den delade inloggningsidentiteten och alla andra anslutna produkter förblir tillgängliga.",
        }
        for identifier, value in shared_identity_expected.items():
            self.assertEqual(
                authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][
                    shared_identity_source
                ],
                value,
            )
        french_sms_source = (
            "After successful verification\n"
            "      and opt-in, XTimers may attempt user-created timer/reminder SMS only to\n"
            "      that same phone number and only when the user schedules them for\n"
            "      themselves."
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["fr"][french_sms_source],
            "Après une vérification réussie et l’adhésion, XTimers peut tenter "
            "d’envoyer des SMS de minuteur ou de rappel créés par l’utilisateur "
            "uniquement à ce même numéro de téléphone et uniquement lorsque "
            "l’utilisateur les programme pour lui-même.",
        )

        source = {f"Before {source_fragment} After": "English"}
        translations = {"fr": {next(iter(source)): expected["fr"]}}
        corrections = {"fr": {source_fragment: expected["fr"]}}
        checker.validate_reviewed_translation_corrections(
            source, translations, corrections
        )
        translations["fr"][next(iter(source))] = "Traduction incorrecte"
        with self.assertRaisesRegex(RuntimeError, "correction is missing for fr"):
            checker.validate_reviewed_translation_corrections(
                source, translations, corrections
            )

    def test_full_value_reviewed_overlay_rejects_appended_garbage(self) -> None:
        source_key = "Complete reviewed legal sentence."
        expected = "Phrase juridique complète révisée."
        source = {source_key: source_key}
        corrections = {"fr": {source_key: expected}}
        checker.validate_reviewed_translation_corrections(
            source, {"fr": {source_key: expected}}, corrections
        )
        with self.assertRaisesRegex(RuntimeError, "correction is missing for fr"):
            checker.validate_reviewed_translation_corrections(
                source,
                {"fr": {source_key: expected + " Texte parasite."}},
                corrections,
            )

    def test_retired_review_fragments_preserve_current_correction_checks(self) -> None:
        current_key = "Current policy sentence."
        retired_key = "Retired landing sentence."
        expected = "Phrase actuelle révisée."
        source = {current_key: current_key}
        historical = {
            retired_key: "Ancienne phrase révisée.",
            current_key: expected,
        }
        corrections = {"test": dict(historical)}
        defective = {current_key: "Traduction incorrecte"}
        with mock.patch.dict(authoring.REVIEWED_TRANSLATION_CORRECTIONS, corrections):
            corrected, count = authoring.reviewed_correction_values(
                source, defective, "test"
            )
            replayed, replay_count = authoring.reviewed_correction_values(
                source, corrected, "test"
            )
        self.assertEqual(corrected, {current_key: expected})
        self.assertEqual(count, 1)
        self.assertEqual((replayed, replay_count), (corrected, 0))
        self.assertEqual(corrections["test"], historical)
        checker.validate_reviewed_translation_corrections(
            source, {"test": corrected}, corrections
        )
        with self.assertRaisesRegex(RuntimeError, "correction is missing for test"):
            checker.validate_reviewed_translation_corrections(
                source, {"test": defective}, corrections
            )

    def test_exact_overlay_supersedes_an_older_fragment_repair(self) -> None:
        source_key = "Complete source sentence with an old fragment."
        exact_value = "Phrase complète nouvellement révisée."
        checker.validate_reviewed_translation_corrections(
            {source_key: source_key},
            {"fr": {source_key: exact_value}},
            {"fr": {"old fragment": "ancien fragment"}},
            {"fr": {source_key: exact_value}},
        )
        with self.assertRaisesRegex(RuntimeError, "correction is missing for fr"):
            checker.validate_reviewed_translation_corrections(
                {source_key: source_key},
                {"fr": {source_key: exact_value + " Texte parasite."}},
                {"fr": {source_key: exact_value}},
                {"fr": {source_key: exact_value}},
            )

    def test_eastern_semantic_corrections_are_exact_and_idempotent(self) -> None:
        account_source = "A Xin\n      Account is the shared identity layer"
        for identifier, expected in {
            "ar": "يُعد Xin Account",
            "he": "Xin Account הוא",
            "ja": "Xin Account は",
            "ko": "Xin Account는",
            "th": "Xin Account คือ",
            "vi": "Xin Account là",
            "zh-Hans": "Xin Account 是",
            "zh-Hant": "Xin Account 是",
        }.items():
            self.assertEqual(
                authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][account_source],
                expected,
            )

        consent_source = (
            "I agree to receive SMS verification codes and reminder messages"
        )
        for identifier, expected in {
            "ja": "私は、この電話番号で、Xintech LLC が提供する XTimers から SMS 確認コードと、自分自身のために予定したリマインダーメッセージを受け取ることに同意します。",
            "ko": "저는 이 전화번호로 Xintech LLC가 제공하는 XTimers의 SMS 인증 코드와 제가 직접 예약한 알림 메시지를 받는 데 동의합니다.",
            "zh-Hans": "我同意在此电话号码接收由 Xintech LLC 运营的 XTimers 所发送的 SMS 验证码，以及我为自己安排的提醒消息。",
            "zh-Hant": "我同意在此電話號碼接收由 Xintech LLC 營運的 XTimers 所發送的 SMS 驗證碼，以及我為自己排定的提醒訊息。",
        }.items():
            self.assertEqual(
                authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][consent_source],
                expected,
            )

        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["he"][
                "as explained in the %2$@main Privacy Policy%3$@."
            ],
            "כפי שמוסבר ב-%2$@מדיניות הפרטיות הראשית%3$@.",
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ar"]["push-registration data"],
            "بيانات التسجيل للإشعارات الفورية",
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ar"][
                "Your Xin Account identifies you and authorizes each connected XTimers account."
            ],
            "يحدد Xin Account هويتك ويخوّل كل حساب XTimers متصل.",
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ko"][
                "Last updated: %1$@August 23, 2026%2$@."
            ],
            "최종 업데이트: %1$@2026년 8월 23일%2$@.",
        )
        self.assertIn(
            "پش نوٹیفکیشن رجسٹریشن ڈیٹا۔",
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][
                "This removes\n"
                "      that account's data from the XTimers service, including active timers,\n"
                "      alarms, session and task history, device-targeting and scheduling-status\n"
                "      records, snapshots, sounds, Background Library content, feedback,\n"
                "      reminders, messages, published reports and report links, SMS configuration,\n"
                "      and push-registration data."
            ],
        )
        self.assertEqual(
            authoring.REVIEWED_TRANSLATION_CORRECTIONS["ur"][
                "The Xin Account, shared sign-in identity, and any other connected product\n"
                "      accounts remain available."
            ],
            "Xin Account، مشترکہ سائن اِن شناخت، اور کسی بھی دیگر منسلک مصنوعات کے "
            "اکاؤنٹس دستیاب رہتے ہیں۔",
        )

        source = authoring.extracted_values(ROOT)
        for identifier in authoring.REVIEWED_TRANSLATION_CORRECTIONS:
            catalog = authoring.load_strings(
                ROOT
                / "generated"
                / "WebsiteTranslations"
                / f"{identifier}.lproj"
                / "Website.strings"
            )
            corrected, count = authoring.reviewed_correction_values(
                source, catalog, identifier
            )
            self.assertEqual(count, 0, identifier)
            self.assertEqual(corrected, catalog, identifier)

        umami_target = authoring.REVIEWED_TRANSLATION_CORRECTIONS["zh-Hans"][
            next(
                key
                for key in authoring.REVIEWED_TRANSLATION_CORRECTIONS["zh-Hans"]
                if key.startswith("This website uses Umami Cloud")
            )
        ]
        self.assertNotIn("\\n \\n", umami_target)

    def test_known_catalog_corruption_cannot_recur(self) -> None:
        catalogs = {
            identifier: authoring.load_strings(
                ROOT
                / "generated"
                / "WebsiteTranslations"
                / f"{identifier}.lproj"
                / "Website.strings"
            )
            for identifier in ("gu", "id", "it", "ko", "nl", "ru", "sl", "sv")
        }
        safety = next(
            key
            for key in catalogs["id"]
            if key.startswith("A signed-in alarm may have one shared definition")
        )
        for term in (
            "Pending Apply",
            "Pending Cancellation",
            "Needs Permission",
            "Unavailable",
            "Failed",
            "Sync Pending",
        ):
            self.assertNotIn(term, catalogs["id"][safety])
            self.assertIn(catalogs["id"][term], catalogs["id"][safety])

        russian_sms = next(
            key
            for key in catalogs["ru"]
            if key.startswith("After a signed-in user gives explicit consent, XTimers may")
        )
        self.assertNotIn("%3$@%4$@", catalogs["ru"][russian_sms])
        self.assertIn("%3$@Политикой конфиденциальности%4$@", catalogs["ru"][russian_sms])

        live_opt_in = next(
            key
            for key in catalogs["nl"]
            if key.startswith("The live opt-in screen shows")
        )
        self.assertNotIn("SMS Terms and Privacy Policy links", catalogs["nl"][live_opt_in])
        swedish_terms = next(
            key
            for key in catalogs["sv"]
            if key.startswith("These terms govern the XTimers services")
        )
        self.assertNotIn(
            "Standard Licensed Application End User License Agreement",
            catalogs["sv"][swedish_terms],
        )
        self.assertEqual(
            catalogs["ko"]["Last updated: August 23, 2026."],
            "최종 업데이트: 2026년 8월 23일.",
        )
        for identifier in ("it", "nl", "sl"):
            date = catalogs[identifier]["Last updated: August 23, 2026."]
            self.assertFalse(date.lstrip().startswith("."), identifier)
        gu_deletion = next(
            key
            for key in catalogs["gu"]
            if key.startswith("In XTimers account controls, choose Delete XTimers Data")
        )
        self.assertNotIn("ઇમેઇલ કરો", catalogs["gu"][gu_deletion])

    def test_telugu_semantic_corrections_are_exact(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(authoring.REVIEWED_TELUGU_OVERLAY_PATH.read_bytes()).hexdigest(),
            authoring.REVIEWED_TELUGU_OVERLAY_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_TELUGU_ALARM_TERMS_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_TELUGU_ALARM_TERMS_SHA256,
        )
        website_overlay = json.loads(
            authoring.REVIEWED_TELUGU_OVERLAY_PATH.read_text(encoding="utf-8")
        )
        alarm_overlay = json.loads(
            authoring.REVIEWED_TELUGU_ALARM_TERMS_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(website_overlay), {"te"})
        self.assertEqual(len(website_overlay["te"]), 47)
        self.assertEqual(set(alarm_overlay), {"te"})
        self.assertEqual(len(alarm_overlay["te"]), 5)
        source = authoring.load_strings(ROOT / "generated" / "WebsiteSource.strings")
        catalog = authoring.load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / "te.lproj"
            / "Website.strings"
        )
        direct = json.loads(
            (ROOT / "generated" / "DirectGPTWebsiteTranslations" / "te.json").read_text(
                encoding="utf-8"
            )
        )["translations"]
        for key in website_overlay["te"].keys() & source.keys():
            self.assertEqual(catalog[key], direct[key])
        for term in alarm_overlay["te"]:
            self.assertEqual(catalog[term], direct[term])
        corrected, count = authoring.reviewed_correction_values(source, catalog, "te")
        self.assertEqual(count, 0)
        self.assertEqual(corrected, catalog)
        checker.validate_translation_values(source, catalog, "te")
        checker.validate_alarm_ui_terminology(source, catalog, "te")

    def test_punjabi_semantic_corrections_are_exact(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(
                authoring.REVIEWED_PUNJABI_OVERLAY_PATH.read_bytes()
            ).hexdigest(),
            authoring.REVIEWED_PUNJABI_OVERLAY_SHA256,
        )
        document = json.loads(
            authoring.REVIEWED_PUNJABI_OVERLAY_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(document), {"_app_glossary", "pa"})
        self.assertEqual(len(document["pa"]), 62)
        self.assertEqual(len(document["_app_glossary"]["pa"]), 3)
        source = authoring.load_strings(ROOT / "generated" / "WebsiteSource.strings")
        catalog = authoring.load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / "pa.lproj"
            / "Website.strings"
        )
        direct = json.loads(
            (ROOT / "generated" / "DirectGPTWebsiteTranslations" / "pa.json").read_text(
                encoding="utf-8"
            )
        )["translations"]
        for key in document["pa"].keys() & source.keys():
            self.assertEqual(catalog[key], direct[key])
        for term in document["_app_glossary"]["pa"]:
            self.assertEqual(catalog[term], direct[term])
        self.assertIn("ਪਿਛੋਕੜ ਲਾਇਬ੍ਰੇਰੀ", " ".join(document["pa"].values()))
        self.assertNotIn(
            authoring.ALARM_TERM_FALLBACK_MARKER, "".join(catalog.values())
        )
        checker.validate_alarm_ui_terminology(source, catalog, "pa")
        replayed, replay_count = authoring.reviewed_correction_values(
            source, catalog, "pa"
        )
        self.assertEqual(replay_count, 0)
        self.assertEqual(replayed, catalog)

    def test_bengali_semantic_corrections_are_exact(self) -> None:
        import hashlib

        self.assertEqual(
            hashlib.sha256(authoring.REVIEWED_BENGALI_OVERLAY_PATH.read_bytes()).hexdigest(),
            authoring.REVIEWED_BENGALI_OVERLAY_SHA256,
        )
        overlay = json.loads(
            authoring.REVIEWED_BENGALI_OVERLAY_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(overlay), {"bn"})
        self.assertEqual(len(overlay["bn"]), 53)
        source = authoring.load_strings(ROOT / "generated" / "WebsiteSource.strings")
        catalog = authoring.load_strings(
            ROOT
            / "generated"
            / "WebsiteTranslations"
            / "bn.lproj"
            / "Website.strings"
        )
        for key in overlay["bn"].keys() & source.keys():
            self.assertEqual(
                catalog[key],
                authoring.REVIEWED_TRANSLATION_CORRECTIONS["bn"][key],
            )
        corrected, count = authoring.reviewed_correction_values(source, catalog, "bn")
        self.assertEqual(count, 0)
        self.assertEqual(corrected, catalog)
        checker.validate_translation_values(source, catalog, "bn")
        checker.validate_alarm_ui_terminology(source, catalog, "bn")

    def test_gujarati_semantic_corrections_are_exact(self) -> None:
        values = set(authoring.REVIEWED_TRANSLATION_CORRECTIONS["gu"].values())
        self.assertTrue(
            {
                "આ શરતો Xintech LLC દ્વારા સંચાલિત XTimers સેવાઓને નિયંત્રિત કરે છે.",
                "સાઇન ઇન કરેલા વપરાશકર્તા સ્પષ્ટ સંમતિ આપે પછી, Xintech LLC દ્વારા સંચાલિત XTimers વપરાશકર્તાએ દાખલ કરેલા પ્રસ્તાવિત ખાતા ફોન નંબર પર સેટઅપ ચકાસણી કોડ મોકલવાનો પ્રયાસ કરી શકે છે.",
                "SMS સંદેશાઓમાંથી ઓપ્ટ આઉટ થવા માટે STOP લખીને જવાબ આપો.",
                "મદદ માટે HELP લખીને જવાબ આપો.",
                "એપમાં સંમતિ આપ્યા પછી START અથવા YES લખીને જવાબ આપી તે નંબરને ફરી ઓપ્ટ ઇન કરી શકાય છે.",
                "SMS દ્વિમાર્ગી ચેટ સેવા નથી.",
                "હું આ ફોન નંબર પર Xintech LLC દ્વારા સંચાલિત XTimers તરફથી SMS ચકાસણી કોડ અને મેં મારા માટે શેડ્યૂલ કરેલા રીમાઇન્ડર સંદેશાઓ મેળવવા માટે સંમત છું.",
                "વપરાશકર્તાઓને દર્શાવવામાં આવતું અંતિમ વ્યવસાય Xintech LLC દ્વારા સંચાલિત XTimers છે.",
                "%1$@ખાતાના સ્તરો કેવી રીતે કાર્ય કરે છે તે જાણો.%2$@",
                "%1$@જાળવણીની વિગતો માટે ગોપનીયતા નીતિ વાંચો.%2$@",
                "%2$@મુખ્ય ગોપનીયતા નીતિ%3$@",
                "%1$@શરતો%2$@, %3$@ગોપનીયતા નીતિ%4$@ અને %5$@SMS શરતો%6$@ જુઓ.",
                "%3$@ગોપનીયતા નીતિ%4$@",
                "%1$@ગોપનીયતા નીતિ%2$@",
                "%3$@ગોપનીયતા પસંદગીઓ%4$@",
                "અમલ તારીખ: %1$@23 ઑગસ્ટ 2026%2$@.",
                "છેલ્લે અપડેટ કર્યું: %1$@23 ઑગસ્ટ 2026%2$@.",
                "Xintech LLC દ્વારા સંચાલિત XTimersના SMS ઓપ્ટ-ઇન સંમતિનો પુરાવો",
                "Xintech LLC દ્વારા સંચાલિત XTimersની ગોપનીયતા નીતિ",
                "Xintech LLC દ્વારા સંચાલિત XTimersની SMS શરતો",
            }.issubset(values)
        )

    def test_checker_rejects_english_equal_and_changed_signatures(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "English-equal values"):
            checker.validate_translation_values(
                {"Delete Xin Account": "Delete Xin Account"},
                {"Delete Xin Account": "Delete Xin Account"},
                "fr",
            )
        checker.validate_translation_values(
            {"XTimers": "XTimers"}, {"XTimers": "XTimers"}, "fr"
        )
        checker.validate_translation_values(
            {"%1$@admin@xintechllc.com%2$@": "%1$@admin@xintechllc.com%2$@"},
            {"%1$@admin@xintechllc.com%2$@": "%1$@admin@xintechllc.com%2$@"},
            "fr",
        )
        checker.validate_translation_values(
            {
                "See %1$@xintechllc.com/XTimers/support.html%2$@.":
                    "See %1$@xintechllc.com/XTimers/support.html%2$@."
            },
            {
                "See %1$@xintechllc.com/XTimers/support.html%2$@.":
                    "Voir %1$@xintechllc.com/XTimers/support.html%2$@."
            },
            "fr",
        )
        checker.validate_translation_values(
            {"Contact": "Contact"}, {"Contact": "Contact"}, "fr"
        )
        checker.validate_translation_values(
            {"Keep Xin\n      Account data.": "Keep Xin\n      Account data."},
            {"Keep Xin\n      Account data.": "Conserver les données Xin Account."},
            "fr",
        )
        checker.validate_translation_values(
            {"See %1$@Privacy%2$@.": "See %1$@Privacy%2$@."},
            {"See %1$@Privacy%2$@.": "%1$@رازداری%2$@ دیکھیں۔"},
            "ur",
        )
        with self.assertRaisesRegex(RuntimeError, "protected-token signature"):
            checker.validate_translation_values(
                {"Keep Xin\n      Account data.": "Keep Xin\n      Account data."},
                {"Keep Xin\n      Account data.": "Conserver les données du compte Xin."},
                "fr",
            )
        for locale, value in (
            ("it", "Privacy"),
            ("nb", "XTimers for Mac"),
            ("nl", "Contact"),
            ("nl", "Privacy"),
            ("ro", "Contact"),
            ("sv", "Support"),
        ):
            checker.validate_translation_values({value: value}, {value: value}, locale)
        with self.assertRaisesRegex(RuntimeError, "English-equal values"):
            checker.validate_translation_values(
                {"Contact": "Contact"}, {"Contact": "Contact"}, "de"
            )
        with self.assertRaisesRegex(RuntimeError, "URL/email signature"):
            checker.validate_translation_values(
                {
                    "Read xintechllc.com/FlexibleTimers/privacy.html":
                        "Read xintechllc.com/FlexibleTimers/privacy.html"
                },
                {
                    "Read xintechllc.com/FlexibleTimers/privacy.html":
                        "Lire xintechllc.com/FlexibleTimers/fr/privacy.html"
                },
                "fr",
            )
        with self.assertRaisesRegex(RuntimeError, "protected-token signature"):
            checker.validate_translation_values(
                {"Reply STOP for XTimers help": "Reply STOP for XTimers help"},
                {"Reply STOP for XTimers help": "Répondez pour l’aide XTimers"},
                "fr",
            )
        with self.assertRaisesRegex(RuntimeError, "protected-token signature"):
            checker.validate_translation_values(
                {"Stored on the Mac.": "Stored on the Mac."},
                {"Stored on the Mac.": "مخزّن على الماك."},
                "ar",
            )
        with self.assertRaisesRegex(RuntimeError, "format-specifier signature"):
            checker.validate_translation_values(
                {"Open %@ at %d": "Open %@ at %d"},
                {"Open %@ at %d": "Ouvrir sans valeur"},
                "fr",
            )
        with self.assertRaisesRegex(RuntimeError, "dropped terminal punctuation"):
            checker.validate_translation_values(
                {"See %1$@Support%2$@.": "See %1$@Support%2$@."},
                {"See %1$@Support%2$@.": "Voir %1$@Assistance%2$@"},
                "fr",
            )

    def test_checker_rejects_protected_latin_token_glue(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "glues protected token"):
            checker.validate_translation_values(
                {"XTimers is operated by Xintech LLC.": "XTimers is operated by Xintech LLC."},
                {"XTimers is operated by Xintech LLC.": "XTimerses operado porXintech LLC."},
                "es",
            )
        checker.validate_translation_values(
            {"XTimers for Mac": "XTimers for Mac"},
            {"XTimers for Mac": "Mac版XTimers"},
            "ja",
        )
        checker.validate_translation_values(
            {"XTimers Pro edition": "XTimers Pro edition"},
            {"XTimers Pro edition": "XTimers Pro版"},
            "ja",
        )
        checker.validate_translation_values(
            {"XTimers works on iPhone": "XTimers works on iPhone"},
            {"XTimers works on iPhone": "XTimersin toiminta iPhonella"},
            "fi",
        )
        checker.validate_translation_values(
            {"XTimers works on iPad": "XTimers works on iPad"},
            {"XTimers works on iPad": "Działanie XTimersa na iPada"},
            "pl",
        )
        checker.validate_translation_values(
            {"XTimers Privacy Policy": "XTimers Privacy Policy"},
            {"XTimers Privacy Policy": "XTimersની ગોપનીયતા નીતિ"},
            "gu",
        )
        checker.validate_translation_values(
            {"Apple license": "Apple license"},
            {"Apple license": "Apples licens"},
            "sv",
        )
        checker.validate_translation_values(
            {"XTimers product support": "XTimers product support"},
            {"XTimers product support": "XTimers Produktsupport"},
            "de",
        )

    def test_alarm_ui_terms_are_synchronized_inside_policy_prose(self) -> None:
        source = {term: term for term in checker.ALARM_UI_TERMS}
        source.update(
            {
                "Use Rings On for This Device and review Scheduled, Needs Permission, or Failed.":
                    "Use Rings On for This Device and review Scheduled, Needs Permission, or Failed."
            }
        )
        translations = {
            "Rings On": "Appareils où l’alarme sonne",
            "This Device": "Cet appareil",
            "Scheduled": "Programmé",
            "Pending Apply": "Application en attente",
            "Pending Cancellation": "Annulation en attente",
            "Needs Permission": "Besoin d’autorisation",
            "Unavailable": "Indisponible",
            "Failed": "Échec.",
            "Sync Pending": "Synchronisation en attente",
            "Use Rings On for This Device and review Scheduled, Needs Permission, or Failed.":
                "Pour Cet appareil, utilisez Sonner sur et vérifiez Programmé, Besoin d’autorisation ou Échec.",
        }
        with self.assertRaisesRegex(
            RuntimeError, "alarm UI term mismatch for fr: 'Rings On'"
        ):
            checker.validate_alarm_ui_terminology(source, translations, "fr")
        translations[
            "Use Rings On for This Device and review Scheduled, Needs Permission, or Failed."
        ] = (
            "Pour Cet appareil, utilisez Appareils où l’alarme sonne et vérifiez "
            "Programmé, Besoin d’autorisation ou Échec."
        )
        checker.validate_alarm_ui_terminology(source, translations, "fr")

    def test_alarm_management_heading_reuses_exact_app_term(self) -> None:
        source = {term: term for term in checker.ALARM_UI_TERMS}
        source[authoring.ALARM_MANAGEMENT_HEADING] = (
            authoring.ALARM_MANAGEMENT_HEADING
        )
        translations = {
            term: f"Localized {term}" for term in checker.ALARM_UI_TERMS
        }
        translations["Rings On"] = "Appareils où l’alarme sonne"
        translations[authoring.ALARM_MANAGEMENT_HEADING] = (
            "Gérer les alarmes et les sonneries"
        )
        with mock.patch.object(
            authoring, "REVIEWED_TRANSLATION_CORRECTIONS", {"ca": {}}
        ), mock.patch.object(authoring, "reviewed_overlay", {}):
            corrected, count = authoring.reviewed_correction_values(
                source, translations, "ca"
            )
        self.assertEqual(count, 1)
        self.assertEqual(
            corrected[authoring.ALARM_MANAGEMENT_HEADING],
            "Appareils où l’alarme sonne",
        )
        checker.validate_alarm_ui_terminology(source, corrected, "fr")

    def test_policy_alarm_statuses_are_reconciled_to_exact_glossary_values(self) -> None:
        paragraph = (
            "Use Rings On for This Device and review Scheduled, Needs Permission, "
            "or Failed."
        )
        source = {term: term for term in checker.ALARM_UI_TERMS}
        source[paragraph] = paragraph
        translations = {
            "Rings On": "Appareils où l’alarme sonne",
            "This Device": "Cet appareil",
            "Scheduled": "Programmé",
            "Pending Apply": "Application en attente",
            "Pending Cancellation": "Annulation en attente",
            "Needs Permission": "Besoin d’autorisation",
            "Unavailable": "Indisponible",
            "Failed": "Échec",
            "Sync Pending": "Synchronisation en attente",
            paragraph: (
                "Utilisez la sonnerie ici et examinez Scheduled, Needs Permission "
                "ou Failed."
            ),
        }
        with mock.patch.object(
            authoring, "REVIEWED_TRANSLATION_CORRECTIONS", {"ca": {}}
        ), mock.patch.object(authoring, "reviewed_overlay", {}):
            corrected, count = authoring.reviewed_correction_values(
                source, translations, "ca"
            )
        self.assertEqual(count, 1)
        self.assertIn(authoring.ALARM_TERM_FALLBACK_MARKER, corrected[paragraph])
        with self.assertRaisesRegex(RuntimeError, "alarm-term authoring fallback"):
            checker.validate_translation_values(source, corrected, "fr")
        self.assertNotIn("Scheduled", corrected[paragraph])
        self.assertIn("Appareils où l’alarme sonne", corrected[paragraph])
        self.assertIn("Cet appareil", corrected[paragraph])
        self.assertIn("Programmé", corrected[paragraph])
        self.assertIn("Besoin d’autorisation", corrected[paragraph])
        self.assertIn("Échec", corrected[paragraph])

    def test_reviewed_alarm_term_changes_rewrite_policy_prose_without_fallback(self) -> None:
        paragraph = (
            "Use Rings On for This Device and review Scheduled, Pending Apply, "
            "Pending Cancellation, Needs Permission, Unavailable, Failed, or Sync Pending."
        )
        source = {term: term for term in checker.ALARM_UI_TERMS}
        source[paragraph] = paragraph
        translations = {
            "Rings On": "Enheter där detta larm ringer",
            "This Device": "Den här enheten",
            "Scheduled": "Schemalagt",
            "Pending Apply": "Väntar på att tillämpas",
            "Pending Cancellation": "Väntar på avbokning",
            "Needs Permission": "Behöver Tillstånd",
            "Unavailable": "Ej tillgänglig",
            "Failed": "Misslyckades",
            "Sync Pending": "Synkronisering väntar",
            paragraph: (
                "Använd Enheter där detta larm ringer för Den här enheten och granska "
                "Schemalagt, Väntar på att tillämpas, Väntar på avbokning, Behöver "
                "Tillstånd, Ej tillgänglig, Misslyckades eller Synkronisering väntar."
            ),
        }
        with mock.patch.object(authoring, "REVIEWED_TRANSLATION_CORRECTIONS", {}):
            corrected, _ = authoring.reviewed_correction_values(
                source, translations, "sv"
            )
        self.assertNotIn(authoring.ALARM_TERM_FALLBACK_MARKER, corrected[paragraph])
        for term in checker.ALARM_UI_TERMS:
            self.assertIn(
                authoring.embedded_alarm_term(corrected[term]),
                corrected[paragraph],
            )
        checker.validate_translation_values(source, corrected, "sv")
        checker.validate_alarm_ui_terminology(source, corrected, "sv")

    def test_alarm_term_import_copies_only_the_central_app_glossary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app_root = root / "App"
            website_root = root / "Website"
            app_catalog = app_root / "fr.lproj" / "Localizable.strings"
            website_catalog = website_root / "fr.lproj" / "Website.strings"
            app_catalog.parent.mkdir(parents=True)
            website_catalog.parent.mkdir(parents=True)
            app_values = {term: f"app:{term}" for term in authoring.ALARM_UI_TERMS}
            app_values["Unrelated App Copy"] = "Do not import"
            app_catalog.write_text(
                authoring.localized_strings_document(app_values), encoding="utf-8"
            )
            website_catalog.write_text(
                authoring.localized_strings_document({"Existing": "Existant"}),
                encoding="utf-8",
            )
            authoring.import_alarm_terms(app_root, website_root, ["fr"])
            result = authoring.load_strings(website_catalog)
        self.assertEqual(result["Existing"], "Existant")
        self.assertNotIn("Unrelated App Copy", result)
        for term in authoring.ALARM_UI_TERMS:
            self.assertEqual(result[term], f"app:{term}")

    def test_cross_repo_alarm_terms_require_valid_exact_supplied_sources(self) -> None:
        source = {term: term for term in checker.ALARM_UI_TERMS}
        website = {
            "fr": {term: f"app:{term}" for term in checker.ALARM_UI_TERMS}
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                checker.validate_alarm_terms_against_app(source, website, root / "missing")
            root.mkdir(exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, "Missing app alarm-term source catalog"):
                checker.validate_alarm_terms_against_app(source, website, root)
            supported = {
                term: term
                for term in checker.ALARM_UI_TERMS
                if term != "Sync Pending"
            }
            english_catalog = root / "en.lproj" / "Localizable.strings"
            english_catalog.parent.mkdir()
            english_catalog.write_text(
                authoring.localized_strings_document(supported), encoding="utf-8"
            )
            changed_english = dict(supported)
            changed_english["Rings On"] = "Rings Here"
            english_catalog.write_text(
                authoring.localized_strings_document(changed_english), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "differs from WebsiteSource"):
                checker.validate_alarm_terms_against_app(source, website, root)
            english_catalog.write_text(
                authoring.localized_strings_document(supported), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "Missing app alarm-term catalog"):
                checker.validate_alarm_terms_against_app(source, website, root)
            catalog = root / "fr.lproj" / "Localizable.strings"
            catalog.parent.mkdir()
            catalog.write_text(
                authoring.localized_strings_document(
                    {term: website["fr"][term] for term in supported}
                ),
                encoding="utf-8",
            )
            checker.validate_alarm_terms_against_app(source, website, root)
            changed = {term: website["fr"][term] for term in supported}
            changed["This Device"] = ""
            catalog.write_text(
                authoring.localized_strings_document(changed), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "localized value is missing"):
                checker.validate_alarm_terms_against_app(source, website, root)
            changed["This Device"] = website["fr"]["This Device"]
            changed["Rings On"] = "different"
            catalog.write_text(
                authoring.localized_strings_document(changed), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "differs from app"):
                checker.validate_alarm_terms_against_app(source, website, root)

    def test_every_policy_date_has_matching_machine_and_visible_values(self) -> None:
        for page in checker.POLICY_PAGES:
            parser = checker.parsed_page(ROOT / page)
            checker.validate_policy_date(
                parser, ROOT / page, checker.POLICY_VISIBLE_DATE_SOURCE
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "privacy.html"
            path.write_text(
                '<!doctype html><html><head><meta name="xtimers-policy-effective-date" '
                'content="2026-08-23"></head><body><time datetime="2026-08-23">'
                "August 22, 2026</time></body></html>",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "visible-date mismatch"):
                checker.validate_policy_date(
                    checker.parsed_page(path), path, checker.POLICY_VISIBLE_DATE_SOURCE
                )
        with self.assertRaisesRegex(RuntimeError, "date block is missing"):
            checker.expected_localized_policy_date(authoring, "privacy.html", {})

    def test_rtl_page_css_uses_logical_callout_and_list_properties(self) -> None:
        stylesheet = (ROOT / "assets" / "flexible-timers" / "page.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("padding-inline-start: 24px", stylesheet)
        self.assertIn("border-inline-start: 3px solid var(--accent)", stylesheet)
        self.assertIn("border-start-start-radius: 0", stylesheet)
        self.assertIn("border-end-start-radius: 0", stylesheet)
        self.assertNotIn("padding-left:", stylesheet)
        self.assertNotIn("border-left:", stylesheet)
        for identifier in ("ar", "he", "ur"):
            parser = checker.parsed_page(ROOT / identifier / "index.html")
            self.assertEqual((parser.html_attributes or {}).get("dir"), "rtl")

    def test_compliance_checker_matches_bounded_evidence_capitalization(self) -> None:
        checker_script = (ROOT / "scripts" / "check-compliance-pages.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Removing or uninstalling the app may leave.*Bounded cancellation, "
            "deletion, security, and diagnostic evidence",
            checker_script,
        )
        choices = (ROOT / "privacy-choices.html").read_text(encoding="utf-8")
        self.assertIn("Bounded cancellation, deletion, security, and diagnostic evidence", choices)

    def test_live_homepage_checks_use_approved_copy_and_reject_missing_claims(self) -> None:
        checker_script = (ROOT / "scripts" / "check-compliance-pages.sh").read_text(
            encoding="utf-8"
        )
        homepage = " ".join((ROOT / "index.html").read_text(encoding="utf-8").split())
        cases = {
            "Homepage distinguishes Xin sign-in from XTimers product data": [
                ("XTimers uses a Xin Account", "XTimers uses an account"),
                ("shared identity layer", "profile"),
                ("not an XTimers product account", "an XTimers product account"),
                ("does not contain XTimers timers", "contains XTimers timers"),
            ],
            "Homepage describes Apple platforms": [
                ("For Mac, iPhone &amp; iPad", "For iPhone &amp; iPad"),
                ("For Mac, iPhone &amp; iPad", "For Mac &amp; iPad"),
                ("For Mac, iPhone &amp; iPad", "For Mac &amp; iPhone"),
            ],
        }
        for label, mutations in cases.items():
            marker = f'check "{label}" \\\n'
            self.assertIn(marker, checker_script)
            assertion = checker_script.split(marker, 1)[1].splitlines()[0].strip()
            prefix = 'page_text_has "/" "'
            self.assertTrue(assertion.startswith(prefix), label)
            self.assertTrue(assertion.endswith('"'), label)
            pattern = assertion[len(prefix):-1]

            def matches(text: str) -> bool:
                return subprocess.run(
                    ["grep", "-Eq", pattern], input=text, text=True, check=False
                ).returncode == 0

            self.assertTrue(matches(homepage), label)
            for before, after in mutations:
                with self.subTest(check=label, missing=before):
                    self.assertIn(before, homepage)
                    self.assertFalse(matches(homepage.replace(before, after)))

    def test_sms_pages_distinguish_proposed_phone_verification_from_reminders(self) -> None:
        pages = [
            "privacy.html",
            "privacy-choices.html",
            "terms.html",
            "sms-terms.html",
            "sms-opt-in.html",
            "support.html",
            "compliance.html",
        ]
        for page in pages:
            text = " ".join((ROOT / page).read_text(encoding="utf-8").split())
            self.assertIn("proposed account phone number", text, page)
            self.assertIn("successful verification", text, page)
            self.assertIn("same phone number", text, page)

    def test_deletion_inventory_and_recovery_record_are_truthful(self) -> None:
        privacy = " ".join((ROOT / "privacy.html").read_text(encoding="utf-8").split())
        choices = " ".join(
            (ROOT / "privacy-choices.html").read_text(encoding="utf-8").split()
        )
        for text in [privacy, choices]:
            self.assertIn("session and task history", text)
            self.assertIn("published reports and report links", text)
            self.assertIn("protected, operation-scoped recovery record", text)
            self.assertIn("does not retain the emailed verification code", text)
        self.assertNotIn("non-secret recovery record", choices)

    def test_report_expiry_choices_match_current_app_controls(self) -> None:
        privacy = " ".join((ROOT / "privacy.html").read_text(encoding="utf-8").split())
        choices = " ".join(
            (ROOT / "privacy-choices.html").read_text(encoding="utf-8").split()
        )
        for text in (privacy, choices):
            self.assertIn("1, 7, 30, 90", text)
            self.assertIn("365 days", text)

    def test_terms_use_a_configuration_safe_app_store_license_statement(self) -> None:
        terms = " ".join((ROOT / "terms.html").read_text(encoding="utf-8").split())
        self.assertIn(
            "Apple's Standard Licensed Application End User License Agreement unless "
            "a custom license agreement is presented for XTimers in the App Store or "
            "App Store Connect",
            terms,
        )
        self.assertIn(
            'href="https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"',
            terms,
        )
        self.assertNotIn("App Store copies are also licensed under", terms)

        source_fragment = (
            "App Store copies are governed by\n"
            "      Apple's Standard Licensed Application End User License Agreement unless\n"
            "      a custom license agreement is presented for XTimers in the App Store or\n"
            "      App Store Connect; these terms supplement the applicable license for\n"
            "      XTimers accounts and services."
        )
        expected = {
            "tr": "App Store kopyaları, XTimers için App Store'da veya App Store Connect'te özel bir lisans sözleşmesi sunulmadıkça Apple'ın Standart Lisanslı Uygulama Son Kullanıcı Lisans Sözleşmesi'ne tabidir; bu şartlar XTimers hesapları ve hizmetleri için geçerli lisansı tamamlar.",
            "uk": "Копії App Store регулюються Стандартною ліцензійною угодою кінцевого користувача ліцензованого застосунку Apple, якщо для XTimers в App Store або App Store Connect не представлено спеціальну ліцензійну угоду; ці умови доповнюють застосовну ліцензію щодо облікових записів і послуг XTimers.",
        }
        for identifier, value in expected.items():
            self.assertEqual(
                authoring.REVIEWED_TRANSLATION_CORRECTIONS[identifier][source_fragment],
                value,
            )

    def test_sms_pages_do_not_promise_unverified_keyword_responses(self) -> None:
        pages = ["sms-terms.html", "sms-opt-in.html", "compliance.html"]
        obsolete = [
            "You are opted out of XTimers SMS",
            "XTimers supports account verification codes",
            "You have opted back in to XTimers SMS",
        ]
        for page in pages:
            text = " ".join((ROOT / page).read_text(encoding="utf-8").split())
            self.assertIn("may opt", text, page)
            self.assertIn("does not promise", text, page)
            for response in obsolete:
                self.assertNotIn(response, text, page)

    def test_sms_samples_allow_provider_templates_and_body_trimming(self) -> None:
        text = " ".join((ROOT / "sms-opt-in.html").read_text(encoding="utf-8").split())
        self.assertIn("provider- or region-specific template", text)
        self.assertIn("trimming and delivery-provider formatting", text)
        self.assertNotIn("generated code in this exact format", text)
        self.assertNotIn("user-created body unchanged", text)

    def test_generated_page_equivalence_rejects_mutated_localized_prose(self) -> None:
        expected = "<!doctype html>\n<html lang=\"fr\"><body>Texte exact.</body></html>\n"
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "privacy.html"
            page.write_text(expected, encoding="utf-8")
            checker.validate_generated_page_equivalence(page, expected)
            page.write_text(expected.replace("Texte exact", "Texte altéré"), encoding="utf-8")
            with self.assertRaisesRegex(
                RuntimeError, "not the exact generated catalog output"
            ):
                checker.validate_generated_page_equivalence(page, expected)

    def test_sitemap_generation_is_complete_and_idempotent(self) -> None:
        source = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://xintechllc.com/XTimers/</loc></url>
  <url><loc>https://xintechllc.com/XTimers/flexible-timers.html</loc></url>
  <url><loc>https://xintechllc.com/XTimers/ur/</loc></url>
  <url><loc>https://xintechllc.com/XTimers/support.html</loc></url>
</urlset>
"""
        generated = navigation.updated_sitemap(source, self.inventory)
        expected_urls = navigation.expected_sitemap_urls(self.inventory)
        self.assertEqual(len(expected_urls), 14 + (len(self.inventory) - 1) * 8)
        for path in (
            "guides/", "guides/menu-bar-timer.html", "guides/multiple-task-timers.html",
            "guides/recover-timer-data.html", "press/",
        ):
            self.assertIn(navigation.BASE_URL + path, expected_urls)
        expected_set = set(expected_urls)
        for item in self.inventory:
            identifier = item["identifier"]
            if identifier == "en":
                self.assertIn("https://xintechllc.com/XTimers/", expected_set)
                self.assertIn("https://xintechllc.com/XTimers/support.html", expected_set)
                legal_prefix = "https://xintechllc.com/FlexibleTimers/"
            else:
                self.assertIn(f"https://xintechllc.com/XTimers/{identifier}/", expected_set)
                self.assertIn(
                    f"https://xintechllc.com/XTimers/{identifier}/support.html",
                    expected_set,
                )
                legal_prefix = f"https://xintechllc.com/FlexibleTimers/{identifier}/"
            for page in (
                "terms.html",
                "privacy.html",
                "privacy-choices.html",
                "extension-privacy.html",
                "sms-terms.html",
                "sms-opt-in.html",
            ):
                self.assertIn(legal_prefix + page, expected_set)
        self.assertEqual(generated.count("<loc>"), len(expected_urls))
        self.assertIn("https://xintechllc.com/XTimers/bn/", generated)
        self.assertIn("https://xintechllc.com/XTimers/ur/", generated)
        self.assertIn(
            "https://xintechllc.com/FlexibleTimers/ur/privacy-choices.html",
            generated,
        )
        self.assertNotIn(
            "https://xintechllc.com/XTimers/flexible-timers.html", generated
        )
        self.assertIn(
            "https://xintechllc.com/FlexibleTimers/extension-privacy.html", generated
        )
        self.assertNotIn("https://xintechllc.com/XTimers/obsolete/", generated)
        self.assertEqual(navigation.updated_sitemap(generated, self.inventory), generated)
        with tempfile.TemporaryDirectory() as directory:
            sitemap = Path(directory) / "sitemap.xml"
            sitemap.write_text(generated, encoding="utf-8")
            checker.validate_sitemap(sitemap, expected_urls)
            sitemap.write_text(
                generated.replace(
                    "  <url>\n    <loc>https://xintechllc.com/FlexibleTimers/extension-privacy.html</loc>\n  </url>\n",
                    "",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "do not exactly match"):
                checker.validate_sitemap(sitemap, expected_urls)

    def test_release_manifest_detects_snapshot_and_localized_page_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            target = root / "target"
            (source / "generated").mkdir(parents=True)
            (source / "generated" / "localizations.json").write_text(
                json.dumps(
                    {
                        "localizations": [
                            {"identifier": "en"},
                            {"identifier": "fr"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (source / "generated" / "WebsiteSource.strings").write_text(
                '"Source" = "Source";\n', encoding="utf-8"
            )
            (source / "fr").mkdir()
            for page in release_verifier.PAGE_NAMES:
                (source / "fr" / page).write_text(f"fr:{page}\n", encoding="utf-8")
            (source / "sitemap.xml").write_text("sitemap\n", encoding="utf-8")
            shutil.copytree(source, target)
            release_verifier.verify_local_tree(source, target)
            fingerprint = release_verifier.deployable_tree_digest(source)
            (source / "generated" / "WebsiteSource.strings").write_text(
                '"Source changed" = "Source changed";\n', encoding="utf-8"
            )
            self.assertNotEqual(
                fingerprint, release_verifier.deployable_tree_digest(source)
            )
            (source / "generated" / "WebsiteSource.strings").write_text(
                '"Source" = "Source";\n', encoding="utf-8"
            )
            self.assertEqual(
                fingerprint, release_verifier.deployable_tree_digest(source)
            )
            (source / "fr" / "privacy.html").write_text("mutated\n", encoding="utf-8")
            self.assertNotEqual(
                fingerprint, release_verifier.deployable_tree_digest(source)
            )
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                release_verifier.verify_local_tree(source, target)

    def test_live_release_readiness_retries_translation_only_staleness(self) -> None:
        payloads = {
            "sitemap.xml": b"stable sitemap",
            "fr/privacy.html": b"translated privacy",
        }
        expected = {
            relative: release_verifier.sha256_bytes(payload)
            for relative, payload in payloads.items()
        }
        stale_once = {"fr/privacy.html"}

        def fetch(url: str) -> bytes:
            relative = url.split("https://example.test/", 1)[1].split("?", 1)[0]
            if relative in stale_once:
                stale_once.remove(relative)
                return b"stale translation"
            return payloads[relative]

        with mock.patch.object(release_verifier, "fetched", side_effect=fetch):
            self.assertEqual(
                release_verifier.live_digest_mismatches(
                    expected, "https://example.test/"
                ),
                ["fr/privacy.html"],
            )
            self.assertEqual(
                release_verifier.live_digest_mismatches(
                    expected, "https://example.test/"
                ),
                [],
            )

    def test_origin_robots_helper_preserves_other_products_and_is_idempotent(self) -> None:
        helper = ROOT / "scripts" / "ensure-origin-robots-sitemap.sh"
        with tempfile.TemporaryDirectory() as directory:
            robots = Path(directory) / "robots.txt"
            robots.write_text(
                "User-agent: *\nAllow: /\n\nSitemap: https://xintechllc.com/sitemap.xml\n",
                encoding="utf-8",
            )
            subprocess.run([str(helper), str(robots)], check=True)
            first = robots.read_text(encoding="utf-8")
            self.assertIn("Sitemap: https://xintechllc.com/sitemap.xml", first)
            self.assertEqual(
                first.count("Sitemap: https://xintechllc.com/XTimers/sitemap.xml"), 1
            )
            subprocess.run([str(helper), str(robots)], check=True)
            self.assertEqual(first, robots.read_text(encoding="utf-8"))
            subprocess.run([str(helper), "--check", str(robots)], check=True)

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
            publisher.index('publish_to "$SOURCE_STAGE" "$DEST_DIR_NEW"'),
        )
        self.assertIn('node "$CALLBACK_CHECK"', publisher)
        self.assertIn("create_release_snapshot", publisher)
        self.assertLess(
            publisher.index("create_release_snapshot\n"),
            publisher.index('publish_to "$SOURCE_STAGE" "$DEST_DIR_NEW"'),
        )
        self.assertIn('XTIMERS_WEBSITE_ROOT="$SOURCE_STAGE"', publisher)
        self.assertIn("assert_snapshot_unchanged", publisher)
        self.assertIn('--verify-live "$PUBLIC_BASE_URL"', publisher)
        self.assertIn('--verify-live "$LEGACY_BASE_URL"', publisher)
        self.assertIn("ensure-origin-robots-sitemap.sh", publisher)
        self.assertIn('"$SOURCE_STAGE/scripts/check-compliance-pages.sh" --no-live', publisher)
        self.assertIn('LIVE_BASE_URL="$PUBLIC_BASE_URL"', publisher)
        self.assertIn('LIVE_BASE_URL="$LEGACY_BASE_URL"', publisher)
        self.assertIn(
            '"[skip ci] Publish XTimers website (canonical + legacy mirror)"',
            publisher,
        )
        compliance_check = (ROOT / "scripts" / "check-compliance-pages.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("-x .DS_Store", compliance_check)
        self.assertIn("CANONICAL_PAGES_ROOT", compliance_check)
        self.assertIn("LEGACY_PAGES_ROOT", compliance_check)
        self.assertIn("reconciled_privacy_and_callback_semantics", compliance_check)
        self.assertIn("Personal Calendar Overlay", compliance_check)
        self.assertIn("local data area.*system Keychain", compliance_check)
        self.assertIn("setTimeout\\(returnToApp", compliance_check)


if __name__ == "__main__":
    unittest.main()
