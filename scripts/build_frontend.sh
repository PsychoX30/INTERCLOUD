#!/usr/bin/env bash
# Bangun bundle produksi frontend INTERCLOUD.
#
# Pakai craco (bukan react-scripts): craco.config.js mendefinisikan alias "@"
# yang tidak dikenal react-scripts, dan build akan gagal dengan
# "Can't resolve '@/index.css'".
#
# JANGAN set CI=true. Repo ini punya warning ESLint yang sudah lama ada; CI=true
# mengubahnya menjadi error dan build gagal padahal kode tidak berubah.
#
# Label versi TIDAK ditanam ke bundle. Frontend menampilkan versi dari
# GET /api/portal/admin/system/version, yang dibaca backend dari
# backend/.version.json. Menanam label di bundle berarti dua sumber kebenaran
# yang bisa berbeda; satu sumber (backend) lebih jujur.
#
# Pemakaian:
#   scripts/build_frontend.sh              # build produksi penuh
#   scripts/build_frontend.sh --no-install # lewati npm ci
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_INSTALL=0
[[ "${1:-}" == "--no-install" ]] && SKIP_INSTALL=1

cd "$APP_DIR"

# --- 1. Bekukan versi -------------------------------------------------------- #
# Stempel dibekukan SEBELUM build supaya nomor build mengidentifikasi artefak
# yang dihasilkan, bukan momen file disentuh.
echo "==> stamping version"
python3 scripts/stamp_version.py --target backend

if [[ "$(id -u)" -eq 0 ]]; then
    chown intercloud:intercloud backend/.version.json 2>/dev/null || true
fi

# --- 2. Build ---------------------------------------------------------------- #
cd "$APP_DIR/frontend"
if [[ "$SKIP_INSTALL" -eq 0 ]]; then
    echo "==> npm ci"
    npm ci --legacy-peer-deps
fi

echo "==> craco build"
npx --no-install craco build

# --- 3. Verifikasi (bukan percaya exit code) -------------------------------- #
# Exit code 0 tidak membuktikan bundle baru. Yang membuktikan: index.html
# merujuk file yang benar-benar ada di disk. Kalau tidak, nginx akan membalas
# index.html untuk permintaan .js (status 200, content-type text/html) dan
# halaman diam-diam menjalankan bundle lama dari cache.
cd "$APP_DIR/frontend"
MAIN_JS=$(grep -oE 'static/js/main\.[a-f0-9]+\.js' build/index.html | head -1 || true)
if [[ -z "$MAIN_JS" ]]; then
    echo "!! build/index.html tidak merujuk bundle main.*.js" >&2
    exit 1
fi
if [[ ! -f "build/$MAIN_JS" ]]; then
    echo "!! bundle yang dirujuk index.html tidak ada di disk: $MAIN_JS" >&2
    exit 1
fi

LABEL=$(python3 -c 'import json;print(json.load(open("../backend/.version.json"))["label"])')
echo "==> build selesai"
echo "    bundle : $MAIN_JS"
echo "    versi  : $LABEL"
echo "    (label ditampilkan dari API, bukan ditanam di bundle)"
