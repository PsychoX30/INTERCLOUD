#!/usr/bin/env python3
"""Bangkitkan metadata versi untuk INTERCLOUD.

Satu sumber kebenaran: file ``VERSION`` di root repo (mis. ``1.0.5``).

Stempel build memakai format yang diminta pemilik produk::

    V1.0.5 build(121120261406)

yaitu ``DDMMYYYYHHmm`` dalam **WIB (UTC+7)**, bukan waktu server. Stempel ini
dibekukan ke ``.version.json`` saat build supaya penomoran tidak berubah tiap
kali file disentuh -- nomor build harus mengidentifikasi ARTEFAK, bukan momen
pembacaan.

Label ``V1.0.5 build(121120261406)`` ditampilkan di UI lewat API, bukan
ditanam ke bundle: backend adalah satu-satunya sumber kebenaran versi.

Dipakai oleh:
- ``scripts/build_frontend.sh``  -> menulis ``backend/.version.json``
- ``backend/portal/routes/admin_core.py`` -> ``/admin/system/version`` (dibaca UI)

Jalankan manual:
    python3 scripts/stamp_version.py            # tulis backend/.version.json
    python3 scripts/stamp_version.py --print    # cetak saja, jangan tulis
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
BACKEND_STAMP = ROOT / "backend" / ".version.json"

WIB = timezone(timedelta(hours=7))
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def read_version() -> str:
    """Baca ``VERSION``. Gagal keras kalau formatnya bukan ``X.Y.Z``.

    Versi yang tidak valid lebih berbahaya daripada build yang gagal: ia
    diam-diam menyebar ke semua artefak dan baru ketahuan saat insiden.
    """
    if not VERSION_FILE.exists():
        raise SystemExit(f"VERSION tidak ditemukan di {VERSION_FILE}")
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not _SEMVER.match(raw):
        raise SystemExit(f"VERSION harus berformat X.Y.Z (mis. 1.0.5), dapat: {raw!r}")
    return raw


def git_sha() -> str:
    """SHA pendek HEAD, atau ``"unknown"`` kalau bukan repo / git tak ada."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_stamp(now: datetime | None = None) -> str:
    """Stempel ``DDMMYYYYHHmm`` waktu WIB."""
    return (now or datetime.now(WIB)).astimezone(WIB).strftime("%d%m%Y%H%M")


def semver_tuple(version: str) -> tuple[int, int, int]:
    """``1.0.5`` -> ``(1, 0, 5)``."""
    major, minor, patch = _SEMVER.match(version).groups()
    return int(major), int(minor), int(patch)


def build_metadata(now: datetime | None = None) -> dict:
    version = read_version()
    stamp = build_stamp(now)
    return {
        "version": version,
        "build": stamp,
        # Format yang diminta pemilik produk; jangan diubah tanpa persetujuan.
        "label": f"V{version} build({stamp})",
        "sha": git_sha(),
        "built_at_wib": (now or datetime.now(WIB)).astimezone(WIB).isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bangkitkan metadata versi INTERCLOUD")
    ap.add_argument("--print", dest="just_print", action="store_true",
                    help="cetak metadata, jangan menulis file")
    ap.add_argument("--target", choices=["backend", "both"], default="backend",
                    help="backend = backend/.version.json (dipakai UI lewat API)")
    args = ap.parse_args(argv)

    meta = build_metadata()

    if args.just_print:
        print(json.dumps(meta, indent=2))
        return 0

    BACKEND_STAMP.parent.mkdir(parents=True, exist_ok=True)
    BACKEND_STAMP.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"  {meta['label']}  ->  {BACKEND_STAMP.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
