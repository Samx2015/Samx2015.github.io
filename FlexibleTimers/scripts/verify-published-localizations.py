#!/usr/bin/env python3
"""Fingerprint a staged site and verify every published localized page byte-for-byte."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


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
EXCLUDED_DIRECTORIES = {".git", "__pycache__"}
EXCLUDED_FILES = {
    ".DS_Store",
    ".gitignore",
    ".nojekyll",
    "README.md",
    "requirements-localization.txt",
    "scripts/publish.sh",
}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inventory(root: Path) -> list[dict]:
    document = json.loads(
        (root / "generated" / "localizations.json").read_text(encoding="utf-8")
    )
    values = document.get("localizations")
    if not isinstance(values, list):
        raise RuntimeError("Invalid website localization inventory")
    return values


def localized_paths(root: Path) -> list[Path]:
    return [
        Path(item["identifier"]) / page
        for item in inventory(root)
        if item["identifier"] != "en"
        for page in PAGE_NAMES
    ]


def localized_digest_manifest(root: Path) -> dict[str, str]:
    paths = [Path("sitemap.xml"), *localized_paths(root)]
    return {
        path.as_posix(): sha256_bytes((root / path).read_bytes()) for path in paths
    }


def deployable_tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if relative.as_posix() in EXCLUDED_FILES or path.name.endswith(".pyc"):
            continue
        files.append(relative)
    for relative in sorted(files, key=lambda item: item.as_posix()):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def verify_local_tree(source: Path, target: Path) -> None:
    expected = localized_digest_manifest(source)
    actual = {
        relative: sha256_bytes((target / relative).read_bytes())
        for relative in expected
    }
    if actual != expected:
        mismatches = sorted(
            relative for relative in expected if actual.get(relative) != expected[relative]
        )
        raise RuntimeError(
            "Published localization digest mismatch: " + ", ".join(mismatches[:5])
        )


def fetched(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "User-Agent": "XTimers-release-verifier/1"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def live_digest_mismatches(expected: dict[str, str], base: str) -> list[str]:
    """Fetch one complete release view and return every stale/unavailable path."""
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(
                fetched,
                base + relative + "?release-check=" + digest,
            ): (relative, digest)
            for relative, digest in expected.items()
        }
        for future in as_completed(futures):
            relative, digest = futures[future]
            try:
                actual = sha256_bytes(future.result())
            except Exception:
                failures.append(relative)
                continue
            if actual != digest:
                failures.append(relative)
    return sorted(failures)


def verify_live(source: Path, base_url: str, poll_seconds: int) -> None:
    expected = localized_digest_manifest(source)
    base = base_url.rstrip("/") + "/"
    deadline = time.monotonic() + poll_seconds
    while True:
        failures = live_digest_mismatches(expected, base)
        if not failures:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for {len(failures)} release files at {base}: "
                + ", ".join(failures[:5])
            )
        time.sleep(5)
    print(f"Verified {len(expected) - 1} localized pages and sitemap at {base}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-tree-digest", action="store_true")
    mode.add_argument("--verify-local", type=Path, metavar="TARGET_ROOT")
    mode.add_argument("--verify-live", metavar="BASE_URL")
    parser.add_argument("--poll-seconds", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    source = arguments.source_root.resolve()
    if arguments.print_tree_digest:
        print(deployable_tree_digest(source))
    elif arguments.verify_local is not None:
        verify_local_tree(source, arguments.verify_local.resolve())
    else:
        verify_live(source, arguments.verify_live, arguments.poll_seconds)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}")
        raise SystemExit(1)
