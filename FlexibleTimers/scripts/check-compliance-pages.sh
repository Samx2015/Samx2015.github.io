#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://xintechllc.com/FlexibleTimers}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

failures=0

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 2
  fi
}

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
  local output="$TMP_DIR/${path//\\//_}"
  if [[ "$path" == "/" ]]; then
    output="$TMP_DIR/index"
  fi
  curl -fsSL "$BASE_URL$path" -o "$output"
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

url_ok() {
  local path="$1"
  curl -fsSIL "$BASE_URL$path" >/dev/null
}

content_type_has() {
  local path="$1"
  local pattern="$2"
  curl -fsSIL "$BASE_URL$path" | grep -Eqi "^content-type: $pattern"
}

require_command curl
require_command grep

echo "Checking Flexible Timers public compliance pages"
echo "Base URL: $BASE_URL"
echo

check "Homepage is reachable" url_ok "/"
check "Support page is reachable" url_ok "/support.html"
check "Terms page is reachable" url_ok "/terms.html"
check "Privacy page is reachable" url_ok "/privacy.html"
check "SMS Terms page is reachable" url_ok "/sms-terms.html"
check "SMS opt-in evidence page is reachable" url_ok "/sms-opt-in.html"
check "Compliance page is reachable" url_ok "/compliance.html"
check "SMS consent screenshot evidence is reachable" url_ok "/assets/sms-consent.png"
check "SMS consent screenshot is PNG" \
  content_type_has "/assets/sms-consent.png" "image/png"
check "Robots file is reachable" url_ok "/robots.txt"
check "Sitemap is reachable" url_ok "/sitemap.xml"

check "Homepage describes account email reporting" \
  page_has "/" "account email"
check "Homepage names operator" \
  page_has "/" "Operated by Xintech LLC"
check "Homepage describes Apple platforms" \
  page_text_has "/" "Mac, iPhone, and iPad"
check "Homepage links support page" \
  page_has "/" "href=\"support.html\""
check "Homepage links privacy page" \
  page_has "/" "href=\"privacy.html\""
check "Homepage links SMS Terms page" \
  page_has "/" "href=\"sms-terms.html\""
check "Homepage describes personal reminders" \
  page_text_has "/" "Personal reminders.*verified phone"
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
  page_has "/sms-terms.html" "xintechllc.com/support.html"
check "SMS Terms says no marketing texts" \
  page_text_has "/sms-terms.html" "does not send marketing text messages"
check "SMS Terms says SMS is not two-way chat" \
  page_text_has "/sms-terms.html" "not a two-way chat"
check "SMS Terms says consent is not required for purchase" \
  page_has "/sms-terms.html" "Consent is not a condition of purchase"
check "SMS Terms includes exact STOP response" \
  page_text_has "/sms-terms.html" "You are opted out of Flexible Timers SMS\\. No more messages will be sent\\. Reply START to opt in again\\."
check "SMS Terms includes exact HELP response" \
  page_text_has "/sms-terms.html" "Flexible Timers sends account verification codes and reminder SMS you schedule for yourself\\. Help: https://xintechllc\\.com/support\\.html\\. Reply STOP to opt out\\."
check "SMS Terms includes exact START response" \
  page_text_has "/sms-terms.html" "You have opted back in to Flexible Timers SMS messages\\. Message frequency varies\\. Reply STOP to opt out, HELP for help\\."
check "Privacy says SMS opt-in data is not sold" \
  page_has "/privacy.html" "does not sell SMS opt-in data"
check "Privacy says SMS opt-in data is not shared for marketing" \
  page_text_has "/privacy.html" "does not share SMS opt-in data"
check "Privacy links support page" \
  page_has "/privacy.html" "xintechllc.com/support.html"
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
  page_text_has "/sms-opt-in.html" "HELP response: Flexible Timers sends account verification codes and reminder SMS you schedule for yourself\\. Help: https://xintechllc\\.com/support\\.html\\. Reply STOP to opt out\\."
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
  page_has "/compliance.html" "xintechllc.com/support.html"
check "Support page includes contact path" \
  page_has "/support.html" "mailto:admin@xintechllc.com"
check "Support page documents SMS opt-out and help" \
  page_text_has "/support.html" "Reply STOP to opt out"
check "Support page says SMS is not two-way chat" \
  page_text_has "/support.html" "not a two-way chat service"
check "Support page documents verified account-phone SMS" \
  page_text_has "/support.html" "own verified(, opted-in)? account phone number"
check "Support page documents account email scope" \
  page_has "/support.html" "own account email address"
check "Sitemap includes support page" \
  page_has "/sitemap.xml" "support.html"
check "Sitemap includes Terms page" \
  page_has "/sitemap.xml" "terms.html"
check "Sitemap includes Privacy page" \
  page_has "/sitemap.xml" "privacy.html"
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
