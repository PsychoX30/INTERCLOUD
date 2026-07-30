#!/usr/bin/env python3
"""Hapus akun uji (sales/regtest/pytest/example.com) + data terkaitnya.

Aman dijalankan di produksi: membaca MONGO_URL / DB_NAME dari backend/.env.
Default = DRY RUN (hanya melaporkan). Tambahkan --apply untuk benar-benar
menghapus, dan --purge-data untuk sekaligus menghapus invoice/order/service/
tiket/quotation/credit note/domain/CRM milik akun uji tsb.

Contoh:
    # lihat apa yang akan dihapus (tanpa mengubah apa pun)
    python3 scripts/cleanup-test-accounts.py

    # hapus akun uji saja
    python3 scripts/cleanup-test-accounts.py --apply

    # hapus akun uji + seluruh data miliknya (rekomendasi sebelum go-live)
    python3 scripts/cleanup-test-accounts.py --apply --purge-data
"""
import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

# Muat backend/.env (MONGO_URL, DB_NAME)
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND / ".env")
except Exception:
    pass

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Pola email akun uji (sintetis dari testing). Akun asli TIDAK cocok pola ini.
TEST_EMAIL_PATTERNS = [
    r"@example\.co",          # @example.com dan @example.co
    r"^regtest_",             # regtest_...@...
    r"^pytest\+",             # pytest+...@example.com
    r"^sales\d{6,}@",         # sales1784914257314@example.com
    r"^mailtest",             # mailtest-bare@...
    r"^inboxbare",            # inboxbare-unified@...
    r"^creative-test@",       # creative-test@intercloud-digital.com
]
TEST_RE = re.compile("|".join(TEST_EMAIL_PATTERNS), re.IGNORECASE)

# Akun yang WAJIB dipertahankan apa pun polanya (jaring pengaman).
PROTECTED_EMAILS = {
    "admin@intercloud-digital.com",
    "owner@intercloud-digital.com",
}

# Koleksi yang mereferensikan pemilik via field user_id.
OWNED_COLLECTIONS = [
    "invoices", "orders", "services", "tickets", "quotations",
    "credit_notes", "domains", "password_resets", "notification_reads",
    "crm_customers",
]


def is_test_email(email: str) -> bool:
    if not email:
        return False
    if email.lower() in PROTECTED_EMAILS:
        return False
    return bool(TEST_RE.search(email))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="benar-benar hapus (default: dry run)")
    ap.add_argument("--purge-data", action="store_true", help="hapus juga data milik akun uji")
    args = ap.parse_args()

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME tidak ditemukan di backend/.env")
        sys.exit(1)

    db = AsyncIOMotorClient(mongo_url)[db_name]

    from bson import ObjectId
    test_ids, keep = [], []
    async for u in db.users.find({}, {"email": 1, "role": 1}):
        (test_ids if is_test_email(u.get("email", "")) else keep).append(u)
    test_id_objs = [u["_id"] for u in test_ids]

    print("=" * 60)
    print(f"DB: {db_name}")
    print(f"Total users        : {len(test_ids) + len(keep)}")
    print(f"Akun uji (dihapus) : {len(test_ids)}")
    print(f"Akun dipertahankan : {len(keep)}")
    print("-" * 60)
    print("Dipertahankan:")
    for u in keep:
        print(f"  KEEP  {u.get('role',''):12} {u.get('email','')}")
    print("-" * 60)
    print("Contoh akun uji yang akan dihapus (maks 10):")
    for u in test_ids[:10]:
        print(f"  DEL   {u.get('role',''):12} {u.get('email','')}")
    if len(test_ids) > 10:
        print(f"  ... dan {len(test_ids) - 10} lainnya")

    # Hitung data milik akun uji
    if args.purge_data and test_id_objs:
        print("-" * 60)
        print("Data milik akun uji (akan dihapus dengan --purge-data):")
        for c in OWNED_COLLECTIONS:
            n = await db[c].count_documents({"user_id": {"$in": test_id_objs}})
            if n:
                print(f"  {c}: {n}")

    if not args.apply:
        print("=" * 60)
        print("DRY RUN - tidak ada yang diubah. Tambahkan --apply untuk menghapus.")
        return

    # Eksekusi hapus
    if args.purge_data and test_id_objs:
        for c in OWNED_COLLECTIONS:
            r = await db[c].delete_many({"user_id": {"$in": test_id_objs}})
            if r.deleted_count:
                print(f"  hapus {r.deleted_count} dari {c}")

    r = await db.users.delete_many({"_id": {"$in": test_id_objs}})
    print("=" * 60)
    print(f"SELESAI: {r.deleted_count} akun uji dihapus.")
    if args.purge_data:
        print("Data terkait akun uji juga sudah dibersihkan.")


if __name__ == "__main__":
    asyncio.run(main())
