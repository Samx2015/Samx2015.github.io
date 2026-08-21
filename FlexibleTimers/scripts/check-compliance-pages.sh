#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://xintechllc.com/FlexibleTimers}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://xintechllc.com/XTimers}"
LIVE_BASE_URL="${LIVE_BASE_URL:-$BASE_URL}"
CANONICAL_PAGES_ROOT="${CANONICAL_PAGES_ROOT:-/Users/sam/GitHub/Samx2015.github.io/XTimers}"
LEGACY_PAGES_ROOT="${LEGACY_PAGES_ROOT:-${PAGES_ROOT:-/Users/sam/GitHub/Samx2015.github.io/FlexibleTimers}}"
CHECK_LIVE=1

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --no-live) CHECK_LIVE=0 ;;
    -h|--help)
      printf 'usage: %s [--no-live]\n' "$0"
      exit 0
      ;;
    *) printf 'error: unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

require_command dirname
require_command mktemp
require_command rm

LOCAL_ROOT="${LOCAL_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOCAL_ROOT="$(cd "$LOCAL_ROOT" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

failures=0

check() {
  local description="$1"
  shift
  if "$@"; then
    echo "PASS $description"
  else
    echo "FAIL $description" >&2
    failures=$((failures + 1))
  fi
}

fetch() {
  local path="$1"
  local output="$TMP_DIR/${path//\//_}"
  if [[ "$path" == "/" ]]; then
    output="$TMP_DIR/index"
  fi
  curl -fsSL "$LIVE_BASE_URL$path" -o "$output"
  printf '%s' "$output"
}

page_has() {
  local path="$1"
  local pattern="$2"
  local file
  file="$(fetch "$path")"
  grep -Eq "$pattern" "$file"
}

page_text_has() {
  local path="$1"
  local pattern="$2"
  local file
  file="$(fetch "$path")"
  tr '\n' ' ' < "$file" | sed -E 's/[[:space:]]+/ /g' | grep -Eq "$pattern"
}

page_text_lacks() {
  ! page_text_has "$@"
}

local_text_has() {
  local relative_path="$1"
  local pattern="$2"
  tr '\n' ' ' < "$LOCAL_ROOT/$relative_path" | sed -E 's/[[:space:]]+/ /g' | grep -Eq "$pattern"
}

url_ok() {
  local path="$1"
  curl -fsSIL "$LIVE_BASE_URL$path" >/dev/null
}

content_type_has() {
  local path="$1"
  local pattern="$2"
  curl -fsSIL "$LIVE_BASE_URL$path" | grep -Eqi "^content-type: $pattern"
}

pages_deploy_tree_matches_source() {
  local pages_root="$1"
  pages_root="$(cd "$pages_root" && pwd)"
  local diff_args=(-qr
    -x .git
    -x .DS_Store
    -x .gitignore
    -x .nojekyll
    -x __pycache__
    -x '*.pyc'
    -x generated
    -x README.md
    -x requirements-localization.txt
    -x publish.sh)
  if [[ ! -d "$LOCAL_ROOT/download" ]]; then
    diff_args+=(-x download)
  fi

  diff "${diff_args[@]}" "$LOCAL_ROOT" "$pages_root"
}

tree_text_has() {
  local root="$1"
  local relative_path="$2"
  local pattern="$3"
  tr '\n' ' ' < "$root/$relative_path" \
    | sed -E 's/[[:space:]]+/ /g' \
    | grep -Eq "$pattern"
}

tree_text_lacks() {
  ! tree_text_has "$@"
}

reconciled_privacy_and_callback_semantics() {
  local root="$1"
  tree_text_has "$root" privacy.html "Personal Calendar Overlay" \
    && tree_text_has "$root" privacy.html "local data area.*system Keychain" \
    && tree_text_has "$root" privacy.html \
      'id="xin-account".*shared identity layer.*Delete XTimers Data.*Delete Xin Account' \
    && tree_text_has "$root" privacy.html "Last updated: August 21, 2026" \
    && tree_text_has "$root" privacy-choices.html \
      "Sign Out of XTimers.*Remove XTimers From a Device.*Delete XTimers Data.*Delete Xin Account" \
    && tree_text_has "$root" privacy-choices.html \
      "fresh security code sent to the Xin Account email" \
    && tree_text_has "$root" terms.html \
      'id="xin-account".*XTimers Product and Messaging Use.*Effective: August 21, 2026' \
    && tree_text_has "$root" support.html \
      'id="xin-account".*XTimers Product and Data Support.*XTimers Messaging Help' \
    && tree_text_has "$root" index.html \
      "Xin Account sign-in\. XTimers data stays separate" \
    && tree_text_has "$root" auth/complete.html \
      'data-callback-url="xtimers-auth://auth/callback".*Xin Account secure sign-in for XTimers.*id="auth-help".*id="retry-open"' \
    && tree_text_has "$root" auth/complete-pro.html \
      'data-callback-url="xtimers-pro-auth://auth/callback".*Xin Account secure sign-in for XTimers Pro.*id="auth-help".*id="retry-open"' \
    && tree_text_has "$root" assets/flexible-timers/auth-complete.js \
      'openApp\.addEventListener\("click", returnToApp\)' \
    && tree_text_has "$root" assets/flexible-timers/auth-complete.js \
      'retry\.addEventListener\("click", returnToApp\)' \
    && tree_text_lacks "$root" assets/flexible-timers/auth-complete.js \
      'setTimeout\(returnToApp' \
    && tree_text_has "$root" assets/flexible-timers/auth-complete.css \
      '\.help\[hidden\]'
}

public_xin_surfaces_are_provider_neutral() {
  local relative_path
  for relative_path in \
    README.md \
    privacy.html \
    privacy-choices.html \
    terms.html \
    support.html \
    auth/complete.html \
    auth/complete-pro.html
  do
    if grep -Eqi 'Supabase|Azure|Twilio' "$LOCAL_ROOT/$relative_path"; then
      echo "Implementation-provider name found in $relative_path" >&2
      return 1
    fi
  done
}

localized_flexible_timers_pages_exist() {
  local page
  local locale_dir
  local failed=0
  while IFS= read -r locale_dir; do
    local locale
    locale="$(basename "$locale_dir")"
    for page in index.html support.html privacy.html sms-terms.html sms-opt-in.html; do
      if [[ ! -f "$locale_dir/$page" ]]; then
        echo "Missing localized page: $locale/$page" >&2
        failed=1
      fi
    done
  done < <(find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name assets ! -name auth ! -name generated ! -name scripts | sort)

  return "$failed"
}

localized_flexible_timers_pages_declare_language() {
  local page
  local locale_dir
  local failed=0
  while IFS= read -r locale_dir; do
    local locale
    locale="$(basename "$locale_dir")"
    for page in index.html support.html privacy.html sms-terms.html sms-opt-in.html; do
      if ! local_text_has "$locale/$page" "<html[^>]*lang=\"$locale\""; then
        echo "Missing lang=\"$locale\" on localized page: $locale/$page" >&2
        failed=1
      fi
    done
  done < <(find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name assets ! -name auth ! -name generated ! -name scripts | sort)

  return "$failed"
}

localized_flexible_timers_pages_have_canonicals() {
  local page
  local locale_dir
  local failed=0
  while IFS= read -r locale_dir; do
    local locale
    locale="$(basename "$locale_dir")"
    for page in index.html support.html privacy.html sms-terms.html sms-opt-in.html; do
      local canonical
      if [[ "$page" == "index.html" ]]; then
        canonical="$PUBLIC_BASE_URL/$locale/"
      elif [[ "$page" == "support.html" ]]; then
        canonical="$PUBLIC_BASE_URL/$locale/$page"
      else
        canonical="$BASE_URL/$locale/$page"
      fi

      if ! local_text_has "$locale/$page" "(rel=\"canonical\"[^>]*href=\"$canonical\"|href=\"$canonical\"[^>]*rel=\"canonical\")"; then
        echo "Missing canonical URL on localized page: $locale/$page" >&2
        failed=1
      fi
    done
  done < <(find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name assets ! -name auth ! -name generated ! -name scripts | sort)

  return "$failed"
}

localized_flexible_timers_pages_have_footer_links() {
  local page
  local locale_dir
  local failed=0
  while IFS= read -r locale_dir; do
    local locale
    locale="$(basename "$locale_dir")"
    for page in index.html support.html privacy.html sms-terms.html sms-opt-in.html; do
      local footer
      footer="$(sed -n '/<footer/,/<\/footer>/p' "$locale_dir/$page" | tr '\n' ' ')"
      for required_href in \
        'href="support.html"' \
        'href="privacy.html"' \
        'href="https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"' \
        'href="sms-terms.html"' \
        'href="sms-opt-in.html"'
      do
        if [[ "$footer" != *"$required_href"* ]]; then
          echo "Missing footer link $required_href on localized page: $locale/$page" >&2
          failed=1
        fi
      done
    done
  done < <(find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name assets ! -name auth ! -name generated ! -name scripts | sort)

  return "$failed"
}

localized_xin_account_sections_exist() {
  local locale_dir
  local failed=0
  while IFS= read -r locale_dir; do
    local locale
    locale="$(basename "$locale_dir")"
    if ! local_text_has "$locale/privacy.html" 'id="xin-account"'; then
      echo "Missing Xin Account privacy section: $locale/privacy.html" >&2
      failed=1
    fi
    if ! local_text_has "$locale/support.html" 'id="xin-account"'; then
      echo "Missing Xin Account support section: $locale/support.html" >&2
      failed=1
    fi
    if ! local_text_has "$locale/index.html" 'href="privacy.html#xin-account"'; then
      echo "Missing Xin Account policy link: $locale/index.html" >&2
      failed=1
    fi
  done < <(find "$LOCAL_ROOT" -mindepth 1 -maxdepth 1 -type d ! -name '.*' ! -name assets ! -name auth ! -name generated ! -name scripts | sort)

  return "$failed"
}

require_command basename
require_command curl
require_command diff
require_command find
require_command grep
require_command sed
require_command sort
require_command tr

echo "Checking XTimers (legacy Flexible Timers) public SMS compliance pages"
echo "Live base URL: $LIVE_BASE_URL"
echo "Local root: $LOCAL_ROOT"
echo "Canonical Pages root: $CANONICAL_PAGES_ROOT"
echo "Legacy Pages root: $LEGACY_PAGES_ROOT"
echo

check "Editable source has reconciled privacy and callback semantics" \
  reconciled_privacy_and_callback_semantics "$LOCAL_ROOT"
check "Public Xin Account surfaces use provider-neutral wording" \
  public_xin_surfaces_are_provider_neutral

for deploy_name in Canonical Legacy; do
  if [[ "$deploy_name" == "Canonical" ]]; then
    deploy_root="$CANONICAL_PAGES_ROOT"
  else
    deploy_root="$LEGACY_PAGES_ROOT"
  fi
  if [[ -d "$deploy_root" ]]; then
    deploy_root="$(cd "$deploy_root" && pwd)"
    if [[ "$deploy_root" != "$LOCAL_ROOT" ]]; then
      check "$deploy_name Pages deploy subtree matches source" \
        pages_deploy_tree_matches_source "$deploy_root"
      check "$deploy_name Pages has reconciled privacy and callback semantics" \
        reconciled_privacy_and_callback_semantics "$deploy_root"
    else
      echo "SKIP $deploy_name Pages checks (local root is Pages root)"
    fi
  else
    echo "SKIP $deploy_name Pages checks (deploy root not found)"
  fi
done

check "Localized legacy-brand compliance pages exist" \
  localized_flexible_timers_pages_exist
check "Localized Flexible Timers pages declare matching languages" \
  localized_flexible_timers_pages_declare_language
check "Localized Flexible Timers pages carry canonical URLs" \
  localized_flexible_timers_pages_have_canonicals
check "Localized Flexible Timers pages keep footer link parity" \
  localized_flexible_timers_pages_have_footer_links
check "Localized pages include Xin Account policy sections" \
  localized_xin_account_sections_exist

if [[ "$CHECK_LIVE" -eq 0 ]]; then
  if [[ "$failures" -gt 0 ]]; then
    echo
    echo "$failures check(s) failed." >&2
    exit 1
  fi
  echo
  echo "All source and deploy-tree compliance checks passed."
  exit 0
fi

check "Homepage is reachable" url_ok "/"
check "Support page is reachable" url_ok "/support.html"
check "Terms page is reachable" url_ok "/terms.html"
check "Privacy page is reachable" url_ok "/privacy.html"
check "Privacy choices page is reachable" url_ok "/privacy-choices.html"
check "SMS Terms page is reachable" url_ok "/sms-terms.html"
check "SMS opt-in evidence page is reachable" url_ok "/sms-opt-in.html"
check "Compliance page is reachable" url_ok "/compliance.html"
check "SMS consent screenshot evidence is reachable" url_ok "/assets/sms-consent.png"
check "SMS consent screenshot is PNG" \
  content_type_has "/assets/sms-consent.png" "image/png"
check "Robots file is reachable" url_ok "/robots.txt"
check "Sitemap is reachable" url_ok "/sitemap.xml"
check "Standard OAuth completion page is reachable" \
  url_ok "/auth/complete.html"
check "Pro OAuth completion page is reachable" \
  url_ok "/auth/complete-pro.html"
check "OAuth completion script is reachable" \
  url_ok "/assets/flexible-timers/auth-complete.js"

check "Homepage distinguishes Xin sign-in from XTimers product data" \
  page_text_has "/" "Xin Account sign-in\. XTimers data stays separate"
check "Homepage names operator (footer)" \
  page_has "/" "Xintech LLC"
check "Homepage describes Apple platforms" \
  page_text_has "/" "Mac, iPhone, and iPad"
check "Homepage links support page" \
  page_has "/" "href=\"support.html\""
check "Homepage links privacy page" \
  page_has "/" "href=\"privacy.html\""
check "Homepage links SMS Terms page" \
  page_has "/" "href=\"sms-terms.html\""
check "Homepage links the Xin account-layer explanation" \
  page_has "/" 'href="privacy.html#xin-account"'
check "SMS Terms documents verification and reminder use" \
  page_has "/sms-terms.html" "verification codes and user-created"
check "SMS Terms documents own account phone scope" \
  page_text_has "/sms-terms.html" "own account phone number|own verified, opted-in account phone number"
check "SMS Terms links visible opt-in evidence URL" \
  page_has "/sms-terms.html" "xintechllc.com/FlexibleTimers/sms-opt-in.html"
check "SMS Terms documents no third-party SMS" \
  page_text_has "/sms-terms.html" "arbitrary third-party recipients"
check "SMS Terms documents STOP keyword" \
  page_has "/sms-terms.html" "Reply STOP to opt out"
check "SMS Terms documents HELP keyword" \
  page_has "/sms-terms.html" "Reply HELP for help"
check "SMS Terms documents START or YES keyword" \
  page_has "/sms-terms.html" "START or YES"
check "SMS Terms documents support URL" \
  page_has "/sms-terms.html" "xintechllc.com/FlexibleTimers/support.html"
check "SMS Terms says no marketing texts" \
  page_text_has "/sms-terms.html" "does not send marketing text messages"
check "SMS Terms says SMS is not two-way chat" \
  page_text_has "/sms-terms.html" "not a two-way chat"
check "SMS Terms says consent is not required for purchase" \
  page_has "/sms-terms.html" "Consent is not a condition of purchase"
check "SMS Terms includes exact STOP response" \
  page_text_has "/sms-terms.html" "You are opted out of Flexible Timers SMS\\. No more messages will be sent\\. Reply START to opt in again\\."
check "SMS Terms includes exact HELP response" \
  page_text_has "/sms-terms.html" "Flexible Timers sends account verification codes and reminder SMS you schedule for yourself\\. Help: https://xintechllc\\.com/FlexibleTimers/support\\.html\\. Reply STOP to opt out\\."
check "SMS Terms includes exact START response" \
  page_text_has "/sms-terms.html" "You have opted back in to Flexible Timers SMS messages\\. Message frequency varies\\. Reply STOP to opt out, HELP for help\\."
check "Privacy says SMS opt-in data is not sold" \
  page_text_has "/privacy.html" "does not sell SMS opt-in data"
check "Privacy says SMS opt-in data is not shared for marketing" \
  page_text_has "/privacy.html" "does not share SMS opt-in data"
check "Privacy links exact Twilio support URL" \
  page_has "/privacy.html" "href=\"https://xintechllc.com/XTimers/support.html\">xintechllc.com/XTimers/support.html</a>"
check "Privacy links privacy choices" \
  page_has "/privacy.html" "href=\"privacy-choices.html\""
check "Privacy includes Personal Calendar disclosure" \
  page_text_has "/privacy.html" "Personal Calendar Overlay"
check "Privacy includes local storage and Keychain disclosure" \
  page_text_has "/privacy.html" "local data area.*system Keychain"
check "Privacy separates Xin identity from XTimers product data" \
  page_text_has "/privacy.html" \
    "shared identity layer.*XTimers Product and Contact Information"
check "Privacy documents both deletion scopes" \
  page_text_has "/privacy.html" \
    "Delete XTimers Data.*Delete Xin Account"
check "Privacy carries the authorized N6b date" \
  page_has "/privacy.html" "Last updated: August 21, 2026"
check "Standard OAuth completion is click-driven" \
  page_text_has "/auth/complete.html" \
    'data-callback-url="xtimers-auth://auth/callback".*Xin Account secure sign-in for XTimers.*id="auth-help".*id="retry-open"'
check "Pro OAuth completion is click-driven" \
  page_text_has "/auth/complete-pro.html" \
    'data-callback-url="xtimers-pro-auth://auth/callback".*Xin Account secure sign-in for XTimers Pro.*id="auth-help".*id="retry-open"'
check "OAuth completion script has no automatic handoff" \
  page_text_has "/assets/flexible-timers/auth-complete.js" \
    'openApp\.addEventListener\("click", returnToApp\)'
check "OAuth completion script omits timed handoff" \
  page_text_lacks "/assets/flexible-timers/auth-complete.js" \
    'setTimeout\(returnToApp'
check "Privacy choices documents four distinct account actions" \
  page_text_has "/privacy-choices.html" \
    "Sign Out of XTimers.*Remove XTimers From a Device.*Delete XTimers Data.*Delete Xin Account"
check "Privacy choices documents fresh-code confirmation" \
  page_text_has "/privacy-choices.html" \
    "fresh security code sent to the Xin Account email"
check "Terms separate identity from product obligations" \
  page_text_has "/terms.html" \
    "Xin Account Identity and Security.*XTimers Product and Messaging Use"
check "Terms describe every supported Apple platform" \
  page_text_has "/terms.html" "Mac, iPhone, and iPad"
check "Terms carry the authorized N6b date" \
  page_has "/terms.html" "Effective: August 21, 2026"
check "Opt-in page includes consent wording" \
  page_text_has "/sms-opt-in.html" "I agree to receive SMS verification codes and reminder messages I schedule for myself from Flexible Timers by Xintech LLC at this phone number"
check "Opt-in page says checkbox is not pre-selected" \
  page_text_has "/sms-opt-in.html" "checkbox is not pre-selected"
check "Opt-in page names end business" \
  page_text_has "/sms-opt-in.html" "Flexible Timers by Xintech LLC"
check "Opt-in page includes message/data rates disclosure" \
  page_text_has "/sms-opt-in.html" "Standard message and data rates may apply"
check "Opt-in page says consent is not condition of purchase" \
  page_text_has "/sms-opt-in.html" "Consent is not a condition of purchase"
check "Opt-in page includes sample production message" \
  page_has "/sms-opt-in.html" "Flexible Timers reminder"
check "Opt-in page says SMS is not two-way chat" \
  page_text_has "/sms-opt-in.html" "does not provide two-way SMS chat"
check "Opt-in page documents verified account-phone reminders" \
  page_text_has "/sms-opt-in.html" "verified(, opted-in)? account phone number"
check "Opt-in page includes exact STOP response" \
  page_text_has "/sms-opt-in.html" "STOP response: You are opted out of Flexible Timers SMS\\. No more messages will be sent\\. Reply START to opt in again\\."
check "Opt-in page includes exact HELP response" \
  page_text_has "/sms-opt-in.html" "HELP response: Flexible Timers sends account verification codes and reminder SMS you schedule for yourself\\. Help: https://xintechllc\\.com/FlexibleTimers/support\\.html\\. Reply STOP to opt out\\."
check "Opt-in page includes exact START response" \
  page_text_has "/sms-opt-in.html" "START response: You have opted back in to Flexible Timers SMS messages\\. Message frequency varies\\. Reply STOP to opt out, HELP for help\\."
check "Opt-in page links support page" \
  page_has "/sms-opt-in.html" "support.html"
check "Compliance page links opt-in evidence" \
  page_has "/compliance.html" "SMS opt-in evidence page"
check "Compliance page documents verified account-phone reminders" \
  page_has "/compliance.html" "user-created timer/reminder SMS"
check "Compliance page says third-party messaging is disabled" \
  page_text_has "/compliance.html" "Third-party recipient messaging is not enabled"
check "Compliance page says SMS is not two-way chat" \
  page_has "/compliance.html" "not a two-way chat"
check "Compliance page links support page" \
  page_has "/compliance.html" "xintechllc.com/FlexibleTimers/support.html"
check "Support page includes contact path" \
  page_has "/support.html" "mailto:admin@xintechllc.com"
check "Support page documents SMS opt-out and help" \
  page_text_has "/support.html" "Reply STOP to opt out"
check "Support page says SMS is not two-way chat" \
  page_text_has "/support.html" "not a two-way chat service"
check "Support page documents verified account-phone SMS" \
  page_text_has "/support.html" "own verified(, opted-in)? account phone number"
check "Support page documents account email scope" \
  page_has "/support.html" "own Xin Account email address"
check "Support separates identity, product, and messaging help" \
  page_text_has "/support.html" \
    "Xin Account Identity and Recovery.*XTimers Product and Data Support.*XTimers Messaging Help"
check "Sitemap includes support page" \
  page_has "/sitemap.xml" "support.html"
check "Sitemap includes Terms page" \
  page_has "/sitemap.xml" "terms.html"
check "Sitemap includes Privacy page" \
  page_has "/sitemap.xml" "privacy.html"
check "Sitemap includes Privacy Choices page" \
  page_has "/sitemap.xml" "privacy-choices.html"
check "Sitemap includes SMS Terms page" \
  page_has "/sitemap.xml" "sms-terms.html"
check "Sitemap includes SMS opt-in page" \
  page_has "/sitemap.xml" "sms-opt-in.html"
check "Sitemap includes compliance page" \
  page_has "/sitemap.xml" "compliance.html"

if [[ "$failures" -gt 0 ]]; then
  echo
  echo "$failures check(s) failed." >&2
  exit 1
fi

echo
echo "All public compliance page checks passed."
