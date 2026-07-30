# Intercloud Portal

Portal manajemen layanan cloud & data center **PT Intercloud Digital Inovasi** — satu aplikasi full-stack yang menggabungkan **client portal**, **billing otomatis**, **provisioning**, **NOC/network operations**, **CRM**, **CMS**, dan **pelaporan finance** dalam satu tempat.

Landing page publik + Client Portal + Admin Portal berjalan di satu deployment.

---

## Fitur Utama

### Client Portal (pelanggan)
- **Order layanan**: Cloud, VPS, Hosting, Colocation, Dedicated Server, Konektivitas — dengan opsi produk, add-on, dan kalkulasi PPN otomatis.
- **Billing**: invoice PDF, pembayaran online via **Duitku** (VA, e-wallet, QRIS) atau transfer bank, riwayat pembayaran, auto-renewal.
- **Support ticket** 24/7 dengan lampiran dan riwayat balasan.
- **Traffic report** live per layanan (sumber data MikroTik/SNMP).
- **Keamanan akun**: 2FA (TOTP), ganti password, riwayat login.

### Admin Portal (staff, multi-role)
- **Sales & Billing**: Orders, Quotations (konversi ke invoice), Invoices, Credit Notes (dengan preview PDF), Finance (cashflow, aset, ekspor PDF/Excel), dunning & suspensi otomatis.
- **Support & CRM**: Tickets, Customer DB, Follow-ups, Webmail (IMAP), Project Tracker, Documents.
- **Operations/NOC**: Provisioning (Proxmox/cPanel/Plesk live), MikroTik Ops (BGP, blackhole, looking glass), DCIM & IPAM, Diagnostics, NOC Monitor.
- **Creative & Marketing**: Landing CMS, Articles (SEO), Media Library, Content Calendar, UTM Builder, Form Builder (public forms + reCAPTCHA v3).
- **System**: Integrations hub (test koneksi live), Security (2FA, brute-force, audit), Backup & Restore, Branding, Public Status Page, User & hak akses menu per staf.
- **Pelaporan otomatis**: laporan bulanan (tagihan + trafik, arsip PDF/Excel dengan formula siap olah) & ringkasan mingguan (order baru, tiket terbuka, invoice jatuh tempo) ke email support.
- **Notifikasi**: lonceng admin dengan status baca (invoice overdue, provisioning pending/gagal, perangkat down, dll).

---

## Workflow Inti

```
Pelanggan order  →  Invoice terbit (PPN otomatis)  →  Bayar via Duitku / transfer
      →  Auto-provisioning (Proxmox clone VM / cPanel-Plesk create account)
      →  Email handover ke klien (IP, hostname, kredensial)
      →  Layanan aktif  →  Renewal & dunning otomatis  →  Suspensi bila menunggak
```

- Jika integrasi provisioning **belum aktif**, order masuk status **pending provisioning** + follow-up task & notifikasi admin — tidak pernah ada "sukses palsu".
- Tiket support, CRM follow-up (H+1 lead), dan email automation (welcome, invoice, reminder, handover) berjalan lewat scheduler internal.

### Jadwal Otomatis (APScheduler, timezone Asia/Jakarta)
| Jadwal | Tugas |
| --- | --- |
| Tiap jam (menit 50) | Sampling trafik MikroTik → grafik trafik klien |
| Harian | Dunning invoice, cek renewal/expiry, retensi log NOC |
| Tiap 5 menit | Monitor perangkat / DDoS indicator |
| Senin 07:00 WIB | Ringkasan mingguan ke email support |
| Tanggal 1, 06:30 WIB | Laporan bulanan (tagihan + trafik) + arsip PDF/Excel |

---

## Tech Stack

| Layer | Teknologi |
| --- | --- |
| Frontend | React 19 (CRA + CRACO), Tailwind CSS, shadcn/ui, lucide-react, Recharts |
| Backend | Python 3.11, FastAPI, Uvicorn, APScheduler |
| Database | MongoDB 8 (Motor async driver) |
| PDF / Excel | WeasyPrint, openpyxl (formula & format siap olah) |
| Auth & Security | JWT (bcrypt), TOTP 2FA (PyOTP), Google reCAPTCHA v3, rate-limit & audit log |
| Integrasi | Duitku (payment), Proxmox VE, cPanel/WHM, Plesk, DirectAdmin, MikroTik (librouteros), SMTP/IMAP, RNA.id (domain), WHOIS/Blacklist |
| Deployment | Ubuntu 24.04, Nginx (+ Let's Encrypt), Supervisor, UFW, fail2ban |

---

## Hak Akses (RBAC)

Akses menu & API mengikuti role + override `menu_keys` per user (Admin → Users → Manage access):

| Role | Cakupan utama |
| --- | --- |
| `admin` | Semua menu & konfigurasi sistem |
| `finance` | Invoices, Finance, Credit Notes, Orders, Quotations, laporan |
| `sales` | Orders, Quotations, Clients (scoped), CRM, UTM/Form Builder |
| `support` | Tickets, Services, Provisioning, NOC/MikroTik, DCIM |
| `creative` | CMS, Articles, Media Library, Content Calendar |
| `ticket_only` | Dashboard + Tickets saja |
| `client` | Client portal saja |

---

## Instalasi Production (Ubuntu 24.04)

Satu perintah — installer menyiapkan MongoDB 8 (dengan auth), Nginx + HTTPS (certbot), Supervisor, UFW, fail2ban, build frontend, dan seeding **satu user admin** (tanpa data demo):

```bash
wget -O install.sh https://raw.githubusercontent.com/PsychoX30/INTERCLOUD/main/scripts/install.sh
sudo bash install.sh
```

Opsi via environment variable (semua opsional):

| Variabel | Default | Keterangan |
| --- | --- | --- |
| `PORTAL_DOMAIN` | intercloud-digital.com | FQDN publik (untuk Nginx + SSL) |
| `LETSENCRYPT_EMAIL` | support@… | Email certbot |
| `ADMIN_EMAIL` | support@… | Email admin pertama |
| `ADMIN_PASSWORD` | *(random)* | Bila kosong: password acak dicetak SEKALI + wajib ganti saat login pertama |
| `REPO_URL` / `REPO_BRANCH` | repo ini / main | Sumber kode |
| `APP_DIR` | /opt/intercloud-portal | Lokasi instalasi |
| `EMERGENT_LLM_KEY` | *(kosong)* | Opsional, fitur AI |

Contoh:

```bash
sudo PORTAL_DOMAIN=portal.perusahaan.co.id \
     ADMIN_EMAIL=admin@perusahaan.co.id \
     bash install.sh
```

Setelah instalasi: login sebagai admin → **Admin → Integrations** untuk mengisi kredensial Duitku, Proxmox, panel hosting, MikroTik, SMTP (ada tombol *Test connection* & *Kirim email percobaan*), dan reCAPTCHA.

---

## Menjalankan untuk Development

```bash
# Backend (port 8001)
cd backend
pip install -r requirements.txt
cp .env.example .env   # isi MONGO_URL, DB_NAME, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend (port 3000)
cd frontend
yarn install
# .env: REACT_APP_BACKEND_URL=http://localhost:8001
yarn start
```

Semua endpoint API berada di bawah prefix **`/api/portal`**.

### Menjalankan test

```bash
cd backend
python -m pytest tests/ -q
```

> Catatan: reCAPTCHA v3 menolak login non-browser. Test suite menonaktifkannya otomatis via conftest; untuk pengujian manual, matikan sementara di koleksi `integration_settings`.

---

## Struktur Repo

```
├── backend/
│   ├── server.py               # Entrypoint FastAPI
│   ├── portal/
│   │   ├── routes.py           # Seluruh endpoint API (/api/portal/...)
│   │   ├── emails.py           # Template email + scheduler (dunning, laporan, trafik)
│   │   ├── integrations_v2.py  # Klien live: Proxmox, cPanel, Plesk, MikroTik, Duitku, SMTP/IMAP
│   │   ├── security.py, twofa.py, audit.py, backups.py, seed.py
│   └── tests/                  # Pytest suite (400+ test)
├── frontend/
│   └── src/pages/              # Landing, Client Portal, Admin Portal (React)
├── scripts/
│   ├── install.sh              # Installer production Ubuntu 24.04
│   └── backup.sh               # Backup harian (dipasang otomatis oleh installer)
└── memory/                     # Dokumen internal dev (di-gitignore sebagian)
```

---

## Keamanan

- Kredensial hanya di `.env` / database — **tidak pernah** di-commit (lihat `.gitignore`).
- Password admin production dibuat acak + wajib ganti saat login pertama.
- 2FA TOTP untuk semua akun, reCAPTCHA v3 pada login & form publik.
- Rate limiting, audit log, fail2ban, UFW, header keamanan Nginx (CSP) — dipasang otomatis oleh installer.
