#!/usr/bin/env python3
"""Materialize a full-catalog direct Codex/GPT review artifact."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = load_module("direct_gpt_catalog_checker", ROOT / "scripts" / "check-localizations.py")
authoring = load_module(
    "direct_gpt_catalog_authoring", ROOT / "scripts" / "prepare-localized-page-drafts.py"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("locale")
    parser.add_argument("corrections", type=Path)
    parser.add_argument("--reviewed-all-values", action="store_true", required=True)
    arguments = parser.parse_args()
    source = checker.load_strings(ROOT / "generated" / "WebsiteSource.strings")
    path = (
        ROOT
        / "generated"
        / "WebsiteTranslations"
        / f"{arguments.locale}.lproj"
        / "Website.strings"
    )
    translations = checker.load_strings(path)
    corrections = json.loads(arguments.corrections.read_text(encoding="utf-8"))
    if not isinstance(corrections, dict) or any(key not in source for key in corrections):
        raise RuntimeError("Direct GPT correction packet is malformed")
    translations.update({str(key): str(value) for key, value in corrections.items()})
    if set(translations) != set(source):
        raise RuntimeError(f"Full direct GPT catalog review requires all {len(source)} values")
    checker.validate_translation_values(source, translations, arguments.locale)
    output = (
        ROOT / "generated" / "DirectGPTWebsiteTranslations" / f"{arguments.locale}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "locale": arguments.locale,
                "authorship": "direct-codex-gpt",
                "reviewScope": f"all-{len(source)}-values-retranslated-or-reaffirmed-from-English",
                "translations": translations,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.write_text(authoring.localized_strings_document(translations), encoding="utf-8")
    print(f"Materialized direct GPT review for {arguments.locale}: {len(translations)} values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
