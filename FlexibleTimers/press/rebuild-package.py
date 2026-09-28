#!/usr/bin/env python3
"""Package approved press assets locally; never download, publish, or alter media."""
from pathlib import Path
import hashlib
import json
import zipfile

press = Path(__file__).resolve().parent
kit = press / "kit"
manifest = json.loads((kit / "asset-manifest.json").read_text())
for asset in manifest["assets"]:
    path = kit / asset["file"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != asset["sha256"]:
        raise SystemExit(f"Approved asset hash mismatch: {asset['file']}")
files = sorted(p for p in kit.rglob("*") if p.is_file() and p.name != "checksums.sha256" and not p.name.startswith("."))
checksums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(kit)}\n" for p in files)
(kit / "checksums.sha256").write_text(checksums)
output = press / "downloads" / "xtimers-press-kit-2026-09-28.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in files + [kit / "checksums.sha256"]:
        entry = zipfile.ZipInfo("XTimers-Press-Kit/" + path.relative_to(kit).as_posix(), (2026, 9, 28, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        archive.writestr(entry, path.read_bytes())
print(f"{output.name}: {len(files) + 1} files, {output.stat().st_size:,} bytes")
