#!/usr/bin/env python3
"""Build a value-level authorship inventory for website translations.

The inventory is deliberately conservative.  A value is marked GPT-authored
only when an exact checked-in Codex correction matches it.  Values added after
the frozen pre-legal-delta baseline are marked as non-GPT provider output unless
an exact correction supersedes them.  Older mixed-provenance values that cannot
be attributed at value granularity remain human/unknown instead of being given
invented authorship.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent / "TimerWorkspace"
BASELINE_REVISION = "e8410650b8e4d35006d139488573d1629ba93f56"
OUTPUT = ROOT / "generated" / "WebsiteValueProvenance.json"
ALARM_TERMS = {
    "Rings On",
    "This Device",
    "Scheduled",
    "Pending Apply",
    "Pending Cancellation",
    "Needs Permission",
    "Unavailable",
    "Failed",
    "Sync Pending",
}
INDIC_LOCALES = {"bn", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te", "ur"}
NEW_PROVIDER_BASELINE_LOCALES = {
    "bn",
    "gu",
    "kn",
    "ml",
    "mr",
    "or",
    "pa",
    "sl",
    "ta",
    "te",
    "ur",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


checker = load_module("website_provenance_checker", ROOT / "scripts" / "check-localizations.py")
authoring = load_module(
    "website_provenance_authoring", ROOT / "scripts" / "prepare-localized-page-drafts.py"
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def baseline_source() -> dict[str, str]:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_REVISION}:generated/WebsiteSource.strings"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Unable to read provenance baseline {BASELINE_REVISION}: "
            + result.stderr.decode(errors="replace").strip()
        )
    with tempfile.NamedTemporaryFile(suffix=".strings") as temporary:
        temporary.write(result.stdout)
        temporary.flush()
        return checker.load_strings(Path(temporary.name))


def codex_review_pairs(locale: str) -> set[tuple[str, str]]:
    path = WORKSPACE / "Docs" / "Localization" / "Corrections" / f"{locale}.json"
    if not path.is_file():
        return set()
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("reviewer") != "Codex" or document.get("translationProviderUsed") is not False:
        return set()
    return {
        (str(item["english"]), str(item["translation"]))
        for item in document.get("corrections", [])
        if isinstance(item, dict) and "english" in item and "translation" in item
    }


def exact_codex_values(locale: str) -> dict[str, str]:
    direct_path = (
        ROOT / "generated" / "DirectGPTWebsiteTranslations" / f"{locale}.json"
    )
    if direct_path.is_file():
        document = json.loads(direct_path.read_text(encoding="utf-8"))
        values = document.get("translations")
        if (
            document.get("authorship") == "direct-codex-gpt"
            and isinstance(values, dict)
            and set(values) == set(current_source)
        ):
            return {str(source): str(translated) for source, translated in values.items()}
    exact = {
        source: translated
        for source, translated in authoring.REVIEWED_TRANSLATION_CORRECTIONS.get(
            locale, {}
        ).items()
        if source in current_source
    }
    exact.update(authoring.reviewed_alarm_terms.get(locale, {}))
    return exact


def classify(
    locale: str,
    source: str,
    translated: str,
    baseline_keys: set[str],
    reviewed_pairs: set[tuple[str, str]],
    exact_values: dict[str, str],
) -> tuple[str, str]:
    if exact_values.get(source) == translated:
        return "gpt-authored", "checked-in exact Codex correction"
    if (source, translated) in reviewed_pairs:
        return (
            "gpt-authored",
            f"TimerWorkspace/Docs/Localization/Corrections/{locale}.json exact pair",
        )
    if locale in NEW_PROVIDER_BASELINE_LOCALES:
        provider = "translategemma-draft" if locale == "sl" else "indictrans2-pinned"
        return (
            "non-gpt-provider-authored",
            f"{provider}; new-2026 provider baseline without an exact later Codex correction",
        )
    if source in ALARM_TERMS:
        return "human-or-unknown", "imported app glossary; value-level origin unresolved"
    if source in baseline_keys:
        return (
            "human-or-unknown",
            f"pre-delta value at {BASELINE_REVISION}; mixed legacy provenance",
        )
    provider = "indictrans2-pinned" if locale in INDIC_LOCALES else "bing-web-draft"
    return (
        "non-gpt-provider-authored",
        f"{provider}; reconstructed from frozen 181-key delta boundary",
    )


def build_document() -> dict[str, object]:
    baseline_keys = set(baseline_source())
    source_bytes = (ROOT / "generated" / "WebsiteSource.strings").read_bytes()
    locales: dict[str, object] = {}
    for path in sorted((ROOT / "generated" / "WebsiteTranslations").glob("*.lproj/Website.strings")):
        locale = path.parent.name.removesuffix(".lproj")
        catalog = checker.load_strings(path)
        reviewed_pairs = codex_review_pairs(locale)
        exact_values = exact_codex_values(locale)
        values = []
        counts = {
            "gpt-authored": 0,
            "human-or-unknown": 0,
            "non-gpt-provider-authored": 0,
        }
        for source, translated in sorted(catalog.items()):
            classification, evidence = classify(
                locale,
                source,
                translated,
                baseline_keys,
                reviewed_pairs,
                exact_values,
            )
            counts[classification] += 1
            values.append(
                {
                    "source": source,
                    "translationSHA256": sha256_text(translated),
                    "classification": classification,
                    "evidence": evidence,
                }
            )
        locales[locale] = {
            "catalogSHA256": sha256_bytes(path.read_bytes()),
            "counts": counts,
            "values": values,
        }
    return {
        "schemaVersion": 1,
        "policy": {
            "accepted": ["gpt-authored", "human-or-unknown"],
            "rejected": ["non-gpt-provider-authored"],
            "unknownIsNotInventedApproval": True,
        },
        "baselineRevision": BASELINE_REVISION,
        "sourceSHA256": sha256_bytes(source_bytes),
        "locales": locales,
    }


def serialized(document: dict[str, object]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    value = serialized(build_document())
    if arguments.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != value:
            raise RuntimeError("Website value-provenance inventory is stale")
        return 0
    OUTPUT.write_text(value, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


current_source = checker.load_strings(ROOT / "generated" / "WebsiteSource.strings")


if __name__ == "__main__":
    raise SystemExit(main())
