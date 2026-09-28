#!/usr/bin/env python3
"""Merge directly authored landing-page packets with unchanged reviewed website copy.

This deterministic importer never creates translations or approval. Every new
value must come from a complete, source-bound Codex/GPT packet with a completed
semantic review; retained values must match their existing direct-GPT authority.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


authoring = module('landing_authoring', ROOT / 'scripts/prepare-localized-page-drafts.py')
checker = module('landing_checker', ROOT / 'scripts/check-localizations.py')


def materialize(packet_root: Path, locale: str, write: bool) -> int:
    source_path = ROOT / 'generated/WebsiteSource.strings'
    source = authoring.load_strings(source_path)
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    packet_source = json.loads((packet_root / 'source.json').read_text())
    packet = json.loads((packet_root / f'{locale}.json').read_text())
    if packet_source['sourceSha256'] != source_hash or packet['sourceSha256'] != source_hash:
        raise RuntimeError(f'{locale}: source changed after translation')
    if packet.get('authorship') != 'direct-codex-gpt' or packet.get('locale') != locale:
        raise RuntimeError(f'{locale}: invalid authorship or locale')
    review = packet.get('review', {})
    if review.get('model') != 'gpt-6' or review.get('qualifiedNativeReview') is not False or not review.get('completedAt'):
        raise RuntimeError(f'{locale}: missing truthful completed semantic review')
    if set(packet['translations']) != set(packet_source['strings']):
        raise RuntimeError(f'{locale}: incomplete translation packet')
    new = {text: packet['translations'][key] for key, text in packet_source['strings'].items()}
    if not set(new) <= set(source):
        raise RuntimeError(f'{locale}: obsolete packet values')
    authority_path = ROOT / 'generated/DirectGPTWebsiteTranslations' / f'{locale}.json'
    authority_bytes = authority_path.read_bytes()
    authority = json.loads(authority_bytes)
    catalog_path = ROOT / 'generated/WebsiteTranslations' / f'{locale}.lproj/Website.strings'
    existing = authoring.load_strings(catalog_path)
    if authority.get('authorship') != 'direct-codex-gpt' or authority['translations'] != existing:
        raise RuntimeError(f'{locale}: existing catalog disagrees with direct-GPT evidence')
    retained = {key: existing[key] for key in source if key not in new and key in existing}
    combined = {**retained, **new}
    checker.validate_translation_values(source, combined, locale)
    # Validate markup containment as well as the value-level signature.
    for filename in authoring.SOURCE_PAGES:
        soup = authoring.BeautifulSoup((ROOT / filename).read_text(), 'html.parser')
        authoring.replace_copy(soup, combined)
    if write:
        prior = authority.get('landingReview', {}).get('retainedAuthoritySha256')
        output = {
            'schemaVersion': 1,
            'locale': locale,
            'authorship': 'direct-codex-gpt',
            'reviewScope': f'all-{len(source)}-values-retranslated-or-reaffirmed-from-English',
            'landingReview': {
                'packet': str((packet_root / f'{locale}.json').relative_to(ROOT)),
                'sourceSha256': source_hash,
                'newValues': len(new),
                'retainedValues': len(retained),
                'retainedAuthoritySha256': prior or hashlib.sha256(authority_bytes).hexdigest(),
                'retention': 'Unchanged values retain the earlier direct-GPT review; the new review covers the landing-page delta.',
                'semanticReview': review,
            },
            'translations': dict(sorted(combined.items())),
        }
        authority_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
        catalog_path.write_text(authoring.localized_strings_document(combined))
    return len(combined)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-root', type=Path, default=ROOT / 'generated/LandingTranslations20260928')
    parser.add_argument('--locales', nargs='+')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    inventory = json.loads((ROOT / 'generated/localizations.json').read_text())['localizations']
    locales = args.locales or [item['identifier'] for item in inventory if item['identifier'] != 'en']
    for locale in locales:
        count = materialize(args.packet_root, locale, args.write)
        print(f'{locale}: {count} complete direct-GPT values ({"written" if args.write else "validated"})')


if __name__ == '__main__':
    try:
        main()
    except (OSError, KeyError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error))
