#!/usr/bin/env bash
set -euo pipefail

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
  shift
fi
if [[ "$#" -ne 1 ]]; then
  printf 'usage: %s [--check] ROBOTS_FILE\n' "$0" >&2
  exit 2
fi

ROBOTS_FILE="$1"
DIRECTIVE='Sitemap: https://xintechllc.com/XTimers/sitemap.xml'
[[ -f "$ROBOTS_FILE" ]] || {
  printf 'error: robots file does not exist: %s\n' "$ROBOTS_FILE" >&2
  exit 1
}

COUNT="$(grep -Fxc "$DIRECTIVE" "$ROBOTS_FILE" || true)"
if [[ "$COUNT" -eq 1 ]]; then
  exit 0
fi
if [[ "$CHECK_ONLY" -eq 1 ]]; then
  printf 'error: expected exactly one XTimers sitemap directive in %s\n' \
    "$ROBOTS_FILE" >&2
  exit 1
fi

TMP_FILE="$(mktemp "${ROBOTS_FILE}.tmp.XXXXXX")"
cleanup() { rm -f -- "$TMP_FILE"; }
trap cleanup EXIT

# Preserve every unrelated directive and product sitemap. Remove only duplicate
# copies of this exact product directive before appending one canonical line.
awk -v directive="$DIRECTIVE" '$0 != directive { print }' "$ROBOTS_FILE" > "$TMP_FILE"
printf '\n%s\n' "$DIRECTIVE" >> "$TMP_FILE"
chmod "$(stat -f '%Lp' "$ROBOTS_FILE")" "$TMP_FILE"
mv -f -- "$TMP_FILE" "$ROBOTS_FILE"
trap - EXIT
