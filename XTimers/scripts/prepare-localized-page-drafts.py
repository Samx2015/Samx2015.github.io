#!/usr/bin/env python3
"""Extract website copy and materialize unreviewed localized page drafts.

The script intentionally keeps translations in a separate .strings package so
the source checksum and page generation can be reviewed independently. It does
not publish the website.
"""

from __future__ import annotations

import argparse
from html import escape as html_escape
import hashlib
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
SOURCE_PAGES = (
    "index.html",
    "support.html",
    "terms.html",
    "privacy.html",
    "privacy-choices.html",
    "extension-privacy.html",
    "sms-terms.html",
    "sms-opt-in.html",
)
LEGACY_IMPORT_PAGES = (
    "index.html",
    "support.html",
    "privacy.html",
    "sms-terms.html",
    "sms-opt-in.html",
)
TRANSLATION_NOTE = (
    "This translation is provided for convenience. The English version is authoritative."
)
ALARM_UI_TERMS = (
    "Rings On",
    "This Device",
    "Scheduled",
    "Pending Apply",
    "Pending Cancellation",
    "Needs Permission",
    "Unavailable",
    "Failed",
    "Sync Pending",
)
ALARM_MANAGEMENT_HEADING = "Manage Alarms and Rings On"
ALARM_TERM_FALLBACK_MARKER = "⟦XTIMERS-TERM-FALLBACK⟧"


def embedded_alarm_term(value: str) -> str:
    return value.strip().rstrip(".!?。！？।؛،").strip()
# Source-sentence keyed corrections from semantic review. These remain separate
# from the machine-draft cache so a later delta merge cannot silently restore a
# known mistranslation inside a larger whole-block catalog value.
REVIEWED_TRANSLATION_CORRECTIONS = {
    "bn": {
        "See the opt-in evidence page at "
        "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@.":
            "অপ্ট-ইন সম্মতির প্রমাণ পৃষ্ঠা "
            "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@-এ দেখুন।",
        "Reply HELP for help. You can also contact XTimers support at "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "সাহায্যের জন্য HELP লিখে উত্তর দিন। এছাড়াও "
            "%1$@xintechllc.com/XTimers/support.html%2$@-এ XTimers সহায়তার "
            "সঙ্গে যোগাযোগ করতে পারেন।",
        "You can also contact XTimers support at "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "এছাড়াও %1$@xintechllc.com/XTimers/support.html%2$@-এ XTimers "
            "সহায়তার সঙ্গে যোগাযোগ করতে পারেন।",
        "For a privacy question or request that cannot be completed in the app, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "অ্যাপে সম্পন্ন করা যায় না এমন গোপনীয়তা-সংক্রান্ত প্রশ্ন বা অনুরোধের "
            "জন্য, %1$@xintechllc.com/XTimers/support.html%2$@ দেখুন।",
        "For questions or requests, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "প্রশ্ন বা অনুরোধের জন্য, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ দেখুন।",
        "For support, see %1$@xintechllc.com/XTimers/support.html%2$@.":
            "সহায়তার জন্য, %1$@xintechllc.com/XTimers/support.html%2$@ দেখুন।",
        "These terms govern the XTimers services operated by Xintech LLC.":
            "এই শর্তাবলি Xintech LLC দ্বারা পরিচালিত XTimers পরিষেবাগুলো নিয়ন্ত্রণ করে।",
        "After a signed-in user gives explicit consent, XTimers by Xintech LLC may\n"
        "      attempt to send a setup verification code to the user-entered proposed\n"
        "      account phone number.":
            "সাইন-ইন করা ব্যবহারকারী স্পষ্ট সম্মতি দেওয়ার পরে, Xintech LLC দ্বারা "
            "পরিচালিত XTimers ব্যবহারকারীর দেওয়া প্রস্তাবিত অ্যাকাউন্ট ফোন নম্বরে "
            "একটি সেটআপ যাচাইকরণ কোড পাঠানোর চেষ্টা করতে পারে।",
        "Reply STOP to opt out of SMS messages.":
            "SMS বার্তা থেকে অপ্ট আউট করতে STOP লিখে উত্তর দিন।",
        "Reply HELP for help.": "সাহায্যের জন্য HELP লিখে উত্তর দিন।",
        "START or YES\n"
        "      may opt that number back in after consent in the app.":
            "অ্যাপে সম্মতি দেওয়ার পরে START বা YES লিখে উত্তর দিয়ে নম্বরটি আবার "
            "অপ্ট ইন করা যেতে পারে।",
        "SMS is not a two-way chat\n"
        "      service.":
            "SMS কোনো দ্বিমুখী চ্যাট পরিষেবা নয়।",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "আমি এই ফোন নম্বরে Xintech LLC দ্বারা পরিচালিত XTimers থেকে SMS "
            "যাচাইকরণ কোড এবং নিজের জন্য নির্ধারিত অনুস্মারক বার্তা পেতে সম্মত।",
        "I agree to receive SMS verification codes and reminder messages from "
        "XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "আমি এই ফোন নম্বরে Xintech LLC দ্বারা পরিচালিত XTimers থেকে SMS "
            "যাচাইকরণ কোড এবং নিজের জন্য নির্ধারিত অনুস্মারক বার্তা পেতে সম্মত।",
        "%1$@Learn how the account layers work.%2$@":
            "%1$@অ্যাকাউন্টের স্তরগুলো কীভাবে কাজ করে তা জানুন।%2$@",
        "%1$@Read the Privacy Policy for retention details.%2$@":
            "%1$@ধরে রাখার বিস্তারিত জানতে গোপনীয়তা নীতি পড়ুন।%2$@",
        "%2$@main Privacy Policy%3$@":
            "%2$@প্রধান গোপনীয়তা নীতি%3$@",
        "%3$@Privacy Policy%4$@": "%3$@গোপনীয়তা নীতি%4$@",
        "%1$@Privacy Policy%2$@": "%1$@গোপনীয়তা নীতি%2$@",
        "%3$@Privacy Choices%4$@": "%3$@গোপনীয়তার পছন্দসমূহ%4$@",
        "Effective: %1$@August 23, 2026%2$@.":
            "কার্যকর হওয়ার তারিখ: %1$@২৩ আগস্ট ২০২৬%2$@।",
        "Last updated: %1$@August 23, 2026%2$@.":
            "সর্বশেষ হালনাগাদ: %1$@২৩ আগস্ট ২০২৬%2$@।",
        "XTimers by Xintech LLC SMS Opt-In Evidence":
            "Xintech LLC দ্বারা পরিচালিত XTimers-এর SMS অপ্ট-ইন সম্মতির প্রমাণ",
        "XTimers by Xintech LLC SMS Terms":
            "Xintech LLC দ্বারা পরিচালিত XTimers-এর SMS শর্তাবলি",
        "See the %1$@Terms%2$@, %3$@Privacy Policy%4$@, and "
        "%5$@SMS Terms%6$@.":
            "%1$@শর্তাবলি%2$@, %3$@গোপনীয়তা নীতি%4$@ এবং %5$@SMS "
            "শর্তাবলি%6$@ দেখুন।",
        "See the XTimers Privacy Policy at "
        "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@.":
            "XTimers গোপনীয়তা নীতি দেখুন: "
            "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@।",
    },
    "es": {
        "%1$@Learn how the account layers work.%2$@":
            "%1$@Aprenda cómo funcionan las capas de la cuenta.%2$@",
    },
    "fr": {
        "%1$@Learn how the account layers work.%2$@":
            "%1$@Découvrez comment fonctionnent les couches du compte.%2$@",
        "After successful verification\n"
        "      and opt-in, XTimers may attempt user-created timer/reminder SMS only to\n"
        "      that same phone number and only when the user schedules them for\n"
        "      themselves.":
            "Après une vérification réussie et l’adhésion, XTimers peut tenter "
            "d’envoyer des SMS de minuteur ou de rappel créés par l’utilisateur "
            "uniquement à ce même numéro de téléphone et uniquement lorsque "
            "l’utilisateur les programme pour lui-même.",
    },
    "gu": {
        "These terms govern the XTimers services operated by Xintech LLC.":
            "આ શરતો Xintech LLC દ્વારા સંચાલિત XTimers સેવાઓને નિયંત્રિત કરે છે.",
        "After a signed-in user gives explicit consent, XTimers by Xintech LLC may\n"
        "      attempt to send a setup verification code to the user-entered proposed\n"
        "      account phone number.":
            "સાઇન ઇન કરેલા વપરાશકર્તા સ્પષ્ટ સંમતિ આપે પછી, Xintech LLC દ્વારા "
            "સંચાલિત XTimers વપરાશકર્તાએ દાખલ કરેલા પ્રસ્તાવિત ખાતા ફોન નંબર પર "
            "સેટઅપ ચકાસણી કોડ મોકલવાનો પ્રયાસ કરી શકે છે.",
        "Reply STOP to opt out of SMS messages.":
            "SMS સંદેશાઓમાંથી ઓપ્ટ આઉટ થવા માટે STOP લખીને જવાબ આપો.",
        "Reply HELP for help.": "મદદ માટે HELP લખીને જવાબ આપો.",
        "START or YES\n"
        "      may opt that number back in after consent in the app.":
            "એપમાં સંમતિ આપ્યા પછી START અથવા YES લખીને જવાબ આપી તે નંબરને ફરી "
            "ઓપ્ટ ઇન કરી શકાય છે.",
        "SMS is not a two-way chat\n"
        "      service.": "SMS દ્વિમાર્ગી ચેટ સેવા નથી.",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "હું આ ફોન નંબર પર Xintech LLC દ્વારા સંચાલિત XTimers તરફથી SMS "
            "ચકાસણી કોડ અને મેં મારા માટે શેડ્યૂલ કરેલા રીમાઇન્ડર સંદેશાઓ મેળવવા "
            "માટે સંમત છું.",
        "I agree to receive SMS verification codes and reminder messages from "
        "XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "હું આ ફોન નંબર પર Xintech LLC દ્વારા સંચાલિત XTimers તરફથી SMS "
            "ચકાસણી કોડ અને મેં મારા માટે શેડ્યૂલ કરેલા રીમાઇન્ડર સંદેશાઓ મેળવવા "
            "માટે સંમત છું.",
        "The end business shown\n"
        "      to users is XTimers by Xintech LLC.":
            "વપરાશકર્તાઓને દર્શાવવામાં આવતું અંતિમ વ્યવસાય Xintech LLC દ્વારા "
            "સંચાલિત XTimers છે.",
        "%1$@Learn how the account layers work.%2$@":
            "%1$@ખાતાના સ્તરો કેવી રીતે કાર્ય કરે છે તે જાણો.%2$@",
        "%1$@Read the Privacy Policy for retention details.%2$@":
            "%1$@જાળવણીની વિગતો માટે ગોપનીયતા નીતિ વાંચો.%2$@",
        "%2$@main Privacy Policy%3$@":
            "%2$@મુખ્ય ગોપનીયતા નીતિ%3$@",
        "See the %1$@Terms%2$@, %3$@Privacy Policy%4$@, and "
        "%5$@SMS Terms%6$@.":
            "%1$@શરતો%2$@, %3$@ગોપનીયતા નીતિ%4$@ અને %5$@SMS શરતો%6$@ જુઓ.",
        "%3$@Privacy Policy%4$@": "%3$@ગોપનીયતા નીતિ%4$@",
        "%1$@Privacy Policy%2$@": "%1$@ગોપનીયતા નીતિ%2$@",
        "%3$@Privacy Choices%4$@": "%3$@ગોપનીયતા પસંદગીઓ%4$@",
        "Effective: %1$@August 23, 2026%2$@.":
            "અમલ તારીખ: %1$@23 ઑગસ્ટ 2026%2$@.",
        "Last updated: %1$@August 23, 2026%2$@.":
            "છેલ્લે અપડેટ કર્યું: %1$@23 ઑગસ્ટ 2026%2$@.",
        "XTimers by Xintech LLC SMS Opt-In Evidence":
            "Xintech LLC દ્વારા સંચાલિત XTimersના SMS ઓપ્ટ-ઇન સંમતિનો પુરાવો",
        "XTimers by Xintech LLC Privacy Policy":
            "Xintech LLC દ્વારા સંચાલિત XTimersની ગોપનીયતા નીતિ",
        "XTimers by Xintech LLC SMS Terms":
            "Xintech LLC દ્વારા સંચાલિત XTimersની SMS શરતો",
    },
    "he": {
        "%1$@Learn how the account layers work.%2$@":
            "%1$@למד כיצד פועלות שכבות החשבון.%2$@",
        "A Xin\n      Account is the shared identity layer":
            "Xin Account הוא",
        "as explained in the %2$@main Privacy Policy%3$@.":
            "כפי שמוסבר ב-%2$@מדיניות הפרטיות הראשית%3$@.",
    },
    "hi": {
        "A Xin Account can authorize access to XTimers and other connected products\n"
        "      listed in the account controls.":
            "एक Xin Account, XTimers और खाता नियंत्रण में सूचीबद्ध अन्य कनेक्टेड "
            "उत्पादों तक पहुँच को अधिकृत कर सकता है।",
        "Deleting only XTimers data leaves the Xin Account and other connected\n"
        "      products available.":
            "केवल XTimers डेटा हटाने पर Xin Account और अन्य कनेक्टेड उत्पाद उपलब्ध "
            "रहते हैं।",
        "XTimers does not send marketing SMS and does not allow SMS to arbitrary "
        "third-party recipients.":
            "XTimers मार्केटिंग SMS नहीं भेजता और मनमाने तृतीय-पक्ष प्राप्तकर्ताओं "
            "को SMS भेजने की अनुमति नहीं देता।",
        "SMS is not a two-way chat\n"
        "      service.":
            "SMS दो-तरफ़ा चैट सेवा नहीं है।",
        "After a signed-in user gives explicit consent, XTimers may attempt to "
        "send a setup verification code to the user-entered proposed account "
        "phone number.":
            "साइन-इन किया हुआ उपयोगकर्ता स्पष्ट सहमति देने के बाद, XTimers "
            "उपयोगकर्ता द्वारा दर्ज किए गए प्रस्तावित खाता फ़ोन नंबर पर सेटअप "
            "सत्यापन कोड भेजने का प्रयास कर सकता है।",
        "User-created reminder SMS may be attempted only after successful "
        "verification and opt-in, and only to that same phone number.":
            "उपयोगकर्ता द्वारा बनाया गया रिमाइंडर SMS केवल सफल सत्यापन और ऑप्ट-इन "
            "के बाद, और केवल उसी फ़ोन नंबर पर भेजने का प्रयास किया जा सकता है।",
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS का उपयोग %1$@SMS शर्तों%2$@ और %3$@गोपनीयता नीति%4$@ द्वारा भी "
            "नियंत्रित होता है।",
        "For a privacy question or request that cannot be completed in the app, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "ऐसे गोपनीयता प्रश्न या अनुरोध के लिए जिसे ऐप में पूरा नहीं किया जा "
            "सकता, %1$@xintechllc.com/XTimers/support.html%2$@ देखें।",
        "For questions or requests, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "प्रश्नों या अनुरोधों के लिए, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ देखें।",
        "For support, see %1$@xintechllc.com/XTimers/support.html%2$@.":
            "सहायता के लिए, %1$@xintechllc.com/XTimers/support.html%2$@ देखें।",
        "In XTimers account controls, choose Delete XTimers Data and confirm with "
        "the fresh security code sent to the Xin Account email.":
            "XTimers खाता नियंत्रणों में, XTimers डेटा हटाएँ चुनें और Xin Account "
            "ईमेल पर भेजे गए नए सुरक्षा कोड से पुष्टि करें।",
        "This permanently deletes the selected XTimers account's data, including "
        "active timers, alarms, session and task history, device-targeting and "
        "scheduling-status records, snapshots, custom sounds, Background Library "
        "content, feedback, reminders, messages, published reports and report links, "
        "SMS configuration, and push-registration data, and removes its local XTimers "
        "data from that device.":
            "यह चुने गए XTimers खाते के डेटा को स्थायी रूप से हटा देता है, जिसमें "
            "सक्रिय टाइमर, अलार्म, सत्र और कार्य इतिहास, डिवाइस-लक्ष्यीकरण और "
            "शेड्यूलिंग-स्थिति रिकॉर्ड, स्नैपशॉट, कस्टम ध्वनियाँ, Background Library "
            "सामग्री, फ़ीडबैक, रिमाइंडर, संदेश, प्रकाशित रिपोर्ट और रिपोर्ट लिंक, "
            "SMS कॉन्फ़िगरेशन और पुश-पंजीकरण डेटा शामिल हैं, और उस डिवाइस से उसका "
            "स्थानीय XTimers डेटा भी हटा देता है।",
        "XTimers may attempt reminder SMS only\n"
        "      after successful verification and opt-in, and only when the account owner\n"
        "      creates and schedules that SMS reminder for themselves.":
            "XTimers केवल सफल सत्यापन और ऑप्ट-इन के बाद, और केवल तब रिमाइंडर SMS "
            "भेजने का प्रयास कर सकता है जब खाता स्वामी अपने लिए वह SMS रिमाइंडर "
            "बनाता और शेड्यूल करता है।",
        "Users cannot send chat replies\n"
        "      or user-authored messages to XTimers by SMS.":
            "उपयोगकर्ता SMS द्वारा XTimers को चैट उत्तर या अपने लिखे संदेश नहीं "
            "भेज सकते।",
        "On iPhone and iPad, AlarmKit authorization and system scheduling are\n"
        "      handled by Apple.":
            "iPhone और iPad पर, AlarmKit की अनुमति और सिस्टम शेड्यूलिंग Apple द्वारा "
            "संभाली जाती है।",
        "On Mac, alarms require the Mac to be awake, XTimers to\n"
        "      be running, and required permissions.":
            "Mac पर, अलार्म के लिए Mac का सक्रिय रहना, XTimers का चलना और आवश्यक "
            "अनुमतियाँ होना ज़रूरी है।",
        "SMS Keyword Instructions":
            "SMS कीवर्ड निर्देश",
        "START or YES may opt a previously opted-out phone number back in after the\n"
        "      user has already provided app consent for that account phone.":
            "उपयोगकर्ता द्वारा उस खाता फ़ोन के लिए ऐप में पहले ही सहमति दिए जाने "
            "के बाद, START या YES पहले से ऑप्ट-आउट किए गए फ़ोन नंबर को फिर से "
            "ऑप्ट-इन कर सकता है।",
        "Carrier and\n"
        "      provider handling may vary; XTimers does not promise a particular\n"
        "      automated response message for any keyword.":
            "कैरियर और प्रदाता का प्रबंधन अलग-अलग हो सकता है; XTimers किसी भी "
            "कीवर्ड के लिए किसी खास स्वचालित प्रतिक्रिया संदेश का वादा नहीं करता।",
        "STOP opts the phone number out of XTimers SMS.":
            "STOP फ़ोन नंबर को XTimers SMS से ऑप्ट आउट कर देता है।",
        "HELP requests help and the\n"
        "      support page above provides another contact path.":
            "HELP मदद का अनुरोध करता है, और ऊपर दिया गया सहायता पृष्ठ संपर्क का "
            "एक अन्य माध्यम प्रदान करता है।",
        "Sample Message Formats":
            "नमूना संदेश प्रारूप",
        "See the %1$@Terms%2$@, %3$@Privacy Policy%4$@, and "
        "%5$@SMS Terms%6$@.":
            "%1$@शर्तें%2$@, %3$@गोपनीयता नीति%4$@ और %5$@SMS शर्तें%6$@ देखें।",
        "See the XTimers Privacy Policy at "
        "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@.":
            "XTimers गोपनीयता नीति "
            "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@ पर देखें।",
        "Separately maintained request logs, IP information, security records, "
        "deletion receipts, and diagnostic submissions may remain when needed for "
        "security, troubleshooting, legal compliance, fraud or abuse prevention, or "
        "service administration.":
            "अलग से रखे गए अनुरोध लॉग, IP जानकारी, सुरक्षा रिकॉर्ड, हटाने की रसीदें "
            "और निदान प्रस्तुतियाँ सुरक्षा, समस्या निवारण, कानूनी अनुपालन, "
            "धोखाधड़ी या दुरुपयोग की रोकथाम या सेवा प्रशासन के लिए आवश्यक होने पर "
            "बनी रह सकती हैं।",
        "Sign Out and Local Data":
            "साइन आउट और स्थानीय डेटा",
    },
    "hr": {
        "%1$@Learn how the account layers work.%2$@":
            "%1$@Saznajte kako funkcioniraju slojevi računa.%2$@",
    },
    "ml": {
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS ഉപയോഗം %1$@SMS നിബന്ധനകൾ%2$@, %3$@സ്വകാര്യതാ നയം%4$@ "
            "എന്നിവയ്ക്കും വിധേയമാണ്.",
        "After the phone is verified and opted in, the user may schedule reminder SMS\n"
        "        only to that same verified, opted-in account phone number.":
            "ഫോൺ സ്ഥിരീകരിച്ച് സമ്മതം നൽകിയ ശേഷം, അതേ സ്ഥിരീകരിച്ച, സമ്മതം നൽകിയ "
            "അക്കൗണ്ട് ഫോൺ നമ്പറിലേക്കു മാത്രമേ ഉപയോക്താവിന് റിമൈൻഡർ SMS "
            "ഷെഡ്യൂൾ ചെയ്യാനാകൂ.",
        "Automatic application tracking can be enabled or disabled in XTimers\n"
        "      settings.":
            "XTimers ക്രമീകരണങ്ങളിൽ സ്വയമേവയുള്ള ആപ്ലിക്കേഷൻ ട്രാക്കിംഗ് "
            "പ്രവർത്തനക്ഷമമാക്കാനോ പ്രവർത്തനരഹിതമാക്കാനോ കഴിയും.",
        "Active browser-tab web-address and title tracking is available\n"
        "      only in the separately distributed XTimers Pro edition, where browser\n"
        "      integration can also be enabled or disabled.":
            "സജീവ ബ്രൗസർ ടാബിന്റെ വെബ് വിലാസവും ശീർഷകവും ട്രാക്കുചെയ്യുന്നത് "
            "പ്രത്യേകം വിതരണം ചെയ്യുന്ന XTimers Pro പതിപ്പിൽ മാത്രമാണ് ലഭ്യം; അവിടെ "
            "ബ്രൗസർ സംയോജനവും പ്രവർത്തനക്ഷമമാക്കാനോ പ്രവർത്തനരഹിതമാക്കാനോ കഴിയും.",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "ഈ ഫോൺ നമ്പറിൽ Xintech LLC നടത്തുന്ന XTimers-ൽ നിന്ന് SMS സ്ഥിരീകരണ "
            "കോഡുകളും ഞാൻ എനിക്കായി ഷെഡ്യൂൾ ചെയ്യുന്ന റിമൈൻഡർ സന്ദേശങ്ങളും "
            "സ്വീകരിക്കാൻ ഞാൻ സമ്മതിക്കുന്നു.",
        "Standard message and data rates may apply.":
            "സാധാരണ സന്ദേശ, ഡാറ്റ നിരക്കുകൾ ബാധകമായേക്കാം.",
        "Reply STOP to opt out and HELP\n"
        "      for help.":
            "ഒഴിവാകാൻ STOP എന്നും സഹായത്തിനായി HELP എന്നും മറുപടി നൽകുക.",
        "Message frequency varies.":
            "സന്ദേശങ്ങളുടെ ആവൃത്തി വ്യത്യാസപ്പെടുന്നു.",
        "XTimers will not send\n"
        "      marketing texts.":
            "XTimers വിപണന സന്ദേശങ്ങൾ അയയ്ക്കില്ല.",
        "Consent is not a condition of purchase.":
            "സമ്മതം വാങ്ങലിന്റെ നിബന്ധനയല്ല.",
        "This permanently deletes the selected XTimers account's data, including "
        "active timers, alarms, session and task history, device-targeting and "
        "scheduling-status records, snapshots, custom sounds, Background Library "
        "content, feedback, reminders, messages, published reports and report links, "
        "SMS configuration, and push-registration data, and removes its local XTimers "
        "data from that device.":
            "ഇത് തിരഞ്ഞെടുത്ത XTimers അക്കൗണ്ടിന്റെ ഡാറ്റ ശാശ്വതമായി ഇല്ലാതാക്കുന്നു; "
            "സജീവ ടൈമറുകൾ, അലാറങ്ങൾ, സെഷൻ, ടാസ്ക് ചരിത്രം, ഉപകരണ-ലക്ഷ്യമിടൽ, "
            "ഷെഡ്യൂളിംഗ്-നില രേഖകൾ, സ്നാപ്പ്ഷോട്ടുകൾ, ഇഷ്ടാനുസൃത ശബ്ദങ്ങൾ, "
            "Background Library ഉള്ളടക്കം, ഫീഡ്ബാക്ക്, റിമൈൻഡറുകൾ, സന്ദേശങ്ങൾ, "
            "പ്രസിദ്ധീകരിച്ച റിപ്പോർട്ടുകളും റിപ്പോർട്ട് ലിങ്കുകളും, SMS ക്രമീകരണം, "
            "പുഷ്-രജിസ്ട്രേഷൻ ഡാറ്റ എന്നിവ ഉൾപ്പെടെ; കൂടാതെ ആ ഉപകരണത്തിൽ നിന്നുള്ള "
            "അതിന്റെ പ്രാദേശിക XTimers ഡാറ്റയും നീക്കം ചെയ്യുന്നു.",
        "After explicit consent, XTimers may attempt to\n"
        "      send one setup verification message when a user requests verification of\n"
        "      the proposed account phone number.":
            "വ്യക്തമായ സമ്മതത്തിന് ശേഷം, നിർദ്ദേശിച്ച അക്കൗണ്ട് ഫോൺ നമ്പർ "
            "സ്ഥിരീകരിക്കാൻ ഉപയോക്താവ് അഭ്യർത്ഥിക്കുമ്പോൾ XTimers ഒരു സജ്ജീകരണ "
            "സ്ഥിരീകരണ സന്ദേശം അയയ്ക്കാൻ ശ്രമിച്ചേക്കാം.",
    },
    "mr": {
        "STOP opts the phone number out of XTimers SMS.":
            "STOP हा फोन नंबर XTimers SMS मधून वगळतो.",
        "See the XTimers Privacy Policy at "
        "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@.":
            "XTimers गोपनीयता धोरण "
            "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@ येथे पहा.",
        "For a privacy question or request that cannot be completed in the app, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "अॅपमध्ये पूर्ण करता न येणाऱ्या गोपनीयता प्रश्नासाठी किंवा विनंतीसाठी, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ पहा.",
        "For questions or requests, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "प्रश्न किंवा विनंत्यांसाठी, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ पहा.",
        "For support, see %1$@xintechllc.com/XTimers/support.html%2$@.":
            "सहाय्यासाठी, %1$@xintechllc.com/XTimers/support.html%2$@ पहा.",
        "You can also contact XTimers support at "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "तुम्ही %1$@xintechllc.com/XTimers/support.html%2$@ येथे "
            "XTimers सहाय्याशी देखील संपर्क साधू शकता.",
        "See the opt-in evidence page at "
        "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@.":
            "निवड-संमतीचा पुरावा "
            "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@ या पृष्ठावर पहा.",
    },
    "or": {
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS ବ୍ୟବହାର %1$@SMS ସର୍ତ୍ତାବଳୀ%2$@ ଏବଂ %3$@ଗୋପନୀୟତା ନୀତି%4$@ "
            "ଦ୍ୱାରା ମଧ୍ୟ ପରିଚାଳିତ ହୁଏ।",
        "After the phone is verified and opted in, the user may schedule reminder SMS\n"
        "        only to that same verified, opted-in account phone number.":
            "ଫୋନ୍ ଯାଞ୍ଚ ହୋଇ ଅପ୍ଟ-ଇନ୍ କରାଯିବା ପରେ, ବ୍ୟବହାରକାରୀ କେବଳ ସେହି "
            "ଯାଞ୍ଚ ହୋଇଥିବା ଓ ଅପ୍ଟ-ଇନ୍ କରାଯାଇଥିବା ଆକାଉଣ୍ଟ ଫୋନ୍ ନମ୍ବରକୁ "
            "ରିମାଇଣ୍ଡର SMS ନିର୍ଦ୍ଧାରଣ କରିପାରିବେ।",
        "Authenticate Xin Accounts and authorize connected XTimers accounts.":
            "Xin Account ଖାତାଗୁଡ଼ିକୁ ପ୍ରମାଣିତ କରନ୍ତୁ ଏବଂ ସଂଯୁକ୍ତ XTimers "
            "ଆକାଉଣ୍ଟଗୁଡ଼ିକୁ ଅନୁମୋଦନ କରନ୍ତୁ।",
        "Automatic application tracking can be enabled or disabled in XTimers\n"
        "      settings.":
            "XTimers ସେଟିଂସ୍‌ରେ ସ୍ୱୟଂଚାଳିତ ଆପ୍ଲିକେସନ୍ ଟ୍ରାକିଂକୁ ସକ୍ଷମ "
            "କିମ୍ବା ଅକ୍ଷମ କରାଯାଇପାରେ।",
    },
    "ru": {
        "%1$@Learn how the account layers work.%2$@":
            "%1$@Узнайте, как работают уровни учётной записи.%2$@",
    },
    "ja": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account は",
        "I agree to receive SMS verification codes and reminder messages":
            "私は、この電話番号で、Xintech LLC が提供する XTimers から SMS 確認コードと、"
            "自分自身のために予定したリマインダーメッセージを受け取ることに同意します。",
        "XTimers by Xintech LLC Privacy Policy":
            "Xintech LLC が提供する XTimers のプライバシーポリシー",
        "XTimers makes a\n"
        "      best-effort attempt to cancel alarms scheduled by that installation before\n"
        "      removing its local account state.":
            "XTimers は、ローカルのアカウント状態を削除する前に、そのインストールによって"
            "スケジュールされたアラームのキャンセルを最大限試みます。",
        "%1$@Read the Privacy Policy for retention details.%2$@":
            "%1$@保持の詳細についてはプライバシーポリシーをご覧ください。%2$@",
    },
    "ko": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account는",
        "I agree to receive SMS verification codes and reminder messages":
            "저는 이 전화번호로 Xintech LLC가 제공하는 XTimers의 SMS 인증 코드와 제가 직접 "
            "예약한 알림 메시지를 받는 데 동의합니다.",
        "Last updated: %1$@August 23, 2026%2$@.":
            "최종 업데이트: %1$@2026년 8월 23일%2$@.",
        "XTimers by Xintech LLC SMS Opt-In Evidence":
            "Xintech LLC가 제공하는 XTimers SMS 옵트인 증거",
        "XTimers by Xintech LLC Privacy Policy":
            "Xintech LLC가 제공하는 XTimers 개인정보 보호정책",
        "XTimers by Xintech LLC SMS Terms":
            "Xintech LLC가 제공하는 XTimers SMS 약관",
        "XTimers makes a\n"
        "      best-effort attempt to cancel alarms scheduled by that installation before\n"
        "      removing its local account state.":
            "XTimers는 로컬 계정 상태를 제거하기 전에 해당 설치에서 예약된 알람을 "
            "취소하기 위해 최선을 다합니다.",
    },
    "ar": {
        "A Xin\n      Account is the shared identity layer":
            "يُعد Xin Account",
        "push-registration data": "بيانات التسجيل للإشعارات الفورية",
        "Your Xin Account identifies you and authorizes each connected XTimers account.":
            "يحدد Xin Account هويتك ويخوّل كل حساب XTimers متصل.",
    },
    "cs": {
        "No Emergency Use": "Nepoužívat v nouzových situacích",
        "The Xin Account, shared sign-in identity, and any other connected "
        "products remain available.":
            "Účet Xin Account, sdílená přihlašovací identita a všechny ostatní "
            "propojené produkty zůstávají k dispozici.",
    },
    "nb": {
        "The Xin Account, shared sign-in identity, and any other connected "
        "products remain available.":
            "Xin Account, den delte påloggingsidentiteten og alle andre tilknyttede "
            "produkter forblir tilgjengelige.",
    },
    "pa": {
        "This permanently deletes the selected XTimers account's data, including "
        "active timers, alarms, session and task history, device-targeting and "
        "scheduling-status records, snapshots, custom sounds, Background Library "
        "content, feedback, reminders, messages, published reports and report links, "
        "SMS configuration, and push-registration data, and removes its local XTimers "
        "data from that device.":
            "ਇਹ ਚੁਣੇ ਹੋਏ XTimers ਖਾਤੇ ਦਾ ਡਾਟਾ ਸਥਾਈ ਤੌਰ 'ਤੇ ਮਿਟਾ ਦਿੰਦਾ ਹੈ, ਜਿਸ "
            "ਵਿੱਚ ਸਰਗਰਮ ਟਾਈਮਰ, ਅਲਾਰਮ, ਸੈਸ਼ਨ ਅਤੇ ਟਾਸਕ ਇਤਿਹਾਸ, ਡਿਵਾਈਸ-ਟਾਰਗੇਟਿੰਗ "
            "ਅਤੇ ਸ਼ਡਿਊਲਿੰਗ-ਸਥਿਤੀ ਰਿਕਾਰਡ, ਸਨੈਪਸ਼ਾਟ, ਕਸਟਮ ਧੁਨੀਆਂ, ਪਿਛੋਕੜ "
            "ਲਾਇਬ੍ਰੇਰੀ ਸਮੱਗਰੀ, ਫੀਡਬੈਕ, ਰੀਮਾਈਂਡਰ, ਸੁਨੇਹੇ, ਪ੍ਰਕਾਸ਼ਿਤ ਰਿਪੋਰਟਾਂ ਅਤੇ "
            "ਰਿਪੋਰਟ ਲਿੰਕ, SMS ਸੰਰਚਨਾ ਅਤੇ ਪੁਸ਼-ਰਜਿਸਟ੍ਰੇਸ਼ਨ ਡਾਟਾ ਸ਼ਾਮਲ ਹਨ, ਅਤੇ ਉਸ "
            "ਡਿਵਾਈਸ ਤੋਂ ਇਸ ਦਾ ਸਥਾਨਕ XTimers ਡਾਟਾ ਹਟਾ ਦਿੰਦਾ ਹੈ।",
        "For a privacy question or request that cannot be completed in the app, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "ਐਪ ਵਿੱਚ ਪੂਰਾ ਨਾ ਹੋ ਸਕਣ ਵਾਲੇ ਗੋਪਨੀਯਤਾ ਸਵਾਲ ਜਾਂ ਬੇਨਤੀ ਲਈ, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ ਵੇਖੋ।",
        "For questions or requests, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "ਸਵਾਲਾਂ ਜਾਂ ਬੇਨਤੀਆਂ ਲਈ, "
            "%1$@xintechllc.com/XTimers/support.html%2$@ ਵੇਖੋ।",
        "For support, see %1$@xintechllc.com/XTimers/support.html%2$@.":
            "ਸਹਾਇਤਾ ਲਈ, %1$@xintechllc.com/XTimers/support.html%2$@ ਵੇਖੋ।",
        "See the XTimers Privacy Policy at "
        "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@.":
            "XTimers ਗੋਪਨੀਯਤਾ ਨੀਤੀ "
            "%1$@xintechllc.com/FlexibleTimers/privacy.html%2$@ ਉੱਤੇ ਵੇਖੋ।",
        "See the opt-in evidence page at "
        "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@.":
            "ਚੋਣ-ਸਹਿਮਤੀ ਦੇ ਸਬੂਤ ਦਾ ਪੰਨਾ "
            "%1$@xintechllc.com/FlexibleTimers/sms-opt-in.html%2$@ ਉੱਤੇ ਵੇਖੋ।",
        "The active-tab report is delivered only to the XTimers Pro app running on "
        "your own computer — either through the app's local native-messaging host or "
        "a loopback (%1$@) connection to the app on the same machine.":
            "ਸਰਗਰਮ ਟੈਬ ਦੀ ਰਿਪੋਰਟ ਸਿਰਫ਼ ਤੁਹਾਡੇ ਆਪਣੇ ਕੰਪਿਊਟਰ ਉੱਤੇ ਚੱਲ ਰਹੀ XTimers "
            "Pro ਐਪ ਨੂੰ ਭੇਜੀ ਜਾਂਦੀ ਹੈ—ਜਾਂ ਐਪ ਦੇ ਸਥਾਨਕ ਨੇਟਿਵ-ਮੈਸੇਜਿੰਗ ਹੋਸਟ ਰਾਹੀਂ "
            "ਜਾਂ ਉਸੇ ਮਸ਼ੀਨ ਉੱਤੇ ਐਪ ਨਾਲ ਲੂਪਬੈਕ (%1$@) ਕਨੈਕਸ਼ਨ ਰਾਹੀਂ।",
        "These terms govern the XTimers services operated by Xintech LLC.":
            "ਇਹ ਸ਼ਰਤਾਂ Xintech LLC ਦੁਆਰਾ ਚਲਾਈਆਂ ਜਾਂਦੀਆਂ XTimers ਸੇਵਾਵਾਂ ਨੂੰ "
            "ਨਿਯੰਤਰਿਤ ਕਰਦੀਆਂ ਹਨ।",
        "After a signed-in user gives explicit consent, XTimers by Xintech LLC may\n"
        "      attempt to send a setup verification code to the user-entered proposed\n"
        "      account phone number.":
            "ਸਾਈਨ-ਇਨ ਕੀਤੇ ਉਪਭੋਗਤਾ ਵੱਲੋਂ ਸਪਸ਼ਟ ਸਹਿਮਤੀ ਦੇਣ ਤੋਂ ਬਾਅਦ, Xintech LLC "
            "ਦੁਆਰਾ ਚਲਾਇਆ ਜਾਂਦਾ XTimers ਉਪਭੋਗਤਾ ਵੱਲੋਂ ਦਰਜ ਕੀਤੇ ਪ੍ਰਸਤਾਵਿਤ ਖਾਤਾ ਫ਼ੋਨ "
            "ਨੰਬਰ ਉੱਤੇ ਸੈੱਟਅੱਪ ਤਸਦੀਕ ਕੋਡ ਭੇਜਣ ਦੀ ਕੋਸ਼ਿਸ਼ ਕਰ ਸਕਦਾ ਹੈ।",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "ਮੈਂ ਇਸ ਫ਼ੋਨ ਨੰਬਰ ਉੱਤੇ Xintech LLC ਦੁਆਰਾ ਚਲਾਏ ਜਾਂਦੇ XTimers ਤੋਂ SMS "
            "ਤਸਦੀਕ ਕੋਡ ਅਤੇ ਉਹ ਰੀਮਾਈਂਡਰ ਸੁਨੇਹੇ ਪ੍ਰਾਪਤ ਕਰਨ ਲਈ ਸਹਿਮਤ ਹਾਂ ਜੋ ਮੈਂ ਆਪਣੇ ਲਈ "
            "ਨਿਰਧਾਰਤ ਕਰਦਾ/ਕਰਦੀ ਹਾਂ।",
        "The checkbox says: \"I agree to receive SMS verification codes and reminder "
        "messages from XTimers by Xintech LLC that I schedule for myself at this phone "
        "number.\" The opt-in screen also displays these SMS Terms, the Privacy Policy, "
        "standard message and data rate disclosure, STOP and HELP instructions, message "
        "frequency information, and no-marketing language.":
            "ਚੈਕਬਾਕਸ ਵਿੱਚ ਲਿਖਿਆ ਹੈ: \"ਮੈਂ ਇਸ ਫ਼ੋਨ ਨੰਬਰ ਉੱਤੇ Xintech LLC ਦੁਆਰਾ ਚਲਾਏ "
            "ਜਾਂਦੇ XTimers ਤੋਂ SMS ਤਸਦੀਕ ਕੋਡ ਅਤੇ ਉਹ ਰੀਮਾਈਂਡਰ ਸੁਨੇਹੇ ਪ੍ਰਾਪਤ ਕਰਨ ਲਈ ਸਹਿਮਤ "
            "ਹਾਂ ਜੋ ਮੈਂ ਆਪਣੇ ਲਈ ਨਿਰਧਾਰਤ ਕਰਦਾ/ਕਰਦੀ ਹਾਂ।\" ਚੋਣ ਸਕ੍ਰੀਨ ਉੱਤੇ ਇਹ SMS ਨਿਯਮ, "
            "ਗੋਪਨੀਯਤਾ ਨੀਤੀ, ਮਿਆਰੀ ਸੁਨੇਹਾ ਅਤੇ ਡਾਟਾ ਦਰ ਖੁਲਾਸਾ, STOP ਅਤੇ HELP ਹਦਾਇਤਾਂ, "
            "ਸੁਨੇਹਾ ਆਵਿਰਤੀ ਜਾਣਕਾਰੀ ਅਤੇ ਗੈਰ-ਮਾਰਕੀਟਿੰਗ ਭਾਸ਼ਾ ਵੀ ਦਿਖਾਈ ਜਾਂਦੀ ਹੈ।",
        "You may not misuse identity, recovery,\n"
        "      linked-provider, session, or connected-product features or attempt to\n"
        "      access another person's account.":
            "ਤੁਸੀਂ ਪਛਾਣ, ਰਿਕਵਰੀ, ਲਿੰਕ ਕੀਤੇ ਪ੍ਰਦਾਤਾ, ਸੈਸ਼ਨ ਜਾਂ ਜੁੜੇ ਉਤਪਾਦ ਦੀਆਂ "
            "ਵਿਸ਼ੇਸ਼ਤਾਵਾਂ ਦੀ ਦੁਰਵਰਤੋਂ ਨਹੀਂ ਕਰ ਸਕਦੇ ਅਤੇ ਨਾ ਹੀ ਕਿਸੇ ਹੋਰ ਵਿਅਕਤੀ ਦੇ ਖਾਤੇ "
            "ਤੱਕ ਪਹੁੰਚ ਕਰਨ ਦੀ ਕੋਸ਼ਿਸ਼ ਕਰ ਸਕਦੇ ਹੋ।",
        "Signing out pauses future\n"
        "      authenticated synchronization without deleting either account scope.":
            "ਸਾਈਨ ਆਊਟ ਕਰਨ ਨਾਲ ਕਿਸੇ ਵੀ ਖਾਤਾ-ਦਾਇਰੇ ਨੂੰ ਮਿਟਾਏ ਬਿਨਾਂ ਭਵਿੱਖ ਦਾ ਪ੍ਰਮਾਣਿਤ "
            "ਸਮਕਾਲੀਕਰਨ ਰੁਕ ਜਾਂਦਾ ਹੈ।",
        "%1$@Learn how the account layers work.%2$@":
            "%1$@ਜਾਣੋ ਕਿ ਖਾਤੇ ਦੀਆਂ ਪਰਤਾਂ ਕਿਵੇਂ ਕੰਮ ਕਰਦੀਆਂ ਹਨ।%2$@",
        "%1$@Read the Privacy Policy for retention details.%2$@":
            "%1$@ਰੱਖਣ ਦੇ ਵੇਰਵਿਆਂ ਲਈ ਗੋਪਨੀਯਤਾ ਨੀਤੀ ਪੜ੍ਹੋ।%2$@",
        "If the user later asks XTimers Pro to email or publish an activity report, "
        "the selected report's application names and derived website hostnames may be "
        "sent to XTimers' service for that requested action; raw web addresses and "
        "titles are not included, as explained in the %2$@main Privacy Policy%3$@.":
            "ਜੇ ਉਪਭੋਗਤਾ ਬਾਅਦ ਵਿੱਚ XTimers Pro ਨੂੰ ਕਿਸੇ ਸਰਗਰਮੀ ਰਿਪੋਰਟ ਨੂੰ ਈਮੇਲ ਜਾਂ "
            "ਪ੍ਰਕਾਸ਼ਿਤ ਕਰਨ ਲਈ ਕਹਿੰਦਾ ਹੈ, ਤਾਂ ਚੁਣੀ ਹੋਈ ਰਿਪੋਰਟ ਦੇ ਐਪਲੀਕੇਸ਼ਨ ਨਾਮ ਅਤੇ ਪ੍ਰਾਪਤ "
            "ਵੈੱਬਸਾਈਟ ਹੋਸਟਨਾਮ ਬੇਨਤੀ ਕੀਤੀ ਕਾਰਵਾਈ ਲਈ XTimers ਦੀ ਸੇਵਾ ਨੂੰ ਭੇਜੇ ਜਾ ਸਕਦੇ "
            "ਹਨ; ਕੱਚੇ ਵੈੱਬ ਪਤੇ ਅਤੇ ਸਿਰਲੇਖ ਸ਼ਾਮਲ ਨਹੀਂ ਕੀਤੇ ਜਾਂਦੇ, ਜਿਵੇਂ ਕਿ %2$@ਮੁੱਖ "
            "ਗੋਪਨੀਯਤਾ ਨੀਤੀ%3$@ ਵਿੱਚ ਦੱਸਿਆ ਗਿਆ ਹੈ।",
        "See the %1$@Terms%2$@, %3$@Privacy Policy%4$@, and %5$@SMS Terms%6$@.":
            "%1$@ਨਿਯਮ%2$@, %3$@ਗੋਪਨੀਯਤਾ ਨੀਤੀ%4$@ ਅਤੇ %5$@SMS ਨਿਯਮ%6$@ ਦੇਖੋ।",
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS ਦੀ ਵਰਤੋਂ %1$@SMS ਨਿਯਮ%2$@ ਅਤੇ %3$@ਗੋਪਨੀਯਤਾ ਨੀਤੀ%4$@ ਦੁਆਰਾ ਵੀ "
            "ਨਿਯੰਤਰਿਤ ਹੁੰਦੀ ਹੈ।",
        "Deletion and retention are described in the %1$@Privacy Policy%2$@ and "
        "%3$@Privacy Choices%4$@.":
            "ਮਿਟਾਉਣ ਅਤੇ ਰੱਖਣ ਬਾਰੇ %1$@ਗੋਪਨੀਯਤਾ ਨੀਤੀ%2$@ ਅਤੇ %3$@ਗੋਪਨੀਯਤਾ "
            "ਚੋਣਾਂ%4$@ ਵਿੱਚ ਦੱਸਿਆ ਗਿਆ ਹੈ।",
        "Effective: %1$@August 23, 2026%2$@.":
            "ਲਾਗੂ ਹੋਣ ਦੀ ਮਿਤੀ: %1$@23 ਅਗਸਤ 2026%2$@।",
        "Last updated: %1$@August 23, 2026%2$@.":
            "ਆਖਰੀ ਵਾਰ ਅੱਪਡੇਟ ਕੀਤਾ: %1$@23 ਅਗਸਤ 2026%2$@।",
        "XTimers by Xintech LLC SMS Opt-In Evidence":
            "Xintech LLC ਦੁਆਰਾ ਚਲਾਏ ਜਾਂਦੇ XTimers ਦੇ SMS ਚੋਣ-ਸਹਿਮਤੀ ਦਾ ਸਬੂਤ",
        "XTimers by Xintech LLC SMS Terms":
            "Xintech LLC ਦੁਆਰਾ ਚਲਾਏ ਜਾਂਦੇ XTimers ਦੇ SMS ਨਿਯਮ",
    },
    "pt-PT": {
        "A Xin\n"
        "      Account is the shared identity layer for XTimers and any other connected\n"
        "      products listed in the account controls; it is not an XTimers product\n"
        "      account and does not contain XTimers timers, reports, sounds, or SMS data.":
            "Uma Xin Account é a camada de identidade partilhada para XTimers e quaisquer "
            "outros produtos ligados listados nos controlos da conta; não é uma conta de "
            "produto XTimers e não contém temporizadores XTimers, relatórios, sons ou dados SMS.",
    },
    "ro": {
        "A Xin\n"
        "      Account is the shared identity layer for XTimers and any other connected\n"
        "      products listed in the account controls; it is not an XTimers product\n"
        "      account and does not contain XTimers timers, reports, sounds, or SMS data.":
            "Un Xin Account este stratul de identitate partajat pentru XTimers și orice "
            "alte produse conectate enumerate în comenzile contului; nu este un cont de "
            "produs XTimers și nu conține cronometre XTimers, rapoarte, sunete sau date SMS.",
    },
    "sk": {
        "A Xin\n"
        "      Account is the shared identity layer for XTimers and any other connected\n"
        "      products listed in the account controls; it is not an XTimers product\n"
        "      account and does not contain XTimers timers, reports, sounds, or SMS data.":
            "Xin Account je zdieľaná vrstva identity pre XTimers a všetky ďalšie pripojené "
            "produkty uvedené v ovládacích prvkoch účtu; nie je to produktový účet XTimers "
            "a neobsahuje časovače XTimers, správy, zvuky ani údaje SMS.",
    },
    "sv": {
        "The Xin Account, shared sign-in identity, and any other connected "
        "products remain available.":
            "Xin Account, den delade inloggningsidentiteten och alla andra anslutna "
            "produkter förblir tillgängliga.",
    },
    "te": {
        "These terms govern the XTimers services operated by Xintech LLC.":
            "ఈ నిబంధనలు Xintech LLC నిర్వహించే XTimers సేవలను నియంత్రిస్తాయి.",
        "A Xin\n"
        "      Account is the shared identity layer for XTimers and any other connected\n"
        "      products listed in the account controls; it is not an XTimers product\n"
        "      account and does not contain XTimers timers, reports, sounds, or SMS data.":
            "Xin Account అనేది XTimers మరియు ఖాతా నియంత్రణల్లో జాబితా చేసిన ఇతర "
            "అనుసంధానిత ఉత్పత్తుల కోసం ఉపయోగించే భాగస్వామ్య గుర్తింపు పొర; అది XTimers "
            "ఉత్పత్తి ఖాతా కాదు మరియు అందులో XTimers టైమర్లు, నివేదికలు, శబ్దాలు లేదా "
            "SMS డేటా ఉండవు.",
        "You may not misuse identity, recovery,\n"
        "      linked-provider, session, or connected-product features or attempt to\n"
        "      access another person's account.":
            "మీరు గుర్తింపు, రికవరీ, అనుసంధానిత ప్రొవైడర్, సెషన్ లేదా అనుసంధానిత "
            "ఉత్పత్తి లక్షణాలను దుర్వినియోగం చేయకూడదు లేదా మరొక వ్యక్తి ఖాతాను యాక్సెస్ "
            "చేయడానికి ప్రయత్నించకూడదు.",
        "Signing out pauses future\n"
        "      authenticated synchronization without deleting either account scope.":
            "సైన్ అవుట్ చేయడం ఏ ఖాతా పరిధినీ తొలగించకుండా భవిష్యత్తు ప్రమాణీకృత "
            "సమకాలీకరణను నిలిపివేస్తుంది.",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "ఈ ఫోన్ నంబర్‌కు Xintech LLC నిర్వహించే XTimers నుండి SMS ధృవీకరణ కోడ్‌లను "
            "మరియు నేను నా కోసం షెడ్యూల్ చేసుకున్న రిమైండర్ సందేశాలను స్వీకరించడానికి "
            "నేను అంగీకరిస్తున్నాను.",
        "The checkbox says: \"I agree to receive SMS verification codes and reminder "
        "messages from XTimers by Xintech LLC that I schedule for myself at this phone "
        "number.\" The opt-in screen also displays these SMS Terms, the Privacy Policy, "
        "standard message and data rate disclosure, STOP and HELP instructions, message "
        "frequency information, and no-marketing language.":
            "చెక్‌బాక్స్ ఇలా చెబుతుంది: \"ఈ ఫోన్ నంబర్‌కు Xintech LLC నిర్వహించే XTimers "
            "నుండి SMS ధృవీకరణ కోడ్‌లను మరియు నేను నా కోసం షెడ్యూల్ చేసుకున్న రిమైండర్ "
            "సందేశాలను స్వీకరించడానికి నేను అంగీకరిస్తున్నాను.\" ఎంపిక స్క్రీన్‌లో ఈ SMS "
            "నిబంధనలు, గోప్యతా విధానం, ప్రామాణిక సందేశం మరియు డేటా రేటు బహిర్గతం, STOP "
            "మరియు HELP సూచనలు, సందేశ పౌనఃపున్య సమాచారం మరియు మార్కెటింగ్ లేని భాష కూడా "
            "ప్రదర్శించబడతాయి.",
        "After a signed-in user gives explicit consent, XTimers by Xintech LLC may\n"
        "      attempt to send a setup verification code to the user-entered proposed\n"
        "      account phone number.":
            "సైన్-ఇన్ చేసిన వినియోగదారు స్పష్టమైన సమ్మతి ఇచ్చిన తర్వాత, Xintech LLC "
            "నిర్వహించే XTimers వినియోగదారు నమోదు చేసిన ప్రతిపాదిత ఖాతా ఫోన్ నంబర్‌కు "
            "సెటప్ ధృవీకరణ కోడ్‌ను పంపడానికి ప్రయత్నించవచ్చు.",
        "Reply STOP to opt out of SMS messages.":
            "SMS సందేశాల నుంచి వైదొలగడానికి STOP అని ప్రత్యుత్తరం ఇవ్వండి.",
        "Reply HELP for help.":
            "సహాయం కోసం HELP అని ప్రత్యుత్తరం ఇవ్వండి.",
        "START or YES\n"
        "      may opt that number back in after consent in the app.":
            "యాప్‌లో సమ్మతి ఇచ్చిన తర్వాత START లేదా YES అని ప్రత్యుత్తరం ఇవ్వడం ద్వారా "
            "ఆ నంబర్‌ను మళ్లీ నమోదు చేయవచ్చు.",
        "SMS is not a two-way chat\n      service.":
            "SMS ద్విముఖ చాట్ సేవ కాదు.",
        "%1$@Learn how the account layers work.%2$@":
            "%1$@ఖాతా పొరలు ఎలా పనిచేస్తాయో తెలుసుకోండి.%2$@",
        "%1$@Read the Privacy Policy for retention details.%2$@":
            "%1$@నిలుపుదల వివరాల కోసం గోప్యతా విధానాన్ని చదవండి.%2$@",
        "If the user later asks XTimers Pro to email or publish an activity report, "
        "the selected report's application names and derived website hostnames may be "
        "sent to XTimers' service for that requested action; raw web addresses and "
        "titles are not included, as explained in the %2$@main Privacy Policy%3$@.":
            "వినియోగదారు తర్వాత కార్యాచరణ నివేదికను ఇమెయిల్ చేయమని లేదా ప్రచురించమని "
            "XTimers Pro ను అడిగితే, ఎంచుకున్న నివేదికలోని అప్లికేషన్ పేర్లు మరియు ఉత్పన్న "
            "వెబ్‌సైట్ హోస్ట్ పేర్లు అభ్యర్థించిన చర్య కోసం XTimers సేవకు పంపబడవచ్చు; ముడి "
            "వెబ్ చిరునామాలు మరియు శీర్షికలు చేర్చబడవు, ఇది %2$@ప్రధాన గోప్యతా "
            "విధానం%3$@లో వివరించబడింది.",
        "See the %1$@Terms%2$@, %3$@Privacy Policy%4$@, and %5$@SMS Terms%6$@.":
            "%1$@నిబంధనలు%2$@, %3$@గోప్యతా విధానం%4$@ మరియు %5$@SMS "
            "నిబంధనలు%6$@ చూడండి.",
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS ఉపయోగం %1$@SMS నిబంధనలు%2$@ మరియు %3$@గోప్యతా విధానం%4$@ ద్వారా కూడా "
            "నియంత్రించబడుతుంది.",
        "Deletion and retention are described in the %1$@Privacy Policy%2$@ and "
        "%3$@Privacy Choices%4$@.":
            "తొలగింపు మరియు నిలుపుదల వివరాలు %1$@గోప్యతా విధానం%2$@ మరియు "
            "%3$@గోప్యతా ఎంపికలు%4$@లో వివరించబడ్డాయి.",
        "Effective: %1$@August 23, 2026%2$@.":
            "అమలులోకి వచ్చిన తేదీ: %1$@23 ఆగస్టు 2026%2$@.",
        "Last updated: %1$@August 23, 2026%2$@.":
            "చివరిగా నవీకరించబడింది: %1$@23 ఆగస్టు 2026%2$@.",
        "XTimers by Xintech LLC SMS Opt-In Evidence":
            "Xintech LLC నిర్వహించే XTimers SMS ఎంపిక-సమ్మతి ఆధారం",
        "XTimers by Xintech LLC Privacy Policy":
            "Xintech LLC నిర్వహించే XTimers గోప్యతా విధానం",
        "XTimers by Xintech LLC SMS Terms":
            "Xintech LLC నిర్వహించే XTimers SMS నిబంధనలు",
    },
    "ta": {
        "In XTimers account controls, choose Delete XTimers Data and confirm with "
        "the fresh security code sent to the Xin Account email.":
            "XTimers கணக்குக் கட்டுப்பாடுகளில், XTimers தரவை நீக்கு என்பதைத் "
            "தேர்ந்தெடுத்து, Xin Account மின்னஞ்சலுக்கு அனுப்பப்பட்ட புதிய "
            "பாதுகாப்புக் குறியீட்டைக் கொண்டு உறுதிப்படுத்தவும்.",
        "Separately maintained request logs, IP information, security records, "
        "deletion receipts, and diagnostic submissions may remain when needed for "
        "security, troubleshooting, legal compliance, fraud or abuse prevention, or "
        "service administration.":
            "தனித்தனியாகப் பராமரிக்கப்படும் கோரிக்கைப் பதிவுகள், IP தகவல், "
            "பாதுகாப்புப் பதிவுகள், நீக்குதல் ரசீதுகள் மற்றும் கண்டறிதல் சமர்ப்பிப்புகள் "
            "பாதுகாப்பு, சிக்கல் தீர்த்தல், சட்ட இணக்கம், மோசடி அல்லது தவறான பயன்பாட்டைத் "
            "தடுப்பது அல்லது சேவை நிர்வாகம் ஆகியவற்றிற்குத் தேவைப்படும் போது தொடர்ந்து "
            "இருக்கலாம்.",
        "If the user later asks XTimers Pro to email or publish an activity report, "
        "the selected report's application names and derived website hostnames may be "
        "sent to XTimers' service for that requested action; raw web addresses and "
        "titles are not included, as explained in the %2$@main Privacy Policy%3$@.":
            "பயனர் பின்னர் ஒரு செயல்பாட்டு அறிக்கையை மின்னஞ்சல் செய்ய அல்லது வெளியிட "
            "XTimers Pro-ஐக் கேட்டால், தேர்ந்தெடுக்கப்பட்ட அறிக்கையின் பயன்பாட்டுப் "
            "பெயர்களும் பெறப்பட்ட இணையதள ஹோஸ்ட்பெயர்களும் கோரப்பட்ட செயலுக்காக XTimers "
            "சேவைக்கு அனுப்பப்படலாம்; %2$@முதன்மை தனியுரிமைக் கொள்கை%3$@யில் "
            "விளக்கப்பட்டுள்ளபடி, மூல இணைய முகவரிகளும் தலைப்புகளும் சேர்க்கப்படாது.",
    },
    "th": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account คือ",
    },
    "tr": {
        "App Store copies are governed by\n"
        "      Apple's Standard Licensed Application End User License Agreement unless\n"
        "      a custom license agreement is presented for XTimers in the App Store or\n"
        "      App Store Connect; these terms supplement the applicable license for\n"
        "      XTimers accounts and services.":
            "App Store kopyaları, XTimers için App Store'da veya App Store Connect'te "
            "özel bir lisans sözleşmesi sunulmadıkça Apple'ın Standart Lisanslı "
            "Uygulama Son Kullanıcı Lisans Sözleşmesi'ne tabidir; bu şartlar XTimers "
            "hesapları ve hizmetleri için geçerli lisansı tamamlar.",
    },
    "uk": {
        "A Xin\n"
        "      Account is the shared identity layer for XTimers and any other connected\n"
        "      products listed in the account controls; it is not an XTimers product\n"
        "      account and does not contain XTimers timers, reports, sounds, or SMS data.":
            "Xin Account є спільним рівнем ідентифікації для XTimers та будь-яких інших "
            "підключених продуктів, зазначених у засобах керування обліковим записом; це "
            "не обліковий запис продукту XTimers і він не містить таймерів XTimers, "
            "звітів, звуків або даних SMS.",
        "App Store copies are governed by\n"
        "      Apple's Standard Licensed Application End User License Agreement unless\n"
        "      a custom license agreement is presented for XTimers in the App Store or\n"
        "      App Store Connect; these terms supplement the applicable license for\n"
        "      XTimers accounts and services.":
            "Копії App Store регулюються Стандартною ліцензійною угодою кінцевого "
            "користувача ліцензованого застосунку Apple, якщо для XTimers в App Store "
            "або App Store Connect не представлено спеціальну ліцензійну угоду; ці "
            "умови доповнюють застосовну ліцензію щодо облікових записів і послуг XTimers.",
    },
    "ur": {
        "Carrier and\n"
        "      provider handling may vary; XTimers does not promise a particular\n"
        "      automated response message for any keyword.":
            "کیریئر اور فراہم کنندہ کا طریقۂ کار مختلف ہو سکتا ہے؛ XTimers کسی بھی "
            "کلیدی لفظ کے لیے کسی مخصوص خودکار جوابی پیغام کا وعدہ نہیں کرتا۔",
        "After you send STOP,\n"
        "      XTimers will stop sending SMS messages to that phone number\n"
        "      unless you opt in again.":
            "آپ کے STOP بھیجنے کے بعد، XTimers اس فون نمبر پر SMS پیغامات بھیجنا "
            "بند کر دے گا، جب تک کہ آپ دوبارہ آپٹ اِن نہ کریں۔",
        "Signing out preserves local timers and other local data;\n"
        "      XTimers does not currently provide a separate whole-app local-data reset\n"
        "      on Mac, iPhone, or iPad.":
            "سائن آؤٹ کرنے سے مقامی ٹائمرز اور دیگر مقامی ڈیٹا برقرار رہتے ہیں؛ "
            "XTimers فی الحال Mac، iPhone یا iPad پر پوری ایپ کے مقامی ڈیٹا کو الگ "
            "سے ری سیٹ کرنے کا اختیار فراہم نہیں کرتا۔",
        "SwiftUI timers with task sets, reports, sync, custom sounds, and menu-bar "
        "status.":
            "ٹاسک سیٹس، رپورٹس، مطابقت پذیری، حسب ضرورت آوازوں اور مینو بار کی حالت "
            "کے ساتھ SwiftUI ٹائمرز۔",
        "The active-tab report is delivered only to the XTimers Pro app running on "
        "your own computer — either through the app's local native-messaging host or "
        "a loopback (%1$@) connection to the app on the same machine.":
            "فعال ٹیب کی رپورٹ صرف آپ کے اپنے کمپیوٹر پر چلنے والی XTimers Pro ایپ "
            "تک پہنچائی جاتی ہے—یا ایپ کے مقامی نیٹو میسجنگ ہوسٹ کے ذریعے، یا اسی "
            "مشین پر ایپ سے لوپ بیک (%1$@) کنکشن کے ذریعے۔",
        "After explicit consent, XTimers may attempt to\n"
        "      send one setup verification message when a user requests verification of\n"
        "      the proposed account phone number.":
            "واضح رضامندی کے بعد، جب صارف مجوزہ اکاؤنٹ فون نمبر کی تصدیق کی درخواست "
            "کرتا ہے تو XTimers ایک سیٹ اپ تصدیقی پیغام بھیجنے کی کوشش کر سکتا ہے۔",
        "XTimers may attempt reminder SMS only\n"
        "      after successful verification and opt-in, and only when the account owner\n"
        "      creates and schedules that SMS reminder for themselves.":
            "XTimers صرف کامیاب تصدیق اور آپٹ اِن کے بعد یاد دہانی کا SMS بھیجنے "
            "کی کوشش کر سکتا ہے، اور صرف اس وقت جب اکاؤنٹ کا مالک وہ SMS یاد دہانی "
            "اپنے لیے بناتا اور شیڈول کرتا ہے۔",
        "Reply STOP to opt out of SMS messages from XTimers.":
            "XTimers کے SMS پیغامات سے دستبردار ہونے کے لیے STOP کا جواب دیں۔",
        "START or YES may opt a previously opted-out phone number back in after the\n"
        "      user has already provided app consent for that account phone.":
            "صارف کی جانب سے اس اکاؤنٹ فون کے لیے ایپ میں پہلے ہی رضامندی دینے کے "
            "بعد، START یا YES پہلے آپٹ آؤٹ کیے گئے فون نمبر کو دوبارہ آپٹ اِن کر "
            "سکتا ہے۔",
        "Carrier and\n"
        "      provider handling may vary; XTimers does not promise a particular\n"
        "      automated keyword response.":
            "کیریئر اور فراہم کنندہ کی کارروائی مختلف ہو سکتی ہے؛ XTimers کسی بھی "
            "مخصوص خودکار کلیدی لفظ کے جوابی پیغام کا وعدہ نہیں کرتا۔",
        "XTimers does not accept general SMS\n"
        "      conversations.":
            "XTimers عام SMS گفتگو قبول نہیں کرتا۔",
        "Keyword Instructions": "کلیدی الفاظ کی ہدایات",
        "The Xin Account, shared sign-in identity, and any other connected products "
        "remain available.":
            "Xin Account، مشترکہ سائن اِن شناخت، اور کوئی بھی دوسری منسلک مصنوعات "
            "دستیاب رہتی ہیں۔",
        "STOP opts out, HELP requests help, and START or YES may opt a\n"
        "      previously opted-out phone number back in after app consent.":
            "STOP سے آپٹ آؤٹ ہوتا ہے، HELP سے مدد کی درخواست کی جاتی ہے، اور ایپ میں "
            "رضامندی کے بعد START یا YES پہلے آپٹ آؤٹ کیے گئے فون نمبر کو دوبارہ شامل "
            "کر سکتا ہے۔",
        "In XTimers account controls, choose Delete XTimers Data and confirm with the "
        "fresh security code sent to the Xin Account email.":
            "XTimers اکاؤنٹ کنٹرولز میں Delete XTimers Data منتخب کریں اور Xin Account "
            "ای میل پر بھیجے گئے نئے سیکیورٹی کوڈ سے تصدیق کریں۔",
        "This permanently deletes the selected XTimers account's data, including "
        "active timers, alarms, session and task history, device-targeting and "
        "scheduling-status records, snapshots, custom sounds, Background Library "
        "content, feedback, reminders, messages, published reports and report links, "
        "SMS configuration, and push-registration data, and removes its local XTimers "
        "data from that device.":
            "اس سے منتخب XTimers اکاؤنٹ کا ڈیٹا مستقل طور پر حذف ہو جاتا ہے، بشمول "
            "فعال ٹائمرز، الارمز، سیشن اور کام کی سرگزشت، ڈیوائس کو ہدف بنانے اور "
            "شیڈولنگ کی حیثیت کے ریکارڈز، اسنیپ شاٹس، حسبِ ضرورت آوازیں، Background "
            "Library کا مواد، تاثرات، یاد دہانیاں، پیغامات، شائع شدہ رپورٹس اور رپورٹ "
            "لنکس، SMS کنفیگریشن، اور پش نوٹیفکیشن رجسٹریشن ڈیٹا، اور اس ڈیوائس سے "
            "اس کا مقامی XTimers ڈیٹا بھی ہٹ جاتا ہے۔",
        "For support, see %1$@xintechllc.com/XTimers/support.html%2$@.":
            "مدد کے لیے، %1$@xintechllc.com/XTimers/support.html%2$@ دیکھیں۔",
        "I agree to receive SMS verification codes and reminder messages from\n"
        "      XTimers by Xintech LLC that I schedule for myself at this phone number.":
            "میں اس فون نمبر پر Xintech LLC کے زیرِ انتظام XTimers سے SMS تصدیقی "
            "کوڈز اور اپنے لیے شیڈول کیے گئے یاد دہانی کے پیغامات وصول کرنے پر "
            "رضامند ہوں۔",
        "Standard message and data rates may apply.":
            "معیاری پیغام اور ڈیٹا کی شرحیں لاگو ہو سکتی ہیں۔",
        "Reply STOP to opt out and HELP\n"
        "      for help.":
            "دستبردار ہونے کے لیے STOP اور مدد کے لیے HELP کا جواب دیں۔",
        "Message frequency varies.": "پیغامات کی تعداد مختلف ہو سکتی ہے۔",
        "XTimers will not send\n"
        "      marketing texts.":
            "XTimers مارکیٹنگ کے متنی پیغامات نہیں بھیجے گا۔",
        "Consent is not a condition of purchase.":
            "رضامندی خریداری کی شرط نہیں ہے۔",
        "The Xin Account, shared sign-in identity, and any other connected product\n"
        "      accounts remain available.":
            "Xin Account، مشترکہ سائن اِن شناخت، اور کسی بھی دیگر منسلک مصنوعات کے "
            "اکاؤنٹس دستیاب رہتے ہیں۔",
        "Reply STOP to opt out of SMS\n"
        "      messages or HELP for help.":
            "SMS پیغامات سے دستبردار ہونے کے لیے STOP یا مدد کے لیے HELP کا جواب دیں۔",
        "XTimers does not send marketing SMS and does not allow SMS to arbitrary "
        "third-party recipients.":
            "XTimers مارکیٹنگ SMS نہیں بھیجتا اور من مانے فریقِ ثالث وصول کنندگان کو "
            "SMS بھیجنے کی اجازت نہیں دیتا۔",
        "Xin Account sign-in is used\n"
        "      to authorize XTimers synchronization.":
            "XTimers کی ہم وقت سازی کی اجازت دینے کے لیے Xin Account سائن اِن "
            "استعمال ہوتا ہے۔",
        "For questions or requests, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "سوالات یا درخواستوں کے لیے، "
            "%1$@xintechllc.com/XTimers/support.html%2$@ دیکھیں۔",
        "This removes\n"
        "      that account's data from the XTimers service, including active timers,\n"
        "      alarms, session and task history, device-targeting and scheduling-status\n"
        "      records, snapshots, sounds, Background Library content, feedback,\n"
        "      reminders, messages, published reports and report links, SMS configuration,\n"
        "      and push-registration data.":
            "اس سے XTimers سروس سے اس اکاؤنٹ کا ڈیٹا حذف ہو جاتا ہے، بشمول فعال "
            "ٹائمرز، الارمز، سیشن اور کام کی سرگزشت، ڈیوائس کو ہدف بنانے اور شیڈولنگ "
            "کی حیثیت کے ریکارڈز، اسنیپ شاٹس، آوازیں، Background Library کا مواد، "
            "تاثرات، یاد دہانیاں، پیغامات، شائع شدہ رپورٹس اور رپورٹ لنکس، SMS "
            "کنفیگریشن، اور پش نوٹیفکیشن رجسٹریشن ڈیٹا۔",
        "For a privacy question or request that cannot be completed in the app, see "
        "%1$@xintechllc.com/XTimers/support.html%2$@.":
            "ایسے رازداری کے سوال یا درخواست کے لیے جو ایپ میں مکمل نہ ہو سکے، "
            "%1$@xintechllc.com/XTimers/support.html%2$@ دیکھیں۔",
        "SMS use is also governed by the %1$@SMS Terms%2$@ and "
        "%3$@Privacy Policy%4$@.":
            "SMS کا استعمال %1$@SMS کی شرائط%2$@ اور %3$@رازداری کی پالیسی%4$@ "
            "کے تحت بھی ہوتا ہے۔",
    },
    "vi": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account là",
    },
    "zh-Hans": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account 是",
        "I agree to receive SMS verification codes and reminder messages":
            "我同意在此电话号码接收由 Xintech LLC 运营的 XTimers 所发送的 SMS 验证码，以及我为自己"
            "安排的提醒消息。",
        "This website uses Umami Cloud, a cookie-free analytics service, to count\n"
        "      page visits and basic website actions such as App Store, download,\n"
        "      support, privacy, terms, and email-link clicks. Umami receives connection\n"
        "      and browser information used for aggregate metrics, including the page,\n"
        "      referrer, browser, operating system, device type, language, screen size,\n"
        "      and approximate location. Umami states that it does not store IP\n"
        "      addresses and uses an anonymized, rotating session identifier. These\n"
        "      website metrics are separate from the XTimers app data described above.":
            "本网站使用 Umami Cloud，一种无 Cookie 的分析服务，用于统计页面访问量和基本网站操作，"
            "如 App Store、下载、支持、隐私、条款和电子邮件链接点击。 Umami 接收连接和浏览器信息，"
            "用于汇总指标，包括页面、来源、浏览器、操作系统、设备类型、语言、屏幕大小和大致位置。 "
            "Umami 声明不会存储 IP 地址，并使用匿名的、轮换的会话标识符。 这些网站指标与上文描述的 XTimers "
            "应用数据是分开的。",
    },
    "zh-Hant": {
        "A Xin\n      Account is the shared identity layer":
            "Xin Account 是",
        "I agree to receive SMS verification codes and reminder messages":
            "我同意在此電話號碼接收由 Xintech LLC 營運的 XTimers 所發送的 SMS 驗證碼，以及我為自己"
            "排定的提醒訊息。",
    },
}
REVIEWED_OVERLAY_PATH = ROOT / "generated" / "ReviewedTranslationCorrections.json"
REVIEWED_OVERLAY_SHA256 = (
    "65f336d5edc91a486a3d2ab531d275c4edd1f28ff42b474baf8deeae2b010c56"
)
reviewed_overlay_bytes = REVIEWED_OVERLAY_PATH.read_bytes()
if hashlib.sha256(reviewed_overlay_bytes).hexdigest() != REVIEWED_OVERLAY_SHA256:
    raise RuntimeError("Reviewed translation correction overlay hash mismatch")
reviewed_overlay = json.loads(reviewed_overlay_bytes)
if not isinstance(reviewed_overlay, dict):
    raise RuntimeError("Reviewed translation correction overlay must be an object")
for reviewed_locale, reviewed_values in reviewed_overlay.items():
    if not isinstance(reviewed_locale, str) or not isinstance(reviewed_values, dict):
        raise RuntimeError("Reviewed translation correction overlay is malformed")
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        {str(key): str(value) for key, value in reviewed_values.items()}
    )
REVIEWED_KANNADA_OVERLAY_PATH = (
    ROOT / "generated" / "ReviewedKannadaCorrections.json"
)
REVIEWED_KANNADA_OVERLAY_SHA256 = (
    "8ebcabe4884410ed8e4c3e9d58fa0df004a4abf4c63a88824935bb63d2a8394b"
)
reviewed_kannada_overlay_bytes = REVIEWED_KANNADA_OVERLAY_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_kannada_overlay_bytes).hexdigest()
    != REVIEWED_KANNADA_OVERLAY_SHA256
):
    raise RuntimeError("Reviewed Kannada correction overlay hash mismatch")
reviewed_kannada_overlay = json.loads(reviewed_kannada_overlay_bytes)
if set(reviewed_kannada_overlay) != {"kn"} or not isinstance(
    reviewed_kannada_overlay["kn"], dict
):
    raise RuntimeError("Reviewed Kannada correction overlay is malformed")
for reviewed_locale, reviewed_values in reviewed_kannada_overlay.items():
    exact_values = {str(key): str(value) for key, value in reviewed_values.items()}
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        exact_values
    )
    reviewed_overlay.setdefault(reviewed_locale, {}).update(exact_values)
REVIEWED_KANNADA_SECOND_AUDIT_PATH = (
    ROOT / "generated" / "ReviewedKannadaSecondAuditCorrections.json"
)
REVIEWED_KANNADA_SECOND_AUDIT_SHA256 = (
    "69ef78e62648e8bbfd5cf4a7f3893d3ab982e291065d6e17f6041002f7e70dd7"
)
reviewed_kannada_second_audit_bytes = (
    REVIEWED_KANNADA_SECOND_AUDIT_PATH.read_bytes()
)
if (
    hashlib.sha256(reviewed_kannada_second_audit_bytes).hexdigest()
    != REVIEWED_KANNADA_SECOND_AUDIT_SHA256
):
    raise RuntimeError("Reviewed Kannada second-audit overlay hash mismatch")
reviewed_kannada_second_audit = json.loads(reviewed_kannada_second_audit_bytes)
if set(reviewed_kannada_second_audit) != {"kn"} or not isinstance(
    reviewed_kannada_second_audit["kn"], dict
):
    raise RuntimeError("Reviewed Kannada second-audit overlay is malformed")
if len(reviewed_kannada_second_audit["kn"]) != 58:
    raise RuntimeError("Reviewed Kannada second-audit overlay must contain 58 values")
for reviewed_locale, reviewed_values in reviewed_kannada_second_audit.items():
    exact_values = {str(key): str(value) for key, value in reviewed_values.items()}
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        exact_values
    )
    reviewed_overlay.setdefault(reviewed_locale, {}).update(exact_values)
REVIEWED_TELUGU_OVERLAY_PATH = (
    ROOT / "generated" / "ReviewedTeluguCorrections.json"
)
REVIEWED_TELUGU_OVERLAY_SHA256 = (
    "20d317c600d79bc7d7e22b3d8c42ccb5f21278127913394f2b9abc681656d949"
)
reviewed_telugu_overlay_bytes = REVIEWED_TELUGU_OVERLAY_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_telugu_overlay_bytes).hexdigest()
    != REVIEWED_TELUGU_OVERLAY_SHA256
):
    raise RuntimeError("Reviewed Telugu correction overlay hash mismatch")
reviewed_telugu_overlay = json.loads(reviewed_telugu_overlay_bytes)
if set(reviewed_telugu_overlay) != {"te"} or not isinstance(
    reviewed_telugu_overlay["te"], dict
):
    raise RuntimeError("Reviewed Telugu correction overlay is malformed")
if len(reviewed_telugu_overlay["te"]) != 47:
    raise RuntimeError("Reviewed Telugu correction overlay must contain 47 values")
for reviewed_locale, reviewed_values in reviewed_telugu_overlay.items():
    exact_values = {str(key): str(value) for key, value in reviewed_values.items()}
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        exact_values
    )
    reviewed_overlay.setdefault(reviewed_locale, {}).update(exact_values)
REVIEWED_BENGALI_OVERLAY_PATH = (
    ROOT / "generated" / "ReviewedBengaliCorrections.json"
)
REVIEWED_BENGALI_OVERLAY_SHA256 = (
    "d20186dabaf33639de11c14f02f2f6b419498fd0eb96a348a273eeaeede0072f"
)
reviewed_bengali_overlay_bytes = REVIEWED_BENGALI_OVERLAY_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_bengali_overlay_bytes).hexdigest()
    != REVIEWED_BENGALI_OVERLAY_SHA256
):
    raise RuntimeError("Reviewed Bengali correction overlay hash mismatch")
reviewed_bengali_overlay = json.loads(reviewed_bengali_overlay_bytes)
if set(reviewed_bengali_overlay) != {"bn"} or not isinstance(
    reviewed_bengali_overlay["bn"], dict
):
    raise RuntimeError("Reviewed Bengali correction overlay is malformed")
if len(reviewed_bengali_overlay["bn"]) != 53:
    raise RuntimeError("Reviewed Bengali correction overlay must contain 53 values")
for reviewed_locale, reviewed_values in reviewed_bengali_overlay.items():
    exact_values = {str(key): str(value) for key, value in reviewed_values.items()}
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        exact_values
    )
    reviewed_overlay.setdefault(reviewed_locale, {}).update(exact_values)
REVIEWED_PUNJABI_OVERLAY_PATH = (
    ROOT / "generated" / "ReviewedPunjabiCorrections.json"
)
REVIEWED_PUNJABI_OVERLAY_SHA256 = (
    "020caad380f7a98e53d235e56fd84d7c0eaad6d23cafb136a0587ec54617764e"
)
reviewed_punjabi_overlay_bytes = REVIEWED_PUNJABI_OVERLAY_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_punjabi_overlay_bytes).hexdigest()
    != REVIEWED_PUNJABI_OVERLAY_SHA256
):
    raise RuntimeError("Reviewed Punjabi correction overlay hash mismatch")
reviewed_punjabi_document = json.loads(reviewed_punjabi_overlay_bytes)
if set(reviewed_punjabi_document) != {"_app_glossary", "pa"} or not isinstance(
    reviewed_punjabi_document["pa"], dict
):
    raise RuntimeError("Reviewed Punjabi correction overlay is malformed")
reviewed_punjabi_overlay = reviewed_punjabi_document["pa"]
exact_punjabi_values = {
    str(key): str(value) for key, value in reviewed_punjabi_overlay.items()
}
REVIEWED_TRANSLATION_CORRECTIONS.setdefault("pa", {}).update(
    exact_punjabi_values
)
reviewed_overlay.setdefault("pa", {}).update(exact_punjabi_values)
REVIEWED_ALARM_TERMS_PATH = (
    ROOT / "generated" / "ReviewedAlarmTermCorrections.json"
)
REVIEWED_ALARM_TERMS_SHA256 = (
    "2c231b1bd62df202d0b0268c5651d20f564346b91cd4e1f352974f04d691c005"
)
reviewed_alarm_terms_bytes = REVIEWED_ALARM_TERMS_PATH.read_bytes()
if hashlib.sha256(reviewed_alarm_terms_bytes).hexdigest() != REVIEWED_ALARM_TERMS_SHA256:
    raise RuntimeError("Reviewed alarm-term correction overlay hash mismatch")
reviewed_alarm_terms = json.loads(reviewed_alarm_terms_bytes)
if not isinstance(reviewed_alarm_terms, dict):
    raise RuntimeError("Reviewed alarm-term correction overlay must be an object")
for reviewed_locale, reviewed_values in reviewed_alarm_terms.items():
    if not isinstance(reviewed_locale, str) or not isinstance(reviewed_values, dict):
        raise RuntimeError("Reviewed alarm-term correction overlay is malformed")
    for reviewed_term, reviewed_value in reviewed_values.items():
        if reviewed_term not in ALARM_UI_TERMS or not isinstance(reviewed_value, str):
            raise RuntimeError("Reviewed alarm-term correction overlay is malformed")
        if not reviewed_value.strip():
            raise RuntimeError("Reviewed alarm-term correction must not be empty")
REVIEWED_KANNADA_ALARM_TERMS_PATH = (
    ROOT / "generated" / "ReviewedKannadaAlarmTermCorrections.json"
)
REVIEWED_KANNADA_ALARM_TERMS_SHA256 = (
    "9242e604d3525b9ba1bc4c42d851b1cb515becfd2b8425635813a55ca2b1cacb"
)
reviewed_kannada_alarm_terms_bytes = REVIEWED_KANNADA_ALARM_TERMS_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_kannada_alarm_terms_bytes).hexdigest()
    != REVIEWED_KANNADA_ALARM_TERMS_SHA256
):
    raise RuntimeError("Reviewed Kannada alarm-term overlay hash mismatch")
reviewed_kannada_alarm_terms = json.loads(reviewed_kannada_alarm_terms_bytes)
if set(reviewed_kannada_alarm_terms) != {"kn"} or not isinstance(
    reviewed_kannada_alarm_terms["kn"], dict
):
    raise RuntimeError("Reviewed Kannada alarm-term overlay is malformed")
for reviewed_term, reviewed_value in reviewed_kannada_alarm_terms["kn"].items():
    if reviewed_term not in ALARM_UI_TERMS or not isinstance(reviewed_value, str):
        raise RuntimeError("Reviewed Kannada alarm-term overlay is malformed")
    if not reviewed_value.strip():
        raise RuntimeError("Reviewed Kannada alarm-term correction must not be empty")
reviewed_alarm_terms.setdefault("kn", {}).update(
    {str(key): str(value) for key, value in reviewed_kannada_alarm_terms["kn"].items()}
)
REVIEWED_TELUGU_ALARM_TERMS_PATH = (
    ROOT / "generated" / "ReviewedTeluguAlarmTermCorrections.json"
)
REVIEWED_TELUGU_ALARM_TERMS_SHA256 = (
    "9e9da49a17980978b54c12523d473df92b845cc3a8dbba03b8848dd5ec8cf37e"
)
reviewed_telugu_alarm_terms_bytes = REVIEWED_TELUGU_ALARM_TERMS_PATH.read_bytes()
if (
    hashlib.sha256(reviewed_telugu_alarm_terms_bytes).hexdigest()
    != REVIEWED_TELUGU_ALARM_TERMS_SHA256
):
    raise RuntimeError("Reviewed Telugu alarm-term overlay hash mismatch")
reviewed_telugu_alarm_terms = json.loads(reviewed_telugu_alarm_terms_bytes)
if set(reviewed_telugu_alarm_terms) != {"te"} or not isinstance(
    reviewed_telugu_alarm_terms["te"], dict
):
    raise RuntimeError("Reviewed Telugu alarm-term overlay is malformed")
if len(reviewed_telugu_alarm_terms["te"]) != 5:
    raise RuntimeError("Reviewed Telugu alarm-term overlay must contain five values")
for reviewed_term, reviewed_value in reviewed_telugu_alarm_terms["te"].items():
    if reviewed_term not in ALARM_UI_TERMS or not isinstance(reviewed_value, str):
        raise RuntimeError("Reviewed Telugu alarm-term overlay is malformed")
    if not reviewed_value.strip():
        raise RuntimeError("Reviewed Telugu alarm-term correction must not be empty")
reviewed_alarm_terms.setdefault("te", {}).update(
    {str(key): str(value) for key, value in reviewed_telugu_alarm_terms["te"].items()}
)
reviewed_punjabi_alarm_document = reviewed_punjabi_document["_app_glossary"]
if set(reviewed_punjabi_alarm_document) != {"pa"} or not isinstance(
    reviewed_punjabi_alarm_document["pa"], dict
):
    raise RuntimeError("Reviewed Punjabi alarm-term overlay is malformed")
for reviewed_term, reviewed_value in reviewed_punjabi_alarm_document["pa"].items():
    if reviewed_term not in ALARM_UI_TERMS or not isinstance(reviewed_value, str):
        raise RuntimeError("Reviewed Punjabi alarm-term overlay is malformed")
    if not reviewed_value.strip():
        raise RuntimeError("Reviewed Punjabi alarm-term correction must not be empty")
reviewed_alarm_terms.setdefault("pa", {}).update(
    {
        str(key): str(value)
        for key, value in reviewed_punjabi_alarm_document["pa"].items()
    }
)
DIRECT_GPT_TRANSLATION_ROOT = (
    ROOT / "generated" / "DirectGPTWebsiteTranslations"
)
for direct_gpt_path in sorted(DIRECT_GPT_TRANSLATION_ROOT.glob("*.json")):
    direct_gpt_document = json.loads(direct_gpt_path.read_text(encoding="utf-8"))
    direct_gpt_locale = direct_gpt_document.get("locale")
    direct_gpt_values = direct_gpt_document.get("translations")
    if (
        direct_gpt_document.get("schemaVersion") != 1
        or direct_gpt_document.get("authorship") != "direct-codex-gpt"
        or not isinstance(direct_gpt_locale, str)
        or direct_gpt_path.stem != direct_gpt_locale
        or not isinstance(direct_gpt_values, dict)
        or not direct_gpt_values
        or any(
            not isinstance(source, str)
            or not isinstance(translated, str)
            or not translated.strip()
            for source, translated in direct_gpt_values.items()
        )
    ):
        raise RuntimeError(f"Malformed direct GPT translation artifact: {direct_gpt_path}")
    exact_direct_gpt_values = {
        str(source): str(translated)
        for source, translated in direct_gpt_values.items()
    }
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(direct_gpt_locale, {}).update(
        exact_direct_gpt_values
    )
    reviewed_overlay.setdefault(direct_gpt_locale, {}).update(
        exact_direct_gpt_values
    )
FINAL_HIGH_RISK_CORRECTIONS_PATH = (
    ROOT / "generated" / "ReviewedFinalHighRiskCorrections.json"
)
FINAL_HIGH_RISK_CORRECTIONS_SHA256 = (
    "cce69cd82103535a4099c334a7d1cc1a7a9b4fafc3a8dafd3ce0079633fc877a"
)
final_high_risk_corrections_bytes = FINAL_HIGH_RISK_CORRECTIONS_PATH.read_bytes()
if (
    hashlib.sha256(final_high_risk_corrections_bytes).hexdigest()
    != FINAL_HIGH_RISK_CORRECTIONS_SHA256
):
    raise RuntimeError("Final high-risk correction overlay hash mismatch")
final_high_risk_corrections = json.loads(final_high_risk_corrections_bytes)
if not isinstance(final_high_risk_corrections, dict):
    raise RuntimeError("Final high-risk correction overlay must be an object")
for reviewed_locale, reviewed_values in final_high_risk_corrections.items():
    if not isinstance(reviewed_locale, str) or not isinstance(reviewed_values, dict):
        raise RuntimeError("Final high-risk correction overlay is malformed")
    exact_values = {str(key): str(value) for key, value in reviewed_values.items()}
    if any(not key or not value.strip() for key, value in exact_values.items()):
        raise RuntimeError("Final high-risk correction overlay is malformed")
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(reviewed_locale, {}).update(
        exact_values
    )
    reviewed_overlay.setdefault(reviewed_locale, {}).update(exact_values)
# Complete direct GPT catalogs are materialized after all narrower review
# packets. Reapply them last so their current, fully reconciled value is the
# deterministic authority when an older focused overlay covers the same key.
for direct_gpt_path in sorted(DIRECT_GPT_TRANSLATION_ROOT.glob("*.json")):
    direct_gpt_document = json.loads(direct_gpt_path.read_text(encoding="utf-8"))
    direct_gpt_locale = str(direct_gpt_document["locale"])
    exact_direct_gpt_values = {
        str(source): str(translated)
        for source, translated in direct_gpt_document["translations"].items()
    }
    REVIEWED_TRANSLATION_CORRECTIONS.setdefault(direct_gpt_locale, {}).update(
        exact_direct_gpt_values
    )
    reviewed_overlay.setdefault(direct_gpt_locale, {}).update(
        exact_direct_gpt_values
    )
# Earlier app catalogs supplied these exact labels to the first website drafts.
# Retain the reviewed old spellings only so correction replay can replace them
# inside complete policy sentences after the standalone app label is corrected.
REVIEWED_ALARM_TERM_PREVIOUS_VALUES = {
    "bn": {
        "Pending Apply": "মুলতুবি আবেদন",
        "Pending Cancellation": "বাতিলের বিষয়টি বিচারাধীন",
        "Unavailable": "অনুপলব্ধ।",
        "Failed": "ব্যর্থ হয়েছে।",
        "Sync Pending": "মুলতুবি সিঙ্ক",
    },
    "gu": {
        "Rings On": "આ અલાર્મ જે ઉપકરણો પર વાગશે",
        "Pending Apply": "બાકી અરજીઓ",
        "Pending Cancellation": "રદ કરવાનું બાકી છે",
        "Needs Permission": "પરવાનગીની જરૂર છે",
        "Sync Pending": "સિંક બાકી છે",
    },
    "he": {"Needs Permission": "דורש הרשאה"},
    "hr": {
        "Pending Apply": "Na čekanju Primjena",
        "Pending Cancellation": "Na čekanju Otkazivanje",
        "Needs Permission": "Potrebna dozvola",
    },
    "hu": {
        "Pending Apply": "Függőben lévő alkalmazás",
        "Pending Cancellation": "Függőben lévő törlés",
        "Sync Pending": "Szinkronizálás függőben",
    },
    "it": {
        "Rings On": "Dispositivi in cui suona questa allarme",
        "Pending Apply": "Applica in sospeso",
        "Pending Cancellation": "Cancellazione in sospeso",
        "Needs Permission": "Necessita di Permesso",
        "Failed": "Fallito",
    },
    "kn": {
        "Pending Apply": "ಬಾಕಿ ಇರುವ ಅರ್ಜಿ",
        "Pending Cancellation": "ರದ್ದುಗೊಳಿಸುವಿಕೆ ಬಾಕಿ ಇದೆ",
        "Needs Permission": "ಅನುಮತಿ ಬೇಕು",
        "Failed": "ವಿಫಲವಾಗಿದೆ.",
        "Sync Pending": "ಸಿಂಕ್ ಬಾಕಿ ಇದೆ",
    },
    "ms": {
        "Pending Apply": "Menunggu Permohonan",
        "Unavailable": "Tidak tersedia",
        "Failed": "gagal",
        "Sync Pending": "Menyegerak Tertunda",
    },
    "nb": {
        "Pending Apply": "Venter på bruk",
        "Sync Pending": "Synkronisering ventende",
    },
    "nl": {
        "Pending Apply": "In afwachting van toepassen",
        "Needs Permission": "Toestemming Vereist",
    },
    "pl": {"Sync Pending": "Synchronizacja w toku"},
    "pa": {
        "Pending Apply": "ਲੰਬਿਤ ਅਰਜ਼ੀ",
        "Pending Cancellation": "ਰੱਦ ਕਰਨਾ ਪੈਂਡਿੰਗ",
        "Sync Pending": "ਲੰਬਿਤ ਸਿੰਕ ਕਰੋ",
    },
    "pt-BR": {"Pending Apply": "Aplicar Pendente"},
    "ru": {"Sync Pending": "Синхронизация в ожидании"},
    "sl": {
        "Pending Apply": "Čaka na uporabo",
        "Needs Permission": "Potrebna dovoljenja",
        "Sync Pending": "Sinhronizacija v teku",
    },
    "sv": {
        "Rings On": "Enheter där detta larm ringer",
        "Pending Apply": "Väntar på att tillämpas",
        "Pending Cancellation": "Väntar på avbokning",
        "Needs Permission": "Behöver Tillstånd",
        "Unavailable": "Ej tillgänglig",
        "Sync Pending": "Synkronisering väntar",
    },
    "th": {
        "Pending Apply": "รอการใช้",
        "Pending Cancellation": "รอยกเลิก",
        "Needs Permission": "ต้องขออนุญาต",
        "Sync Pending": "กำลังซิงค์ค้างอยู่",
    },
    "tr": {
        "Pending Apply": "Uygulama Bekleniyor",
        "Needs Permission": "İzin Gerekiyor",
        "Unavailable": "Kullanılamaz",
        "Sync Pending": "Senkr. Bekleniyor",
    },
    "uk": {
        "Rings On": "Пристрої, на яких лунає цей сигнал тривоги",
        "Sync Pending": "Синхронізація в очікуванні",
    },
    "vi": {
        "Rings On": "Các thiết bị nơi báo thức này reo",
        "Needs Permission": "Cần quyền",
        "Unavailable": "Không có sẵn",
        "Failed": "thất bại",
    },
}
# Exact substitutions make the semantic corrections above reproducible after a
# machine-draft cache merge. The command is idempotent: a catalog that already
# contains every reviewed target is left unchanged.
REVIEWED_TRANSLATION_REPLACEMENTS = {
    "ar": (
        ("حساب Xin هو طبقة الهوية المشتركة", "يُعد Xin Account طبقة الهوية المشتركة"),
        ("Xin Account هو طبقة الهوية المشتركة", "يُعد Xin Account طبقة الهوية المشتركة"),
        ("تحدد يُعد Xin Accountيتك وتخوّل كل حساب XTimers متصل.",
         "يحدد Xin Account هويتك ويخوّل كل حساب XTimers متصل."),
        ("بيانات تسجيل الدفع", "بيانات التسجيل للإشعارات الفورية"),
    ),
    "he": (
        ("%1$@למד כיצד שכבות החשבון work.%2$@",
         "%1$@למד כיצד פועלות שכבות החשבון.%2$@"),
        ("חשבון Xin הוא", "Xin Account הוא"),
        ("כפי שמוסבר במדיניות הפרטיות הראשית של %2$@%3$@.",
         "כפי שמוסבר ב-%2$@מדיניות הפרטיות הראשית%3$@."),
    ),
    "ja": (
        ("A Xinアカウントは", "Xin Account は"),
        ("XTimers は、そのインストールによってスケジュールされたアラームを削除する前に、"
         "ローカルのアカウント状態を削除するよう最善を尽くします。",
         "XTimers は、ローカルのアカウント状態を削除する前に、そのインストールによって"
         "スケジュールされたアラームのキャンセルを最大限試みます。"),
        ("%1$@保持に関するプライバシーポリシーを読む details.%2$@",
         "%1$@保持の詳細についてはプライバシーポリシーをご覧ください。%2$@"),
        ("私は、XTimersからXintech LLCを通じて、この電話番号で自分自身が予定したSMSの確認コードおよび"
         "リマインダーメッセージを受け取ることに同意します。",
         "私は、この電話番号で、Xintech LLC が提供する XTimers から SMS 確認コードと、"
         "自分自身のために予定したリマインダーメッセージを受け取ることに同意します。"),
        ("私は SMS の確認コードおよび Xintech LLC 経由で自分自身がこの電話番号でスケジュールした XTimers からの"
         "リマインダーメッセージを受け取ることに同意します。",
         "私は、この電話番号で、Xintech LLC が提供する XTimers から SMS 確認コードと、"
         "自分自身のために予定したリマインダーメッセージを受け取ることに同意します。"),
        ("XTimers by Xintech LLC プライバシーポリシー",
         "Xintech LLC が提供する XTimers のプライバシーポリシー"),
    ),
    "ko": (
        ("Xin 계정은", "Xin Account는"),
        ("Xin Account은", "Xin Account는"),
        ("마지막 업데이트: %1$@2026년 8월 23일%2$@.",
         "최종 업데이트: %1$@2026년 8월 23일%2$@."),
        ("XTimers는 해당 설치에서 예약된 알람을 제거하기 전에 가능하면 알람 취소를 시도합니다.",
         "XTimers는 로컬 계정 상태를 제거하기 전에 해당 설치에서 예약된 알람을 취소하기 위해 최선을 다합니다."),
        ("저는 이 전화번호에서 제가 직접 예약한 Xintech LLC를 통해 SMS 확인 코드와 알림 메시지를 XTimers로부터 받는 것에 동의합니다.",
         "저는 이 전화번호로 Xintech LLC가 제공하는 XTimers의 SMS 인증 코드와 제가 직접 예약한 알림 메시지를 받는 데 동의합니다."),
        ("나는 내 전화번호에서 내가 스스로 예약한 SMS 인증 코드와 XTimers에서 Xintech LLC를 통해 전송되는 알림 메시지를 받는 것에 동의합니다.",
         "저는 이 전화번호로 Xintech LLC가 제공하는 XTimers의 SMS 인증 코드와 제가 직접 예약한 알림 메시지를 받는 데 동의합니다."),
        ("XTimers by Xintech LLC SMS 옵트인 증거", "Xintech LLC가 제공하는 XTimers SMS 옵트인 증거"),
        ("XTimers by Xintech LLC 개인 정보 보호 정책", "Xintech LLC가 제공하는 XTimers 개인정보 보호정책"),
        ("XTimers by Xintech LLC SMS 약관", "Xintech LLC가 제공하는 XTimers SMS 약관"),
    ),
    "th": (("บัญชี Xin คือ", "Xin Account คือ"),),
    "tr": (
        (
            "App Store kopyaları, Apple'in Standart Lisanslı Uygulama Son Kullanıcı "
            "Lisans Sözleşmesi ile düzenlenir; XTimers için özel bir lisans sözleşmesi "
            "App Store veya App Store Connect'te sunulmadıkça; bu şartlar, XTimers "
            "hesapları ve hizmetleri için geçerli lisansa ek olarak uygulanır.",
            "App Store kopyaları, XTimers için App Store'da veya App Store Connect'te "
            "özel bir lisans sözleşmesi sunulmadıkça Apple'ın Standart Lisanslı "
            "Uygulama Son Kullanıcı Lisans Sözleşmesi'ne tabidir; bu şartlar XTimers "
            "hesapları ve hizmetleri için geçerli lisansı tamamlar.",
        ),
    ),
    "uk": (
        (
            "Копії App Store регулюються\n"
            "      Стандартною ліцензійною угодою користувача додатків Apple, якщо\n"
            "      для XTimers у App Store або App Store Connect не подано іншу "
            "ліцензійну угоду; ці умови доповнюють відповідну ліцензію для\n"
            "      облікових записів та послуг XTimers.",
            "Копії App Store регулюються Стандартною ліцензійною угодою кінцевого "
            "користувача ліцензованого застосунку Apple, якщо для XTimers в App Store "
            "або App Store Connect не представлено спеціальну ліцензійну угоду; ці "
            "умови доповнюють застосовну ліцензію щодо облікових записів і послуг XTimers.",
        ),
    ),
    "vi": (("Tài khoản A Xin  \n      là", "Xin Account là"),),
    "zh-Hans": (
        ("A Xin 账户是", "Xin Account 是"),
        ("我同意接收来自 XTimers 的 SMS 验证码和提醒消息，按我在此电话号码上自行安排的 Xintech LLC。",
         "我同意在此电话号码接收由 Xintech LLC 运营的 XTimers 所发送的 SMS 验证码，以及我为自己安排的提醒消息。"),
        ("我同意通过我在此电话号码上自行安排的 Xintech LLC 接收来自 XTimers 的 SMS 验证码和提醒消息。",
         "我同意在此电话号码接收由 Xintech LLC 运营的 XTimers 所发送的 SMS 验证码，以及我为自己安排的提醒消息。"),
        ("本网站使用 Umami Cloud，这是一项无 Cookie 的分析服务，用于统计页面访问量和基本的网页操作，如 App Store、下载、支持、隐私、条款以及电子邮件链接点击。 Umami 会接收用于汇总指标的连接和浏览器信息，包括页面、来源、浏览器、操作系统、设备类型、语言、屏幕尺寸和大致位置。 Umami 声明它不会存储 IP 地址，并使用匿名的、轮换的会话标识符。 这些网站指标与上述所述的 XTimers 应用数据是分开的。",
         "本网站使用 Umami Cloud，一种无 Cookie 的分析服务，用于统计页面访问量和基本网站操作，如 App Store、下载、支持、隐私、条款和电子邮件链接点击。 Umami 接收连接和浏览器信息，用于汇总指标，包括页面、来源、浏览器、操作系统、设备类型、语言、屏幕大小和大致位置。 Umami 声明不会存储 IP 地址，并使用匿名的、轮换的会话标识符。 这些网站指标与上文描述的 XTimers 应用数据是分开的。"),
        ("本网站使用 Umami Cloud，一种无 Cookie 的分析服务，用于统计页面访问量和基本网站操作，如 App Store、下载、支持、隐私、条款和电子邮件链接点击。\\n \\nUmami 接收连接和浏览器信息，用于汇总指标，包括页面、来源、浏览器、操作系统、设备类型、语言、屏幕大小和大致位置。\\n \\nUmami 声明不会存储 IP 地址，并使用匿名的、旋转的会话标识符。\\n \\n这些网站指标与上文描述的 XTimers 应用数据是分开的。",
         "本网站使用 Umami Cloud，一种无 Cookie 的分析服务，用于统计页面访问量和基本网站操作，"
         "如 App Store、下载、支持、隐私、条款和电子邮件链接点击。 Umami 接收连接和浏览器信息，"
         "用于汇总指标，包括页面、来源、浏览器、操作系统、设备类型、语言、屏幕大小和大致位置。 "
         "Umami 声明不会存储 IP 地址，并使用匿名的、轮换的会话标识符。 这些网站指标与上文描述的 XTimers "
         "应用数据是分开的。"),
    ),
    "zh-Hant": (
        ("A Xin 帳戶是", "Xin Account 是"),
        ("我同意接收來自 XTimers 的 SMS 驗證碼及提醒訊息，透過我在此電話號碼自行安排的 Xintech LLC 送出。",
         "我同意在此電話號碼接收由 Xintech LLC 營運的 XTimers 所發送的 SMS 驗證碼，以及我為自己排定的提醒訊息。"),
        ("我同意通過 Xintech LLC 接收由 XTimers 發送到此電話號碼的 SMS 驗證碼及提醒訊息，該訊息由我自行安排。",
         "我同意在此電話號碼接收由 Xintech LLC 營運的 XTimers 所發送的 SMS 驗證碼，以及我為自己排定的提醒訊息。"),
    ),
}
BASE_PRODUCT_URL = "https://xintechllc.com/XTimers/"
BASE_LEGAL_URL = "https://xintechllc.com/FlexibleTimers/"
IDENTIFIER_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z][A-Za-z]{1,7})?$")
MENU_PATTERN = re.compile(r'<details class="language-menu">.*?</details>', re.DOTALL)
TRANSLATABLE_META_NAMES = {
    "description",
    "twitter:description",
    "twitter:title",
}
TRANSLATABLE_META_PROPERTIES = {
    "og:description",
    "og:title",
    "twitter:description",
    "twitter:title",
}
INLINE_BLOCK_TAGS = {"h1", "h2", "h3", "li", "p"}
INLINE_TAGS = {"a", "br", "code", "em", "img", "small", "span", "strong", "svg", "time", "use"}
OPAQUE_INLINE_TAGS = {"br", "code", "img", "svg"}
TRANSLATABLE_ATTRIBUTES = (
    "aria-label", "alt", "title", "placeholder", "data-caption",
    "data-open-label", "data-close-label",
)
INLINE_PLACEHOLDER_PATTERN = re.compile(r"%(\d+)\$@")
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
    parser.add_argument(
        "--import-alarm-terms-from",
        type=Path,
        metavar="LOCALIZATION_ROOT",
        help=(
            "Copy central alarm UI terms from locale .lproj/Localizable.strings "
            "catalogs into the website catalogs."
        ),
    )
    parser.add_argument("--generate", action="store_true")
    parser.add_argument(
        "--apply-reviewed-corrections",
        action="store_true",
        help="Reapply deterministic human-reviewed translation corrections.",
    )
    parser.add_argument(
        "--prune-obsolete-translations",
        action="store_true",
        help="Remove translation keys no longer present in the canonical pages.",
    )
    parser.add_argument("--locales", nargs="*")
    return parser.parse_args()


def validate_inventory(inventory: list[dict]) -> None:
    for item in inventory:
        identifier = item.get("identifier")
        direction = item.get("direction")
        route = item.get("route")
        native_name = item.get("nativeName")
        if not isinstance(identifier, str) or IDENTIFIER_PATTERN.fullmatch(identifier) is None:
            raise RuntimeError(f"Unsafe localization identifier: {identifier!r}")
        if direction not in {"ltr", "rtl"}:
            raise RuntimeError(f"Unsafe localization direction for {identifier}: {direction!r}")
        expected_route = "flexible-timers.html" if identifier == "en" else f"{identifier}/"
        if route != expected_route:
            raise RuntimeError(f"Unsafe localization route for {identifier}: {route!r}")
        if (
            not isinstance(native_name, str)
            or not native_name.strip()
            or len(native_name) > 80
            or any(ord(character) < 0x20 for character in native_name)
        ):
            raise RuntimeError(f"Unsafe native language name for {identifier}")


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


def has_translatable_meta_content(tag: Tag) -> bool:
    return tag.name == "meta" and (
        tag.get("name") in TRANSLATABLE_META_NAMES
        or tag.get("property") in TRANSLATABLE_META_PROPERTIES
    )


def excluded_text_node(node) -> bool:
    parent = node.parent
    if parent is None or parent.name in {"script", "style", "noscript"}:
        return True
    if parent.find_parent("details", class_="language-menu") is not None:
        return True
    if parent.name == "details" and "language-menu" in (parent.get("class") or []):
        return True
    return isinstance(node, (Comment, Doctype))


def inline_translation_template(tag: Tag) -> tuple[str, list[dict[str, str]]]:
    placeholders: list[dict[str, str]] = []
    pieces: list[str] = []

    def add_placeholder(markup: str, kind: str, name: str, pair: str) -> None:
        placeholder = f"%{len(placeholders) + 1}$@"
        placeholders.append(
            {
                "placeholder": placeholder,
                "markup": markup,
                "kind": kind,
                "name": name,
                "pair": pair,
            }
        )
        pieces.append(placeholder)

    def walk(parent: Tag) -> None:
        for child in parent.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                pieces.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name not in INLINE_TAGS:
                raise RuntimeError(
                    f"Unsupported inline element <{child.name}> in <{tag.name}>"
                )
            rendered = str(child)
            if child.name in OPAQUE_INLINE_TAGS:
                add_placeholder(rendered, "opaque", child.name, str(len(placeholders)))
                continue
            close_markup = f"</{child.name}>"
            if not rendered.endswith(close_markup):
                raise RuntimeError(f"Unable to preserve inline element: {rendered}")
            open_markup = rendered[: rendered.find(">") + 1]
            pair = str(len(placeholders))
            add_placeholder(open_markup, "open", child.name, pair)
            walk(child)
            add_placeholder(close_markup, "close", child.name, pair)

    walk(tag)
    return " ".join("".join(pieces).split()), placeholders


def inline_translation_blocks(soup: BeautifulSoup) -> list[Tag]:
    result: list[Tag] = []
    for tag in soup.find_all(INLINE_BLOCK_TAGS):
        if is_within_import_ignored_structure(tag):
            continue
        descendant_tags = tag.find_all(True)
        if not descendant_tags:
            continue
        if any(child.name not in INLINE_TAGS for child in descendant_tags):
            if is_translatable(tag.get_text(" ", strip=True)):
                unsupported = sorted(
                    {child.name for child in descendant_tags if child.name not in INLINE_TAGS}
                )
                raise RuntimeError(
                    f"Unsupported inline translation tags in <{tag.name}>: "
                    + ", ".join(unsupported)
                )
            continue
        template, _ = inline_translation_template(tag)
        if is_translatable(template):
            result.append(tag)
    return result


def node_within_blocks(node, blocks: set[int]) -> bool:
    parent = node.parent
    while isinstance(parent, Tag):
        if id(parent) in blocks:
            return True
        parent = parent.parent
    return False


def restored_inline_translation(
    translated: str, placeholders: list[dict[str, str]]
) -> BeautifulSoup:
    matches = list(INLINE_PLACEHOLDER_PATTERN.finditer(translated))
    expected = [item["placeholder"] for item in placeholders]
    actual = [match.group(0) for match in matches]
    if sorted(actual) != sorted(expected):
        raise RuntimeError(
            f"Inline translation changed placeholder signature: expected {expected}, "
            f"found {actual}"
        )
    by_placeholder = {item["placeholder"]: item for item in placeholders}
    expected_parent: dict[str, str | None] = {}
    source_stack: list[tuple[str, str]] = []
    for item in placeholders:
        if item["kind"] in {"open", "opaque"}:
            expected_parent[item["placeholder"]] = (
                source_stack[-1][1] if source_stack else None
            )
        if item["kind"] == "open":
            source_stack.append((item["name"], item["pair"]))
        elif item["kind"] == "close":
            if not source_stack or source_stack[-1] != (item["name"], item["pair"]):
                raise RuntimeError("Canonical inline placeholder nesting is invalid")
            source_stack.pop()
    if source_stack:
        raise RuntimeError("Canonical inline placeholder nesting is incomplete")

    stack: list[tuple[str, str, int]] = []
    for match, placeholder in zip(matches, actual):
        item = by_placeholder[placeholder]
        if item["kind"] == "open":
            actual_parent = stack[-1][1] if stack else None
            if actual_parent != expected_parent[placeholder]:
                raise RuntimeError(
                    f"Inline translation changed tag containment: {translated!r}"
                )
            if item["name"] == "a" and any(name == "a" for name, _, _ in stack):
                raise RuntimeError(
                    f"Inline translation nested an anchor: {translated!r}"
                )
            stack.append((item["name"], item["pair"], match.end()))
        elif item["kind"] == "opaque":
            actual_parent = stack[-1][1] if stack else None
            if actual_parent != expected_parent[placeholder]:
                raise RuntimeError(
                    f"Inline translation changed tag containment: {translated!r}"
                )
        elif item["kind"] == "close":
            if not stack:
                raise RuntimeError(
                    f"Inline translation produced invalid tag order: {translated!r}"
                )
            open_name, open_pair, content_start = stack.pop()
            expected_pair = (item["name"], item["pair"])
            if (open_name, open_pair) != expected_pair:
                raise RuntimeError(
                    f"Inline translation produced invalid tag order: {translated!r}"
                )
            enclosed = translated[content_start : match.start()]
            visible_enclosed = INLINE_PLACEHOLDER_PATTERN.sub("", enclosed).strip()
            opaque_content = any(
                by_placeholder[nested.group(0)]["kind"] == "opaque"
                and BeautifulSoup(
                    by_placeholder[nested.group(0)]["markup"], "html.parser"
                ).get_text(strip=True)
                for nested in INLINE_PLACEHOLDER_PATTERN.finditer(enclosed)
            )
            if not visible_enclosed and not opaque_content:
                raise RuntimeError(
                    f"Inline translation emptied <{item['name']}> content: {translated!r}"
                )
    if stack:
        raise RuntimeError(f"Inline translation left unclosed markup: {translated!r}")
    escaped_translation = html_escape(translated, quote=False)
    restored = INLINE_PLACEHOLDER_PATTERN.sub(
        lambda match: by_placeholder[match.group(0)]["markup"],
        escaped_translation,
    )
    return BeautifulSoup(restored, "html.parser")


def extracted_values(root: Path) -> set[str]:
    values: set[str] = {TRANSLATION_NOTE, *ALARM_UI_TERMS}
    for file_name in SOURCE_PAGES:
        soup = BeautifulSoup((root / file_name).read_text(encoding="utf-8"), "html.parser")
        blocks = inline_translation_blocks(soup)
        block_ids = {id(tag) for tag in blocks}
        values.update(inline_translation_template(tag)[0] for tag in blocks)
        for node in soup.find_all(string=True):
            if excluded_text_node(node) or node_within_blocks(node, block_ids):
                continue
            value = str(node).strip()
            if is_translatable(value):
                values.add(value)
        for tag in soup.find_all(True):
            for attribute in TRANSLATABLE_ATTRIBUTES:
                value = tag.get(attribute)
                if isinstance(value, str) and is_translatable(value):
                    values.add(value)
            if has_translatable_meta_content(tag):
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
    source_blocks = inline_translation_blocks(source)
    source_block_ids = {id(tag) for tag in source_blocks}

    for source_tag in source_blocks:
        try:
            localized_tag = tag_at_path(localized, tag_path(source_tag, source))
            source_template, source_placeholders = inline_translation_template(source_tag)
            localized_template, localized_placeholders = inline_translation_template(
                localized_tag
            )
        except RuntimeError:
            continue
        if len(source_placeholders) != len(localized_placeholders):
            continue
        add_imported_value(
            translations,
            source_template,
            localized_template,
            f"{localized_path}:{tag_path(source_tag, source)}:inline-block",
        )

    for node in source.find_all(string=True):
        if excluded_text_node(node) or node_within_blocks(node, source_block_ids):
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
        for attribute in TRANSLATABLE_ATTRIBUTES:
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
        if has_translatable_meta_content(source_tag):
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
    for file_name in LEGACY_IMPORT_PAGES:
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


def import_alarm_terms(
    localization_root: Path,
    translation_root: Path,
    locales: list[str],
) -> None:
    for locale in locales:
        app_catalog = localization_root / f"{locale}.lproj" / "Localizable.strings"
        website_catalog = translation_root / f"{locale}.lproj" / "Website.strings"
        app_values = load_strings(app_catalog)
        website_values = load_strings(website_catalog)
        missing = [term for term in ALARM_UI_TERMS if not app_values.get(term, "").strip()]
        if missing:
            raise RuntimeError(
                f"Alarm UI term source for {locale} is missing: {', '.join(missing)}"
            )
        for term in ALARM_UI_TERMS:
            website_values[term] = app_values[term]
        website_catalog.write_text(
            localized_strings_document(website_values), encoding="utf-8"
        )
        print(f"Imported {len(ALARM_UI_TERMS)} alarm UI terms for {locale}.")


def reviewed_correction_values(
    source: dict[str, str], translations: dict[str, str], identifier: str
) -> tuple[dict[str, str], int]:
    updated = dict(translations)
    replacement_count = 0
    for term, reviewed_value in reviewed_alarm_terms.get(identifier, {}).items():
        exact_reviewed_value = reviewed_overlay.get(identifier, {}).get(term)
        if exact_reviewed_value is not None and updated.get(term) == exact_reviewed_value:
            # A complete, source-keyed GPT review is the final authority. Avoid
            # changing its value here only to restore it in the exact-value pass.
            continue
        if updated.get(term) != reviewed_value:
            updated[term] = reviewed_value
            replacement_count += 1
    heading = updated.get(ALARM_MANAGEMENT_HEADING, "").strip()
    rings_on = updated.get("Rings On", "").strip()
    if (
        updated.get(ALARM_MANAGEMENT_HEADING)
        != reviewed_overlay.get(identifier, {}).get(ALARM_MANAGEMENT_HEADING)
        and heading
        and rings_on
        and rings_on.casefold() not in heading.casefold()
    ):
        # The old machine heading often interpreted "rings" as tones/sounds.
        # Use the exact shipping device-targeting label instead of preserving a
        # misleading prefix. The surrounding policy section supplies the
        # management context.
        updated[ALARM_MANAGEMENT_HEADING] = rings_on
        replacement_count += 1
    for source_value, translated in list(updated.items()):
        if source_value in ALARM_UI_TERMS or source_value == ALARM_MANAGEMENT_HEADING:
            continue
        if translated == reviewed_overlay.get(identifier, {}).get(source_value):
            continue
        referenced_terms = [
            term for term in ALARM_UI_TERMS if term in source_value
        ]
        if not referenced_terms or not (
            "Rings On" in source_value or "This Device" in source_value
        ):
            continue
        reconciled = translated.split(ALARM_TERM_FALLBACK_MARKER, 1)[0].rstrip()
        for term, previous_value in REVIEWED_ALARM_TERM_PREVIOUS_VALUES.get(
            identifier, {}
        ).items():
            reviewed_value = updated.get(term, "").strip()
            if previous_value and reviewed_value and previous_value in reconciled:
                reconciled = reconciled.replace(previous_value, reviewed_value)
        for term in referenced_terms:
            localized = embedded_alarm_term(updated.get(term, ""))
            if not localized:
                continue
            if term in reconciled and localized.casefold() not in reconciled.casefold():
                reconciled = reconciled.replace(term, localized)
        missing = [
            embedded_alarm_term(updated.get(term, ""))
            for term in referenced_terms
            if embedded_alarm_term(updated.get(term, "")).casefold()
            not in reconciled.casefold()
        ]
        if missing:
            # A machine draft may have paraphrased a status beyond safe lexical
            # replacement. Preserve the prose, then add the exact shipping UI
            # labels as a compact glossary so legal copy and app state cannot
            # diverge silently.
            reconciled = (
                reconciled.rstrip()
                + " "
                + ALARM_TERM_FALLBACK_MARKER
                + " "
                + "; ".join(missing)
            )
        if reconciled != translated:
            updated[source_value] = reconciled
            replacement_count += 1
    for old, new in REVIEWED_TRANSLATION_REPLACEMENTS.get(identifier, ()):
        for key, value in list(updated.items()):
            if key in reviewed_overlay.get(identifier, {}):
                # A source-keyed all-value review supersedes older fragment
                # rewrites. Applying the fragment first and restoring the
                # reviewed value later made deterministic replay report false
                # changes even though the final catalog was already current.
                continue
            occurrences = value.count(old)
            if occurrences:
                updated[key] = value.replace(old, new)
                replacement_count += occurrences

    for source_fragment, expected_fragment in REVIEWED_TRANSLATION_CORRECTIONS.get(
        identifier, {}
    ).items():
        matching_keys = [key for key in source if source_fragment in key]
        if not matching_keys:
            # Keep historical review artifacts intact without restoring retired
            # copy or requiring it in the current source catalog.
            continue
        for key in matching_keys:
            if (
                key in reviewed_overlay.get(identifier, {})
                and source_fragment != key
            ):
                # The independently reviewed whole-value overlay supersedes
                # older fragment-level machine-draft repairs for this key.
                continue
            if key == source_fragment and updated.get(key) != expected_fragment:
                updated[key] = expected_fragment
                replacement_count += 1
            if expected_fragment not in updated.get(key, ""):
                raise RuntimeError(
                    f"Reviewed correction could not be applied for {identifier}: "
                    f"{source_fragment!r}"
                )
    return updated, replacement_count


def apply_reviewed_corrections(
    source: dict[str, str], translation_root: Path, locales: list[str]
) -> None:
    for locale in locales:
        translation_file = (
            translation_root / f"{locale}.lproj" / "Website.strings"
        )
        translations = load_strings(translation_file)
        corrected, replacement_count = reviewed_correction_values(
            source, translations, locale
        )
        if corrected != translations:
            translation_file.write_text(
                localized_strings_document(corrected), encoding="utf-8"
            )
        print(
            f"Applied {replacement_count} reviewed translation replacements "
            f"for {locale}."
        )


def replace_copy(soup: BeautifulSoup, translations: dict[str, str]) -> None:
    blocks = inline_translation_blocks(soup)
    block_ids = {id(tag) for tag in blocks}
    for tag in blocks:
        template, placeholders = inline_translation_template(tag)
        if template not in translations:
            continue
        fragment = restored_inline_translation(translations[template], placeholders)
        tag.clear()
        for child in list(fragment.contents):
            tag.append(child.extract())
    for node in list(soup.find_all(string=True)):
        if (
            isinstance(node, Doctype)
            or excluded_text_node(node)
            or node_within_blocks(node, block_ids)
        ):
            continue
        original = str(node)
        stripped = original.strip()
        if stripped not in translations:
            continue
        leading = original[: len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()) :]
        node.replace_with(leading + translations[stripped] + trailing)
    for tag in soup.find_all(True):
        for attribute in TRANSLATABLE_ATTRIBUTES:
            value = tag.get(attribute)
            if isinstance(value, str) and value in translations:
                tag[attribute] = translations[value]
        if has_translatable_meta_content(tag):
            value = tag.get("content")
            if isinstance(value, str) and value in translations:
                tag["content"] = translations[value]


def adjust_relative_references(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(True):
        for attribute in ("href", "src", "data-zoom"):
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
            href = (
                BASE_PRODUCT_URL
                if item["identifier"] == "en"
                else BASE_PRODUCT_URL + item["route"]
            )
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
        default_href = BASE_PRODUCT_URL
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
        f"            <summary>🌐 · {html_escape(native_name)}</summary>",
        f'            <div class="language-menu-list" aria-label="{html_escape(translated_label, quote=True)}">',
    ]
    for item in inventory:
        current = ' aria-current="page"' if item["identifier"] == locale else ""
        href = "../" if item["identifier"] == "en" else f'../{item["route"]}'
        lines.append(
            f'              <a href="{html_escape(href, quote=True)}" '
            f'lang="{html_escape(item["identifier"], quote=True)}"'
            f'{current}>{html_escape(item["nativeName"])}</a>'
        )
    lines.extend(["            </div>", "          </details>"])
    return "\n".join(lines)


def localize_owner_support_urls(document: str, locale: str) -> str:
    replacements = {
        "xintechllc.com/XTimers/support.html": (
            f"xintechllc.com/XTimers/{locale}/support.html"
        ),
    }
    for source, localized in replacements.items():
        document = document.replace(source, localized)
    return document


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
    document = localize_owner_support_urls(document, locale)
    if file_name == "index.html":
        document, count = MENU_PATTERN.subn(
            language_menu(inventory, locale, translations["Language"]),
            document,
            count=1,
        )
        if count != 1:
            raise RuntimeError(f"Expected one product language menu for {locale}")
    document = "\n".join(line.rstrip() for line in document.splitlines())
    return document.rstrip() + "\n"


def main() -> int:
    arguments = parse_arguments()
    if not any(
        (
            arguments.extract,
            arguments.import_existing,
            arguments.import_alarm_terms_from,
            arguments.generate,
            arguments.apply_reviewed_corrections,
            arguments.prune_obsolete_translations,
        )
    ):
        raise RuntimeError(
            "Choose --extract, --import-existing, --import-alarm-terms-from, "
            "--apply-reviewed-corrections, --prune-obsolete-translations, "
            "and/or --generate"
        )
    inventory_document = json.loads(arguments.inventory.read_text(encoding="utf-8"))
    inventory = inventory_document.get("localizations")
    if not isinstance(inventory, list) or len(inventory) != 45:
        raise RuntimeError("Website inventory must contain exactly 45 localizations")
    validate_inventory(inventory)

    source_values = extracted_values(arguments.root)
    if arguments.extract:
        arguments.source_strings.parent.mkdir(parents=True, exist_ok=True)
        arguments.source_strings.write_text(strings_document(source_values), encoding="utf-8")
        print(f"Extracted {len(source_values)} unique English website strings.")

    if arguments.prune_obsolete_translations:
        locales = arguments.locales or [
            item["identifier"] for item in inventory if item.get("identifier") != "en"
        ]
        for locale in locales:
            translation_file = (
                arguments.translation_root / f"{locale}.lproj" / "Website.strings"
            )
            translations = load_strings(translation_file)
            retained = {
                key: translations[key]
                for key in sorted(source_values)
                if key in translations
            }
            translation_file.write_text(
                localized_strings_document(retained), encoding="utf-8"
            )
            print(f"Pruned obsolete website translation keys for {locale}.")

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

    if arguments.import_alarm_terms_from:
        locales = arguments.locales or [
            item["identifier"] for item in inventory if item.get("identifier") != "en"
        ]
        import_alarm_terms(
            arguments.import_alarm_terms_from,
            arguments.translation_root,
            locales,
        )

    if arguments.apply_reviewed_corrections:
        locales = arguments.locales or [
            item["identifier"] for item in inventory if item.get("identifier") != "en"
        ]
        apply_reviewed_corrections(
            source_values,
            arguments.translation_root,
            locales,
        )

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
            print(f"Generated {len(SOURCE_PAGES)} unreviewed website pages for {locale}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
