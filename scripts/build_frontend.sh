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
# ATOMIC BUILD (2026-11-16)
# react-scripts menjalankan `fs.emptyDirSync(paths.appBuild)` SEBELUM kompilasi
# (react-scripts/scripts/build.js:72). Artinya build in-place menghapus
# index.html yang sedang dilayani nginx lebih dulu, lalu baru mulai compile.
# Kalau kompilasi gagal - dan itu benar-benar terjadi di produksi hari ini,
# karena build/ dipegang user lain sehingga rmdir kena EACCES - situs langsung
# mati dengan 404 sampai build berikutnya berhasil.
#
# Sekarang: build ke direktori sementara (BUILD_PATH), verifikasi di sana, baru
# tukar ke build/ setelah terbukti valid. Build yang gagal tidak menyentuh
# build/ yang sedang dipakai.
#
# Pemakaian:
#   scripts/build_frontend.sh              # build produksi penuh
#   scripts/build_frontend.sh --no-install # lewati npm ci
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_INSTALL=0
[[ "${1:-}" == "--no-install" ]] && SKIP_INSTALL=1

cd "$APP_DIR"

FE_DIR="$APP_DIR/frontend"
LIVE="$FE_DIR/build"
# Nama unik per proses: sisa build yang dimiliki user lain tidak boleh
# menggagalkan (atau lebih buruk, dianggap hasil) build ini.
STAGE="$FE_DIR/build.stage.$$"
PREV="$FE_DIR/build.prev.$$"

cleanup() {
    rm -rf "$STAGE" 2>/dev/null || true
    rm -rf "$PREV" 2>/dev/null || true
}
trap cleanup EXIT

# --- 0. Preflight ------------------------------------------------------------ #
# Lebih baik gagal SEKARANG, saat situs masih utuh, daripada gagal setelah
# direktori live sudah dikosongkan. Kedua temuan produksi hari ini (build/
# dimiliki user lain, build/ tidak bisa di-rename) tertangkap di sini.
if [[ -e "$LIVE" && ! -w "$LIVE" ]]; then
    echo "!! frontend/build ada tapi tidak bisa ditulis oleh $(id -un)." >&2
    echo "!! Pemilik sekarang: $(stat -c '%U:%G' "$LIVE" 2>/dev/null || echo '?')" >&2
    echo "!! Perbaiki dulu: sudo chown -R $(id -un):$(id -gn) $LIVE" >&2
    exit 1
fi
if [[ -e "$LIVE" && ! -w "$(dirname "$LIVE")" ]]; then
    echo "!! direktori frontend/ tidak bisa ditulis oleh $(id -un); swap atomik mustahil." >&2
    exit 1
fi

# --- 1. Bekukan versi -------------------------------------------------------- #
# Stempel dibekukan SEBELUM build supaya nomor build mengidentifikasi artefak
# yang dihasilkan, bukan momen file disentuh.
echo "==> stamping version"
python3 scripts/stamp_version.py --target backend

if [[ "$(id -u)" -eq 0 ]]; then
    chown intercloud:intercloud backend/.version.json 2>/dev/null || true
fi

# --- 2. Build ke direktori sementara ----------------------------------------- #
cd "$FE_DIR"
if [[ "$SKIP_INSTALL" -eq 0 ]]; then
    echo "==> npm ci"
    npm ci --legacy-peer-deps
fi

echo "==> craco build -> $(basename "$STAGE")"
# react-scripts membaca BUILD_PATH (config/paths.js:32). Digunakan sebagai
# path relatif terhadap frontend/, sama seperti default 'build'.
BUILD_PATH="$(basename "$STAGE")" npx --no-install craco build

# --- 3. Verifikasi di staging (bukan percaya exit code) --------------------- #
# Exit code 0 tidak membuktikan bundle baru. Yang membuktikan: index.html
# merujuk file yang benar-benar ada di disk. Kalau tidak, nginx akan membalas
# index.html untuk permintaan .js (status 200, content-type text/html) dan
# halaman diam-diam menjalankan bundle lama dari cache.
MAIN_JS=$(grep -oE 'static/js/main\.[a-f0-9]+\.js' "$STAGE/index.html" 2>/dev/null | head -1 || true)
if [[ -z "$MAIN_JS" ]]; then
    echo "!! staging terverifikasi GAGAL: index.html tidak merujuk bundle main.*.js" >&2
    exit 1
fi
if [[ ! -f "$STAGE/$MAIN_JS" ]]; then
    echo "!! staging terverifikasi GAGAL: bundle yang dirujuk tidak ada: $MAIN_JS" >&2
    exit 1
fi
if [[ ! -s "$STAGE/index.html" ]]; then
    echo "!! staging terverifikasi GAGAL: index.html kosong" >&2
    exit 1
fi

# --- 4. Swap atomik ---------------------------------------------------------- #
# Urutan mv/rename: hanya ada jendela mikrodetik di mana build/ tidak ada,
# bukan hitungan menit seperti build in-place.
if [[ -e "$LIVE" ]]; then
    mv "$LIVE" "$PREV"
fi
if ! mv "$STAGE" "$LIVE"; then
    echo "!! swap gagal, mengembalikan build sebelumnya" >&2
    [[ -e "$PREV" ]] && mv "$PREV" "$LIVE"
    exit 1
fi
rm -rf "$PREV"
trap - EXIT

# --- 5. Verifikasi ulang di lokasi live ------------------------------------- #
MAIN_LIVE=$(grep -oE 'static/js/main\.[a-f0-9]+\.js' "$LIVE/index.html" | head -1 || true)
if [[ "$MAIN_LIVE" != "$MAIN_JS" || ! -f "$LIVE/$MAIN_LIVE" ]]; then
    echo "!! setelah swap, build/index.html tidak konsisten ($MAIN_LIVE vs $MAIN_JS)" >&2
    exit 1
fi

LABEL=$(python3 -c 'import json;print(json.load(open("../backend/.version.json"))["label"])')
echo "==> build selesai (atomic)"
echo "    bundle : $MAIN_JS"
echo "    versi  : $LABEL"
echo "    (label ditampilkan dari API, bukan ditanam di bundle)"
