#!/usr/bin/env python3
"""Create display-only WebP renditions and a share card from approved PNGs.

Requires Pillow with WebP support. Originals and screenshot zoom targets are
never modified. The manifest records exact inputs and transfer-size comparisons.
"""
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'assets/marketing'
SIZES = {
    'mac-dark': [480, 960],
    'mac-timer-minimal-hidden': [320, 640],
    'mac-world-calendar-month': [240, 480],
    'mac-sound-ceremonial': [240, 480],
    'mac-planning-minimal-hidden-dolomites': [320, 658],
    'mac-report-week-daily-totals': [320, 640],
    'mac-menubar-status-planning': [320, 572],
}


def evidence(path):
    return {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    target = ASSETS / 'responsive'
    target.mkdir(exist_ok=True)
    manifest = {'format': 'lossless WebP after Lanczos resampling', 'originalsUnchanged': True, 'images': []}
    for name, widths in SIZES.items():
        original = ASSETS / f'{name}.png'
        image = Image.open(original).convert('RGBA')
        variants = []
        for width in widths:
            size = (width, round(image.height * width / image.width))
            resized = image.resize(size, Image.Resampling.LANCZOS)
            output = target / f'{name}-{width}.webp'
            resized.save(output, 'WEBP', lossless=True, method=6)
            variants.append({**evidence(output), 'width': width, 'height': size[1]})
        manifest['images'].append({'original': evidence(original), 'variants': variants})

    # A factual social card: genuine English Mac UI, with its release status.
    card = Image.new('RGB', (1200, 630), '#fbfaf7')
    draw = ImageDraw.Draw(card)
    font_path = '/System/Library/Fonts/Helvetica.ttc'
    regular = lambda size: ImageFont.truetype(font_path, size)
    icon = Image.open(ASSETS / 'app-icon.png').convert('RGBA').resize((76, 76), Image.Resampling.LANCZOS)
    card.paste(icon, (58, 56), icon)
    draw.text((150, 70), 'XTimers', font=regular(42), fill='#163d67')
    draw.text((60, 180), 'Timers.', font=regular(54), fill='#086ce9')
    draw.text((60, 244), 'Countdowns.', font=regular(54), fill='#8850da')
    draw.text((60, 308), 'Your workspace.', font=regular(48), fill='#c32b77')
    draw.text((62, 436), 'Mac 3.4 available now', font=regular(25), fill='#3e526c')
    draw.text((62, 478), 'Mac 3.5 preview shown', font=regular(21), fill='#647181')
    draw.text((62, 563), 'xintechllc.com/XTimers', font=regular(21), fill='#647181')
    workspace = Image.open(ASSETS / 'mac-dark.png').convert('RGBA')
    workspace = workspace.resize((650, round(workspace.height * 650 / workspace.width)), Image.Resampling.LANCZOS)
    card.paste(workspace, (500, 103), workspace)
    timer = Image.open(ASSETS / 'mac-timer-minimal-hidden.png').convert('RGBA')
    timer = timer.resize((375, round(timer.height * 375 / timer.width)), Image.Resampling.LANCZOS)
    card.paste(timer, (770, 407), timer)
    share = ASSETS / 'xtimers-share.png'
    card.save(share, optimize=True)
    manifest['shareCard'] = {**evidence(share), 'width': 1200, 'height': 630, 'textLanguage': 'en', 'inputs': ['assets/marketing/app-icon.png', 'assets/marketing/mac-dark.png', 'assets/marketing/mac-timer-minimal-hidden.png']}
    original_bytes = sum(item['original']['bytes'] for item in manifest['images'])
    manifest['heroTransfer'] = {'originalPngBytes': original_bytes}
    for index, label in [(0, 'smallRenditions'), (1, 'largeRenditions')]:
        total = sum(item['variants'][index]['bytes'] for item in manifest['images'])
        manifest['heroTransfer'][label] = {'bytes': total, 'reductionPercent': round(100*(1-total/original_bytes), 1)}
    (ROOT / 'generated/MarketingMedia20260928.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['heroTransfer'], indent=2))


if __name__ == '__main__':
    main()
