# Panduan Rotasi Kredensial & Pembersihan Git History

Konteks: arsip backup mongodump (`backups/*.archive.gz`) berisi secret live pernah ter-track
di git. File sudah di-untrack (`git rm --cached` + `.gitignore`), tetapi bila repo pernah
di-push ke remote (GitHub), secret masih bisa diekstrak dari HISTORY. Lakukan dua hal:
(A) rotasi semua kredensial yang terekspos, (B) purge history di remote.

---

## A. Rotasi Kredensial (urutan aman)

Rotasi dilakukan di sisi PENYEDIA dulu, lalu perbarui di portal:
Portal > Admin > Integrations (kartu per provider). Field secret yang dikosongkan
TIDAK menghapus nilai lama (merge-by-design); cukup isi nilai BARU lalu Save,
atau gunakan tombol hapus provider (DELETE) untuk reset bersih lalu isi ulang.

| # | Kredensial | Cara rotasi di penyedia | Update di portal |
|---|---|---|---|
| 1 | Proxmox API Token (`root@pam!...`) | Proxmox UI > Datacenter > Permissions > API Tokens: hapus token lama, buat token baru | Admin > Integrations > Proxmox VE (token_id + token_secret) DAN Admin > Integrations > kartu "Server Proxmox" (registry multi-server, edit tiap server) |
| 2 | Duitku Merchant API Key | Dashboard Duitku (dashboard.duitku.com) > Proyek Saya > regenerate API Key | Admin > Integrations > Duitku (api_key) |
| 3 | SMTP password | Panel email hosting/cPanel: ganti password mailbox pengirim | Admin > Integrations > SMTP (password) |
| 4 | reCAPTCHA v3 secret | console.cloud.google.com/security/recaptcha: buat site key baru (site+secret berpasangan, keduanya diganti) | Admin > Integrations > reCAPTCHA (site_key + secret_key) |
| 5 | RDASH / RNA.id API key | Dashboard RDASH: regenerate API key | Admin > Integrations > RNA.id |
| 6 | Password admin & staff portal | - | Portal > Settings > Change Password (semua akun staff yang ada di backup) |
| 7 | Password MongoDB produksi | Hanya jika `/etc/intercloud/mongo.env` ikut bocor (file ini TIDAK pernah di-commit). `db.updateUser` di mongosh + update `MONGO_URL` di `backend/.env`, restart backend | - |

Catatan `JWT_SECRET`: bila diganti, semua sesi login aktif logout (aman, tidak masalah).
PENTING sejak update ini: secret integrasi dienkripsi at-rest memakai `SETTINGS_ENC_KEY`
(fallback: derive dari `JWT_SECRET`). Jika server Anda BELUM punya `SETTINGS_ENC_KEY` di
`backend/.env` dan Anda mengganti `JWT_SECRET`, kredensial integrasi tersimpan tidak bisa
didekripsi lagi (field akan kosong) - cukup isi ulang via Admin > Integrations, ATAU
tambahkan dulu `SETTINGS_ENC_KEY` sebelum rotasi `JWT_SECRET` (lihat bagian C).

---

## B. Purge Git History (git filter-repo, disarankan)

Jalankan di mesin lokal (bukan server produksi). Semua kolaborator harus re-clone setelahnya.

```bash
pip install git-filter-repo            # atau: apt install git-filter-repo

# 1. Clone mirror BARU (filter-repo menolak clone kotor)
git clone --mirror git@github.com:USERNAME/REPO.git repo-purge
cd repo-purge

# 2. Hapus semua file sensitif dari SELURUH history
git filter-repo \
  --invert-paths \
  --path backups/ \
  --path backend/requirements.txt.new \
  --path-glob '*.archive.gz' \
  --path memory/test_credentials.md \
  --path backend/.env \
  --path frontend/.env

# 3. Force push history bersih
git push --force --mirror git@github.com:USERNAME/REPO.git
```

Alternatif BFG Repo-Cleaner:
```bash
java -jar bfg.jar --delete-files '*.archive.gz' repo-purge.git
java -jar bfg.jar --delete-folders backups repo-purge.git
cd repo-purge.git && git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

Setelah force push:
- Minta semua kolaborator hapus clone lama dan `git clone` ulang (JANGAN pull/merge).
- GitHub masih menyimpan cache view lama (commit via URL SHA & PR). Hubungi GitHub Support
  ("remove cached views / sensitive data removal") atau, paling tuntas: hapus repo dan
  buat repo baru lalu push history bersih.
- Di server produksi: `cd /opt/intercloud/app && git fetch origin && git reset --hard origin/main`
  (history lokal server ikut bersih).

Anggap SEMUA secret di history sudah bocor - purge TIDAK menggantikan rotasi (bagian A tetap wajib).

---

## C. Arsip Backup Lama & Enkripsi At-Rest

1. **Arsip backup lama = plaintext.** Semua `*.archive.gz` yang dibuat SEBELUM update ini
   berisi secret plaintext. Setelah rotasi kredensial selesai, hapus arsip lama di server
   (`/opt/intercloud/app/backups/` dan lokasi cron backup) atau pindahkan ke storage
   terenkripsi. Backup BARU otomatis berisi secret yang sudah terenkripsi (Fernet).
2. **Instalasi baru** (install.sh): `SETTINGS_ENC_KEY` digenerate otomatis di `backend/.env`.
3. **Server existing** (update via update.sh): tidak perlu aksi - kunci diturunkan dari
   `JWT_SECRET`. Untuk memisahkan kunci enkripsi dari kunci sesi (disarankan), tambahkan
   SEKARANG selagi data masih terbaca:
   ```bash
   echo "SETTINGS_ENC_KEY=\"$(openssl rand -base64 48 | tr -d '=+/' | head -c 48)\"" >> /opt/intercloud/app/backend/.env
   sudo supervisorctl restart intercloud-backend
   ```
   Dekripsi data lama tetap jalan (fallback JWT), penulisan baru memakai kunci baru.
   Simpan salinan `SETTINGS_ENC_KEY` di password manager - kunci hilang = kredensial
   integrasi harus diisi ulang manual.
4. **Restore backup ke server lain**: server tujuan harus punya `SETTINGS_ENC_KEY`
   (atau `JWT_SECRET`) yang SAMA dengan sumber agar secret terbaca. Jika tidak, field
   kredensial akan kosong dan cukup diisi ulang via Admin > Integrations.
