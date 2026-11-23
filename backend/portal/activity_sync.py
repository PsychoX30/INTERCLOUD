"""Jembatan modul lain -> activity log.

Satu pekerjaan nyata (rapat, maintenance, konten terjadwal, follow-up klien)
harus muncul sekali di Activity, bukan sebagai empat daftar terpisah. Setiap
fungsi di sini best-effort: kegagalan sync TIDAK boleh menggagalkan operasi
asalnya (rapat tetap terbuat walau activity log error).
"""
import logging

log = logging.getLogger("portal.activity_sync")

COLL = "activities"


async def upsert_activity(
    db,
    *,
    source: str,
    source_id,
    title: str,
    kind: str = "other",
    status: str = "planned",
    scheduled_start=None,
    scheduled_end=None,
    location: str = "",
    description: str = "",
    owner_name: str = "",
    owner_id=None,
    customer_id=None,
    customer_name: str = "",
    source_label: str = "",
    link_url: str = "",
    actor_name: str = "",
    now: str | None = None,
) -> None:
    """Buat/perbarui satu baris aktivitas yang mewakili ``source``/``source_id``.

    Status ``done``/``cancelled`` tidak pernah diturunkan kembali oleh sync —
    hasil kerja manusia menang atas status jadwal.
    """
    if not source or source_id in (None, ""):
        return
    try:
        sid = str(source_id)
        filt = {"source": source, "source_id": sid}
        existing = await db[COLL].find_one(filt)
        fields = {
            "kind": kind,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "source_label": source_label,
            "link_url": link_url,
            "updated_at": now,
        }
        if description:
            fields["description"] = description
        if location:
            fields["location"] = location
        if owner_name:
            fields["owner_name"] = owner_name
        if owner_id:
            fields["owner_id"] = str(owner_id)
        if customer_id:
            fields["customer_id"] = str(customer_id)
        if customer_name:
            fields["customer_name"] = customer_name

        if not existing:
            doc = dict(fields)
            doc.update({
                "title": (title or "").strip()[:200] or source_label or "Aktivitas",
                "source": source,
                "source_id": sid,
                "status": status,
                "started_at": None,
                "ended_at": None,
                "created_by": "",
                "created_by_name": actor_name,
                "created_at": now,
            })
            await db[COLL].insert_one(doc)
            return

        fields["title"] = (title or "").strip()[:200] or existing.get("title") or source_label
        if existing.get("status") not in ("done", "cancelled"):
            fields["status"] = status
            if status == "in_progress" and not existing.get("started_at"):
                fields["started_at"] = now
            if status == "done":
                fields["started_at"] = existing.get("started_at") or now
                fields["ended_at"] = existing.get("ended_at") or now
        await db[COLL].update_one(filt, {"$set": fields})
    except Exception as exc:  # noqa: BLE001 - sync tidak boleh memutus alur asal
        log.warning("activity sync failed source=%s id=%s: %s", source, source_id, exc)


async def close_activity(db, *, source: str, source_id, now: str | None = None,
                         status: str = "done") -> None:
    """Tutup aktivitas yang terikat ke sumber (rapat berakhir, incident resolved)."""
    if not source or source_id in (None, ""):
        return
    try:
        filt = {"source": source, "source_id": str(source_id)}
        existing = await db[COLL].find_one(filt)
        if not existing:
            return
        fields = {"status": status, "updated_at": now}
        if status == "done":
            fields["started_at"] = existing.get("started_at") or now
            fields["ended_at"] = existing.get("ended_at") or now
        await db[COLL].update_one(filt, {"$set": fields})
    except Exception as exc:  # noqa: BLE001
        log.warning("activity close failed source=%s id=%s: %s", source, source_id, exc)


async def drop_activity(db, *, source: str, source_id) -> None:
    """Hapus aktivitas terikat saat sumbernya dihapus (hindari baris yatim)."""
    if not source or source_id in (None, ""):
        return
    try:
        await db[COLL].delete_many({"source": source, "source_id": str(source_id)})
    except Exception as exc:  # noqa: BLE001
        log.warning("activity drop failed source=%s id=%s: %s", source, source_id, exc)
