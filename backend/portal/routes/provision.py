"""Provisioning engine: Proxmox settings/multi-server, cloud-init templates, SSH config, VM lifecycle, IP allocation.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from .. import models as m
from ..auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, get_current_admin, get_current_staff, get_current_content,
    require_roles, sales_can_access,
    STAFF_ROLES, FINANCE_ROLES, BILLING_ROLES, CATALOG_ROLES,
    OPS_ROLES, USER_MGMT_ROLES, TICKET_ROLES, CONTENT_ROLES,
)
from ..audit import log_audit, serialize as _serialize_audit
from ..secretbox import (dec_value as _sb_dec, enc_value as _sb_enc,
                         decrypt_config as _sb_dec_config)
from .. import integrations_v2 as iv2
from .shared import _get_db, _get_setting_value, _next_number, _now, _oid  # noqa: E402

router = APIRouter()


async def _proxmox_settings(db) -> Optional[dict]:
    """Resolve Proxmox settings dari `integration_settings` (iv2) atau fallback
    baris module-hub `integrations` (module=proxmox, status=enabled)."""
    s = await iv2.get_settings(db, "proxmox")
    if s and s.get("enabled") and (s.get("credentials") or {}).get("host"):
        return s
    row = await db.integrations.find_one({"module": "proxmox", "status": "enabled"})
    cfg = _sb_dec_config((row or {}).get("config") or {})
    if cfg.get("hostname"):
        proto = cfg.get("protocol") or "https"
        port = cfg.get("port") or 8006
        return {
            "provider": "proxmox",
            "enabled": True,
            "credentials": {"host": f"{proto}://{cfg['hostname']}:{port}",
                            "token_id": cfg.get("api_token_id"),
                            "token_secret": cfg.get("api_token_secret"),
                            "username": cfg.get("username"),
                            "password": cfg.get("password")},
            "options": {"default_node": cfg.get("default_node") or "", "ssl_verify": False},
        }
    # Fallback terakhir: server pertama dari registry multi-server
    doc = await db.proxmox_servers.find_one(
        {"enabled": {"$ne": False}, "host": {"$nin": [None, ""]}}, sort=[("sort_order", 1)])
    if doc:
        return _px_server_to_settings(doc)
    return None


# ---------------------------------------------------------------------------
# Multi-server Proxmox: registry (`proxmox_servers`) + resource-aware placement
# ---------------------------------------------------------------------------
def _px_server_to_settings(doc: dict) -> dict:
    return {
        "provider": "proxmox",
        "enabled": bool(doc.get("enabled", True)),
        "name": doc.get("name") or "Server",
        "server_id": str(doc.get("_id") or ""),
        "credentials": {"host": doc.get("host") or "",
                        "token_id": doc.get("token_id") or "",
                        "token_secret": _sb_dec(doc.get("token_secret") or ""),
                        "username": doc.get("username") or "",
                        "password": _sb_dec(doc.get("password") or "")},
        "options": {"default_node": doc.get("default_node") or "",
                    "default_storage": doc.get("default_storage") or "local-lvm",
                    "default_bridge": doc.get("default_bridge") or "vmbr0",
                    "clone_template_vmid": doc.get("clone_template_vmid"),
                    "ssl_verify": False},
    }


async def _proxmox_servers(db) -> list:
    """Semua server Proxmox aktif (multi-server). Bila registry `proxmox_servers`
    kosong, fallback ke konfigurasi tunggal legacy (Integrations)."""
    docs = await db.proxmox_servers.find({"enabled": {"$ne": False}}).sort("sort_order", 1).to_list(50)
    out = [_px_server_to_settings(d) for d in docs if d.get("host")]
    if out:
        return out
    legacy = await _proxmox_settings(db)
    if legacy:
        legacy = dict(legacy)
        legacy.setdefault("name", "Default")
        legacy.setdefault("server_id", "legacy")
        return [legacy]
    return []


async def _proxmox_settings_by_id(db, server_id: str) -> Optional[dict]:
    if not server_id or server_id == "legacy":
        return await _proxmox_settings(db)
    try:
        doc = await db.proxmox_servers.find_one({"_id": _oid(server_id)})
    except Exception:
        doc = None
    if doc:
        return _px_server_to_settings(doc)
    return await _proxmox_settings(db)


async def _proxmox_settings_for_service(db, svc: dict) -> Optional[dict]:
    """Settings server yang menaungi VM service ini (config.server_id), fallback legacy."""
    sid = ((svc.get("config") or {}).get("server_id") or "").strip()
    return await _proxmox_settings_by_id(db, sid)


async def _pick_proxmox_server(db, *, cores: int = 0, memory_mb: int = 0,
                               disk_gb: int = 0) -> tuple:
    """Resource-aware placement: pilih server+node dengan RAM bebas TERBANYAK
    yang muat spesifikasi (load-balance/spread). Return (settings, node, report)."""
    servers = await _proxmox_servers(db)
    report = []
    best = None  # (free_mem_mb, settings, node)
    for s in servers:
        px = iv2.ProxmoxClient(s)
        cap = await px.capacity()
        entry = {"server": s.get("name", ""), "server_id": s.get("server_id", ""),
                 "ok": cap.get("ok"), "error": cap.get("error"), "nodes": cap.get("nodes", [])}
        report.append(entry)
        if not cap.get("ok"):
            continue
        for n in cap["nodes"]:
            fits = (n["free_mem_mb"] >= memory_mb + 512 and
                    (not disk_gb or n["free_disk_gb"] >= disk_gb + 5) and
                    (not cores or n["cpus"] >= cores))
            n["fits"] = fits
            if fits and (best is None or n["free_mem_mb"] > best[0]):
                best = (n["free_mem_mb"], s, n["node"])
    if best:
        return best[1], best[2], report
    return None, None, report


async def _notify_admin_manual_provision(db, order: dict, note: str) -> None:
    """Create an internal follow-up task so admins act on orders that could
    not be auto-provisioned (integration off / live call failed)."""
    try:
        await db.followups.insert_one({
            "customer_id": None,
            "customer_name": order.get("user_name", ""),
            "task": (f"Provisioning manual diperlukan untuk order "
                     f"{order.get('number') or str(order['_id'])[-6:]}: {note}"),
            "channel": "internal",
            "due_date": datetime.now(timezone.utc).date().isoformat(),
            "done": False,
            "owner": "auto",
            "created_at": _now(),
        })
    except Exception:
        pass


def _selection_extras(prod: dict, selections: list) -> dict:
    """Extra resource (vCPU/RAM/Disk/IP) dari opsi konfigurasi yang dipilih klien."""
    extras = {"cores": 0.0, "memory_mb": 0.0, "disk_gb": 0.0, "ip": 0.0}
    groups = {g.get("key"): g for g in (prod.get("option_groups") or [])}
    for s in selections or []:
        g = groups.get(s.get("group_key"))
        if not g:
            continue
        if g.get("type") == "quantity":
            kind = g.get("resource_kind")
            qty = float(s.get("quantity") or 0)
            per = float(g.get("resource_per_unit") or 0)
            if kind in extras and qty and per:
                extras[kind] += qty * per
        else:
            opts = {o.get("label"): o for o in (g.get("options") or [])}
            for lbl in (s.get("option_labels") or []):
                o = opts.get(lbl)
                if o and o.get("resource_kind") in extras and o.get("resource_amount"):
                    extras[o["resource_kind"]] += float(o["resource_amount"])
    return extras


def _match_whm_package(requested: Optional[str], available: list) -> Optional[str]:
    """Resolve a catalog package to the actual WHM package name.

    Reseller-owned packages are commonly prefixed by WHM (for example,
    ``reseller_starter``). Exact matches win. A suffix match is accepted only
    at an underscore boundary and only when it is unambiguous.
    """
    want = str(requested or "").strip().lower()
    packages = [str(p).strip() for p in (available or []) if str(p).strip()]
    if not want or not packages:
        return None
    exact = [p for p in packages if p.lower() == want]
    if exact:
        return exact[0]
    suffix = [p for p in packages if p.lower().endswith("_" + want)]
    return suffix[0] if len(suffix) == 1 else None


def _resolve_hosting_config(prod: dict, order_cfg: dict) -> dict:
    """Build the stable hosting provisioning contract from product + order.

    Product defaults live in ``product.provision``. Per-order ``package`` and
    ``domain`` remain supported for backwards compatibility.
    """
    provision = prod.get("provision") if isinstance(prod.get("provision"), dict) else {}
    cfg = order_cfg if isinstance(order_cfg, dict) else {}
    nameservers = provision.get("nameservers") or []
    if not isinstance(nameservers, list):
        nameservers = []
    return {
        "package": (cfg.get("package") or provision.get("package") or None),
        "domain": (cfg.get("domain") or "").strip(),
        "domain_policy": provision.get("domain_policy") or "subdomain",
        "subdomain_suffix": provision.get("subdomain_suffix") or "",
        "nameservers": [str(v).strip() for v in nameservers if str(v).strip()],
        "set_registrar_ns": provision.get("set_registrar_ns") is True,
    }


def _generate_whm_username(email: str) -> str:
    """Create a cPanel-compatible, deterministic base username (max 8 chars)."""
    local = str(email or "").split("@", 1)[0].lower()
    username = re.sub(r"[^a-z0-9]", "", local)[:8] or "icduser"
    if username[0].isdigit():
        username = "u" + username[:7]
    return username


async def _generate_unique_whm_username(cp, email: str, max_tries: int = 20) -> str:
    """Find an available WHM username without racing through arbitrary names."""
    base = _generate_whm_username(email)
    last_reason = "taken"
    for attempt in range(max_tries):
        suffix = "" if attempt == 0 else str(attempt)
        candidate = base[:8 - len(suffix)] + suffix
        result = await cp.verify_username(candidate)
        if result.get("available"):
            return candidate
        last_reason = result.get("reason") or last_reason
    raise RuntimeError(f"WHM username taken setelah {max_tries} percobaan: {last_reason}")


def _resolve_hosting_domain(hosting_cfg: dict, order_cfg: dict, *, username: str,
                            server_settings: dict) -> str:
    """Resolve and validate the account domain from the configured policy."""
    policy = hosting_cfg.get("domain_policy") or "subdomain"
    if policy == "customer_domain":
        domain = str((order_cfg or {}).get("domain") or hosting_cfg.get("domain") or "").strip().lower()
        if not domain:
            raise ValueError("customer domain required untuk produk hosting ini")
    elif policy == "subdomain":
        suffix = (hosting_cfg.get("subdomain_suffix") or
                  (server_settings.get("options") or {}).get("subdomain_suffix") or
                  "icd-cust.net")
        domain = f"{username}.{str(suffix).strip().strip('.').lower()}"
    else:
        raise ValueError(f"domain policy tidak didukung: {policy}")
    if (len(domain) > 253 or not re.fullmatch(
            r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", domain)):
        raise ValueError("domain hosting tidak valid")
    return domain


async def _order_resource_extras(db, order: dict, prod: dict) -> dict:
    """Total extra resource order: opsi konfigurasi + add-on (field provision add-on)."""
    extras = _selection_extras(prod, order.get("selections") or [])
    if order.get("addon_ids"):
        addons = await db.products.find({"_id": {"$in": order["addon_ids"]}}).to_list(50)
        for a in addons:
            ap = a.get("provision") or {}
            extras["cores"] += float(ap.get("cores") or 0)
            extras["memory_mb"] += float(ap.get("memory_mb") or 0)
            extras["disk_gb"] += float(ap.get("disk_gb") or 0)
            extras["ip"] += float(ap.get("ip") or 0)
    return {k: int(v) for k, v in extras.items()}


async def _maybe_update_rna_ns(db, order: dict, domain: str, nameservers: list) -> None:
    """If nameservers are provided and the customer's domain is registered via
    RNA.id, push those nameservers to the registrar (best-effort).

    Called after a hosting account is successfully created. Never raises: the
    hosting account already exists and must not be marked failed if the
    registrar NS update fails. Writes its own provision_log entries directly.
    """
    if not nameservers:
        return
    user_id = order.get("user_id")
    if not domain or not user_id:
        return
    s = await iv2.get_settings(db, "rna")
    if not s or not s.get("enabled"):
        await _order_log(db, order, "rna_ns_skipped", "Integrasi RNA.id tidak aktif.")
        return
    try:
        user_oid = ObjectId(user_id)
    except Exception:
        user_oid = user_id
    dom = await db.domains.find_one({"domain": domain, "user_id": user_oid})
    if not dom:
        await _order_log(db, order, "rna_ns_skipped",
                         f"Domain {domain} tidak ditemukan di RNA (registrar eksternal).")
        return
    order_ref = dom.get("order_ref")
    if not order_ref:
        await _order_log(db, order, "rna_ns_skipped",
                         f"Domain {domain} belum punya order_ref RNA.")
        return
    rna = iv2.RdashClient(s)
    try:
        await rna.update_ns(order_ref, list(nameservers))
        await _order_log(db, order, "rna_ns_updated",
                         f"Nameserver {', '.join(nameservers)} di-update via RNA untuk {domain}.")
    except Exception as e:
        await _order_log(db, order, "rna_ns_error",
                         f"Gagal update nameserver RNA untuk {domain}: {str(e)[:150]}")


async def _order_log(db, order: dict, step: str, msg: str) -> None:
    """Append a provision_log entry for an order."""
    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$push": {"provision_log": {"at": _now(), "step": step, "message": msg}}},
    )


async def _auto_provision(db, order: dict) -> dict:
    """Run auto-provisioning based on product category.
    Uses LIVE integration APIs (cPanel/Plesk/DirectAdmin/Proxmox) when they are
    enabled under /admin/integrations. When no live integration is available the
    service is created in `pending` state and an admin follow-up task is raised -
    no fake/mock success is ever recorded.
    """
    prod = await db.products.find_one({"_id": order["product_id"]})
    if not prod:
        return None
    cat = prod.get("category", "other")
    now = datetime.now(timezone.utc)
    cfg = dict(order.get("config", {}))

    # Append a provision log entry
    async def _log(step, msg):
        await db.orders.update_one(
            {"_id": order["_id"]},
            {"$push": {"provision_log": {"at": _now(), "step": step, "message": msg}}},
        )

    await _log("provisioning_started", f"Provisioning started for category '{cat}'.")

    # Spesifikasi dari opsi konfigurasi + add-on ikut dibawa ke service config
    sel_specs = {}
    for s in order.get("selections", []) or []:
        gk = s.get("group_key")
        if not gk:
            continue
        if s.get("option_labels"):
            sel_specs[gk] = s["option_labels"][0] if len(s["option_labels"]) == 1 else s["option_labels"]
        elif s.get("quantity") is not None:
            sel_specs[gk] = s["quantity"]
    if sel_specs:
        cfg.setdefault("selected_options", sel_specs)
    if order.get("addon_ids"):
        addon_docs = await db.products.find({"_id": {"$in": order["addon_ids"]}}).to_list(50)
        if addon_docs:
            cfg.setdefault("addons", [a.get("name", "") for a in addon_docs])
            await _log("addons_attached",
                       "Add-on terpasang: " + ", ".join(a.get("name", "") for a in addon_docs))

    hosting_credentials = None
    if cat in ("hosting",):
        # Live provisioning cPanel/Plesk/DirectAdmin bila integrasi aktif.
        hosting_cfg = _resolve_hosting_config(prod, cfg)
        _PANELS = [
            ("cpanel", "cPanel/WHM", iv2.CpanelClient, "package"),
            ("plesk", "Plesk", iv2.PleskClient, "plan"),
            ("directadmin", "DirectAdmin", iv2.DirectAdminClient, "package"),
        ]
        chosen = None
        for key, label, cls, pkg_kw in _PANELS:
            if key == "cpanel":
                # Multi-server WHM: pick best node via registry, fallback legacy
                pkg_name = hosting_cfg.get("package") or ""
                s, report = await _pick_cp_server(db, package_name=pkg_name)
                if s:
                    # Prefer the report row for the chosen node; fall back to any
                    # row that resolved a package, then to the requested name.
                    # Never silently fall through to None, which would make WHM
                    # apply its own default package.
                    resolved_pkg = (
                        next((r.get("resolved_package") for r in report
                              if r.get("server_id") == s.get("server_id")
                              and r.get("resolved_package")), None)
                        or next((r.get("resolved_package") for r in report
                                 if r.get("resolved_package")), None)
                        or (pkg_name or None)
                    )
                    chosen = (key, label, cls, pkg_kw, s, resolved_pkg)
                    break
            else:
                s = await iv2.get_settings(db, key)
                if s and s.get("enabled"):
                    chosen = (key, label, cls, pkg_kw, s, hosting_cfg.get("package"))
                    break
        if chosen:
            key, panel_label, cls, pkg_kw, settings, resolved_package = chosen
            panel_client = cls(settings)
            if key == "cpanel":
                uname = await _generate_unique_whm_username(panel_client, order["user_email"])
            else:
                uname = _generate_whm_username(order["user_email"])
            domain = _resolve_hosting_domain(hosting_cfg, cfg, username=uname,
                                             server_settings=settings)
            pw_alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%"
            password = "".join(secrets.choice(pw_alphabet) for _ in range(16))
            try:
                await panel_client.create_account(
                    domain=domain, username=uname, password=password,
                    contact_email=order["user_email"], **{pkg_kw: resolved_package})
                cfg.update({"control_panel": panel_label, "domain": domain,
                            "username": uname, "provision_status": "provisioned",
                            "provisioned_at": _now(),
                            "server_id": settings.get("server_id") or "",
                            "server_name": settings.get("name") or "",
                            "whm_package": resolved_package or "",
                            "nameservers": hosting_cfg.get("nameservers") or [],
                            "set_registrar_ns": hosting_cfg.get("set_registrar_ns") is True})
                await _log("panel_account_created",
                           f"{panel_label} account '{uname}' created for {domain} (live).")
                # Push nameservers to RNA.id if set_registrar_ns=True and domain is managed by RNA
                await _maybe_update_rna_ns(db, order, domain,
                                           hosting_cfg.get("nameservers") or [])
                bare_host = re.sub(r"^https?://", "", (settings.get("credentials") or {}).get("host") or "").split(":")[0].split("/")[0]
                panel_port = {"cpanel": 2083, "plesk": 8443, "directadmin": 2222}[key]
                hosting_credentials = {
                    "panel": panel_label, "domain": domain, "username": uname,
                    "password": password,
                    "panel_url": f"https://{bare_host}:{panel_port}" if bare_host else "",
                }
            except Exception as e:
                cfg.update({"control_panel": panel_label, "domain": domain,
                            "username": uname, "provision_status": "failed"})
                await _log("panel_account_failed",
                           f"{panel_label} provisioning gagal: {str(e)[:150]}. Perlu tindak lanjut manual.")
                await _notify_admin_manual_provision(
                    db, order, f"{panel_label} provisioning gagal: {str(e)[:120]}")
        else:
            cfg.setdefault("hostname", f"{order['user_email'].split('@')[0]}.icd-cust.net")
            pool = await _auto_allocate_customer_ip(db, hostname=cfg.get("hostname", ""),
                                                    customer=order.get("user_email", ""),
                                                    ref=f"order {str(order['_id'])[-6:]}")
            if pool:
                cfg.setdefault("ip", pool["ip"])
                await _log("ip_allocated", f"IP {pool['ip']} dialokasikan otomatis dari IP pool (DCIM).")
            cfg["provision_status"] = "pending"
            await _log("manual_provision_required",
                       "Integrasi panel hosting (cPanel/Plesk/DirectAdmin) belum aktif. "
                       "Provisioning manual oleh admin diperlukan.")
            await _notify_admin_manual_provision(
                db, order, "Integrasi panel hosting belum aktif - buat akun hosting manual")
    elif cat in ("vps", "cloud"):
        if cfg.get("os"):
            await _log("os_selected", f"OS dipilih klien saat order: {cfg['os']}.")
        cfg.setdefault("hostname", f"vm-{str(order['_id'])[-6:]}.icd-cust.net")
        pool = await _auto_allocate_customer_ip(db, hostname=cfg.get("hostname", ""),
                                                customer=order.get("user_email", ""),
                                                ref=f"order {str(order['_id'])[-6:]}",
                                                purpose="vps")
        if pool:
            cfg.setdefault("ip", pool["ip"])
            cfg["ip_prefixlen"] = pool["prefixlen"]
            cfg["ip_gateway"] = pool["gateway"]
            await _log("ip_allocated",
                       f"IP {pool['ip']}/{pool['prefixlen']} (gateway {pool['gateway']}) "
                       f"dialokasikan dari IP pool khusus VPS/Cloud ({pool['prefix']}).")
        else:
            await _log("ip_pool_empty",
                       "Tidak ada IP pool khusus VPS/Cloud dengan slot tersisa "
                       "(centang 'Untuk provisioning VPS/Cloud' di DCIM - IP Prefixes). VM memakai DHCP.")
        # IP tambahan yang dipesan klien (opsi konfigurasi / add-on)
        extras = await _order_resource_extras(db, order, prod)
        if extras.get("ip"):
            extra_ips = []
            for _ in range(int(extras["ip"])):
                p2 = await _auto_allocate_customer_ip(db, hostname=cfg.get("hostname", ""),
                                                      customer=order.get("user_email", ""),
                                                      ref=f"order {str(order['_id'])[-6:]} (extra)",
                                                      purpose="vps")
                if not p2:
                    break
                extra_ips.append(f"{p2['ip']}/{p2['prefixlen']}")
            if extra_ips:
                cfg["extra_ips"] = extra_ips
                await _log("extra_ip_allocated",
                           f"{len(extra_ips)} IP tambahan dialokasikan sesuai order: {', '.join(extra_ips)}.")
            if len(extra_ips) < int(extras["ip"]):
                await _log("extra_ip_shortage",
                           f"Hanya {len(extra_ips)} dari {int(extras['ip'])} IP tambahan yang tersedia di pool.")
        pxs = await _proxmox_servers(db)
        if pxs:
            cfg["provision_status"] = "provisioning"
            await _log("vm_queued",
                       "Provisioning VM Proxmox dijadwalkan - berjalan otomatis di background "
                       "(match template by OS, auto-build template bila belum ada, clone, set spek, start).")
        else:
            cfg["provision_status"] = "pending"
            await _log("manual_provision_required",
                       "Integrasi Proxmox belum aktif. VM harus dibuat manual oleh tim NOC.")
            await _notify_admin_manual_provision(
                db, order, "Integrasi Proxmox belum aktif - buat VM manual")
    elif cat in ("dedicated", "colocation", "interconnect", "firewall", "lease"):
        # These need manual DC/network setup - mark the service as provisioning
        cfg.setdefault("rack", "TBD by NOC")
        await _log("manual_setup_required", "Requires physical / network setup by NOC team.")
    else:
        await _log("manual_setup_required", "Category needs manual handling.")

    svc = {
        "user_id": order["user_id"],
        "product_id": prod["_id"],
        "product_name": prod["name"],
        "category": cat,
        "name": f"{prod['name']} - {order.get('user_name','')}",
        "status": "active" if cfg.get("provision_status") == "provisioned" else "pending",
        "start_date": now.date().isoformat(),
        "next_renewal": (now + timedelta(days=30)).date().isoformat(),
        "price_monthly": prod.get("price_monthly", 0),
        "config": cfg,
        "order_id": str(order["_id"]),
        "created_at": _now(),
    }
    sr = await db.services.insert_one(svc)
    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"service_id": sr.inserted_id, "status": "active" if svc["status"] == "active" else "provisioning"},
         "$push": {"provision_log": {"at": _now(), "step": "service_handover", "message": "Service delivered to client dashboard."}}},
    )
    if hosting_credentials:
        u = await db.users.find_one({"_id": order["user_id"]})
        if u:
            from portal import emails as _em
            try:
                await _em.on_hosting_provisioned(db, u, svc, hosting_credentials)
                await _log("credentials_emailed",
                           f"Detail akun hosting dikirim via email ke {u.get('email', '')}.")
            except Exception as e:
                await _log("credentials_email_failed", f"Gagal mengirim email detail akun: {str(e)[:120]}")
    if cat in ("vps", "cloud") and cfg.get("provision_status") == "provisioning":
        asyncio.create_task(_vps_provision_task(db, order["_id"], sr.inserted_id))
    return svc


async def _provision_order_from_invoice(db, inv: dict) -> bool:
    """Trigger auto-provisioning order tertaut saat invoice lunas (idempotent).
    Dipakai semua jalur invoice -> paid: admin mark-paid, webhook Duitku,
    dan pelunasan via credit note."""
    if not inv.get("order_id"):
        return False
    try:
        oid = _oid(str(inv["order_id"]))
    except Exception:
        return False
    order = await db.orders.find_one_and_update(
        {"_id": oid, "service_id": None, "provisioning_started": {"$ne": True}},
        {"$set": {"status": "payment_verified", "provisioning_started": True},
         "$push": {"provision_log": {"at": _now(), "step": "payment_verified",
                                     "message": f"Payment received for invoice {inv.get('number', '')}."}}})
    if not order:
        return False
    order = await db.orders.find_one({"_id": order["_id"]})
    await _auto_provision(db, order)
    return True


# ---------------------------------------------------------------------------
# VPS/Cloud auto-provisioning: OS catalog, template matching & auto-build
# ---------------------------------------------------------------------------
_CLOUD_IMAGE_CATALOG = [
    {"key": "ubuntu-22.04", "label": "Ubuntu 22.04 LTS", "family": "ubuntu",
     "url": "https://cloud-images.ubuntu.com/releases/jammy/release/ubuntu-22.04-server-cloudimg-amd64.img"},
    {"key": "ubuntu-24.04", "label": "Ubuntu 24.04 LTS", "family": "ubuntu",
     "url": "https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"},
    {"key": "debian-12", "label": "Debian 12 (Bookworm)", "family": "debian",
     "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2"},
    {"key": "almalinux-9", "label": "AlmaLinux 9", "family": "rhel",
     "url": "https://repo.almalinux.org/almalinux/9/cloud/x86_64/images/AlmaLinux-9-GenericCloud-latest.x86_64.qcow2"},
    {"key": "rocky-9", "label": "Rocky Linux 9", "family": "rhel",
     "url": "https://dl.rockylinux.org/pub/rocky/9/images/x86_64/Rocky-9-GenericCloud-Base.latest.x86_64.qcow2"},
    {"key": "centos-stream-9", "label": "CentOS Stream 9", "family": "rhel",
     "url": "https://cloud.centos.org/centos/9-stream/x86_64/images/CentOS-Stream-GenericCloud-9-latest.x86_64.qcow2"},
]


_OS_STOPWORDS = {"lts", "server", "live", "desktop", "amd64", "x86", "generic", "genericcloud",
                 "cloud", "cloudimg", "standard", "latest", "base", "edition", "std", "iso",
                 "img", "ci", "template", "linux", "bookworm", "jammy", "noble"}


def _os_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", (s or "").lower()).strip("-")


def _os_tokens(s: str) -> list:
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t and t not in _OS_STOPWORDS]


def _match_os_template(templates: list, os_choice: str):
    """Cari VM template Proxmox yang namanya cocok dengan OS pilihan klien."""
    want = _os_slug(os_choice)
    if not want:
        return None
    for t in templates or []:
        tn = _os_slug(t.get("name", ""))
        if tn and (want in tn or tn in want):
            return t
    wt = _os_tokens(os_choice)
    if not wt:
        return None
    for t in templates or []:
        tt = set(_os_tokens(t.get("name", "")))
        if tt and all(x in tt for x in wt):
            return t
    return None


def _match_iso(isos: list, os_choice: str):
    want = _os_slug(os_choice)
    if not want:
        return None
    for i in isos or []:
        n = _os_slug(i.get("name", ""))
        if n and (want in n or n in want):
            return i
    wt = _os_tokens(os_choice)
    if not wt:
        return None
    for i in isos or []:
        it = set(_os_tokens(i.get("name", "")))
        if it and all(x in it for x in wt):
            return i
    return None


def _catalog_entry_for(catalog: list, os_choice: str):
    want = _os_slug(os_choice)
    if not want:
        return None
    for c in catalog or []:
        ck = _os_slug(c.get("key", ""))
        if ck and (want == ck or ck in want or want in ck):
            return c
    wt = set(_os_tokens(os_choice))
    for c in catalog or []:
        ct = set(_os_tokens(c.get("key", "")) + _os_tokens(c.get("label", "")))
        if wt and ct and wt <= ct:
            return c
    return None


async def _get_os_catalog(db) -> list:
    val = await _get_setting_value(db, "os_cloud_images", None)
    return val if isinstance(val, list) and val else _CLOUD_IMAGE_CATALOG


async def _list_cluster_isos(px) -> list:
    """Semua ISO nyata dari seluruh storage/node cluster Proxmox."""
    out, seen = [], set()
    try:
        nodes = await px.list_nodes()
    except Exception:
        return out
    for n in nodes:
        node = n.get("node")
        try:
            storages = await px.list_storages(node)
        except Exception:
            continue
        for st in storages:
            if "iso" not in (st.get("content") or ""):
                continue
            try:
                for c in await px.storage_content(node, st["storage"], "iso"):
                    volid = c.get("volid", "")
                    fname = volid.split("/")[-1]
                    if fname and fname not in seen:
                        seen.add(fname)
                        out.append({"volid": volid, "name": fname,
                                    "node": node, "storage": st["storage"]})
            except Exception:
                continue
    return out


async def _build_os_options(db) -> dict:
    """Daftar OS REAL: template + ISO live dari Proxmox + katalog cloud image."""
    s = await _proxmox_settings(db)
    catalog = await _get_os_catalog(db)
    templates, isos, err = [], [], None
    if s:
        px = iv2.ProxmoxClient(s)
        try:
            templates = await px.list_templates()
            isos = await _list_cluster_isos(px)
        except Exception as e:
            err = str(e)[:150]
    else:
        err = "Integrasi Proxmox belum aktif"
    matched = set()
    options = []
    for c in catalog:
        tpl = _match_os_template(templates, c.get("key", ""))
        if tpl:
            matched.add(tpl["vmid"])
        options.append({"key": c["key"], "label": c.get("label", c["key"]),
                        "family": c.get("family", "linux"), "type": "cloud-init",
                        "ready": bool(tpl),
                        "note": (f"Template siap (VMID {tpl['vmid']})" if tpl
                                 else "Template dibuat OTOMATIS di server saat order pertama")})
    for t in templates:
        if t["vmid"] in matched:
            continue
        options.append({"key": t.get("name") or f"vmid-{t['vmid']}",
                        "label": f"{t.get('name') or t['vmid']} (template)",
                        "family": "template", "type": "template", "ready": True,
                        "note": f"Clone langsung dari template VMID {t['vmid']}"})
    for i in isos:
        options.append({"key": i["name"], "label": i["name"], "family": "iso",
                        "type": "iso", "ready": True,
                        "note": "VM dibuat + ISO terpasang - instalasi OS oleh NOC via console"})
    return {"online": bool(s) and not err, "error": err,
            "templates": templates, "isos": isos, "options": options}


# Skrip sshd yang diminta operasional. Ditulis sebagai drop-in ber-prefix "00-"
# agar MENANG atas bawaan cloud image (60-cloudimg-settings) - sshd memakai
# nilai pertama yang ditemukan (first-match) saat membaca /etc/ssh/sshd_config.d/*.
def _ssh_config_script(root_pw: str) -> str:
    return (
        "mkdir -p /etc/ssh/sshd_config.d; "
        "printf '%s\\n' 'PermitRootLogin yes' 'PasswordAuthentication yes' "
        "'MaxAuthTries 10' 'MaxSessions 6' 'Port 22' 'ListenAddress 0.0.0.0' "
        "> /etc/ssh/sshd_config.d/00-intercloud.conf; "
        f"echo 'root:{root_pw}' | chpasswd; "
        "systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || "
        "service ssh restart 2>/dev/null || service sshd restart 2>/dev/null || true"
    )


async def _get_provision_ssh_key(db) -> dict:
    """Keypair SSH milik portal untuk auto-config VM. Dibuat sekali & dipakai ulang."""
    doc = await db.settings.find_one({"key": "provision_ssh_key"})
    if doc and doc.get("private") and doc.get("public"):
        return {"private": doc["private"], "public": doc["public"]}
    import io as _io
    import paramiko as _pk
    k = _pk.RSAKey.generate(2048)
    buf = _io.StringIO()
    k.write_private_key(buf)
    priv = buf.getvalue()
    pub = f"{k.get_name()} {k.get_base64()} intercloud-portal"
    await db.settings.update_one(
        {"key": "provision_ssh_key"},
        {"$set": {"key": "provision_ssh_key", "private": priv, "public": pub, "created_at": _now()}},
        upsert=True)
    return {"private": priv, "public": pub}


def _ssh_pubkey_param(pub: str) -> str:
    """Nilai `sshkeys` untuk Proxmox cloud-init (harus URL-encoded)."""
    return quote(pub, safe="")


def _blocking_ssh_configure(ip: str, private_key_pem: str, root_pw: str) -> tuple:
    """Tunggu port 22, SSH sebagai root via key portal, konfigurasi sshd + set
    password root. Sinkron - dipanggil lewat asyncio.to_thread. Return (ok, msg)."""
    import io as _io
    import time as _time
    import socket as _socket
    import paramiko as _pk
    deadline = _time.time() + 210
    up = False
    while _time.time() < deadline:
        try:
            with _socket.create_connection((ip, 22), timeout=5):
                up = True
                break
        except Exception:
            _time.sleep(6)
    if not up:
        return (False, "port 22 tidak terbuka dalam ~3.5 menit")
    key = _pk.RSAKey.from_private_key(_io.StringIO(private_key_pem))
    cli = _pk.SSHClient()
    cli.set_missing_host_key_policy(_pk.AutoAddPolicy())
    last = None
    for _ in range(6):
        try:
            cli.connect(ip, port=22, username="root", pkey=key, timeout=10,
                        allow_agent=False, look_for_keys=False)
            last = None
            break
        except Exception as e:
            last = e
            _time.sleep(8)
    if last is not None:
        return (False, f"login SSH key gagal: {str(last)[:100]}")
    try:
        _stdin, stdout, _stderr = cli.exec_command(_ssh_config_script(root_pw), timeout=25)
        stdout.channel.recv_exit_status()
    finally:
        cli.close()
    return (True, "diterapkan")


async def _apply_ssh_config(db, ip, root_pw, log=None) -> bool:
    """Auto-config SSH VM baru: pasang PermitRootLogin yes, PasswordAuthentication
    yes, MaxAuthTries 10, MaxSessions 6, Port 22, ListenAddress 0.0.0.0 + set root pw.
    Best-effort: bila IP DHCP/tak terjangkau, provisioning tetap sukses."""
    ip = str(ip or "").split("/")[0].strip()
    if not ip or ip.upper() == "DHCP":
        if log:
            await log("ssh_config_skipped", "IP DHCP/tidak diketahui - SSH auto-config dilewati.")
        return False
    try:
        key = await _get_provision_ssh_key(db)
        ok, msg = await asyncio.to_thread(_blocking_ssh_configure, ip, key["private"], root_pw)
    except Exception as e:
        ok, msg = False, str(e)[:120]
    if log:
        if ok:
            await log("ssh_config_applied",
                      "SSH auto-config diterapkan (via key portal): PermitRootLogin yes, "
                      "PasswordAuthentication yes, MaxAuthTries 10, MaxSessions 6, Port 22, "
                      "ListenAddress 0.0.0.0. Login root via password & key aktif.")
        else:
            await log("ssh_config_failed",
                      f"SSH auto-config dilewati: {msg}. VM & IP tetap aktif; login key portal "
                      "tetap terpasang via cloud-init.")
    return ok


async def _autobuild_ci_template(px, entry: dict) -> dict:
    """Bangun template cloud-init di Proxmox dari URL cloud image (sekali per OS,
    dipakai ulang untuk semua order berikutnya)."""
    nodes = [n.get("node") for n in await px.list_nodes()]
    if not nodes:
        raise RuntimeError("Tidak ada node Proxmox yang terlihat")
    node = px.default_node if px.default_node in nodes else nodes[0]
    storages = await px.list_storages(node)
    imp = next((s for s in storages if "import" in (s.get("content") or "").split(",")), None)
    if not imp:
        cand = next((s for s in storages if "iso" in (s.get("content") or "")), None)
        if not cand:
            raise RuntimeError(f"Tidak ada storage yang mendukung import/iso di node {node}")
        await px.enable_storage_content(cand["storage"], "import")
        imp = cand
    imp_storage = imp["storage"]
    fname = f"{_os_slug(entry['key'])}-cloudimg.qcow2"
    existing = await px.storage_content(node, imp_storage, "import")
    if not any(str(c.get("volid", "")).endswith("/" + fname) for c in existing):
        upid = await px.download_url(node, imp_storage, url=entry["url"],
                                     filename=fname, content="import")
        await px.wait_task(node, upid, timeout_s=1800, interval=8)
    rows = await px._get("/cluster/resources?type=vm") or []
    used = {int(r["vmid"]) for r in rows if r.get("vmid") is not None}
    tid = 9000
    while tid in used:
        tid += 1
    disk_storage = px.default_storage or "local-lvm"
    name = f"ci-{_os_slug(entry['key'])}"
    params = {"vmid": tid, "name": name, "memory": 2048, "cores": 2,
              "cpu": "x86-64-v2-AES",
              "net0": f"virtio,bridge={px.default_bridge or 'vmbr0'},firewall=1",
              "scsihw": "virtio-scsi-single",
              "scsi0": f"{disk_storage}:0,import-from={imp_storage}:import/{fname}",
              "ide2": f"{disk_storage}:cloudinit", "boot": "order=scsi0",
              "serial0": "socket", "vga": "serial0", "ostype": "l26", "agent": 1}
    upid = await px.create_vm(node, params)
    if isinstance(upid, str) and upid.startswith("UPID"):
        await px.wait_task(node, upid, timeout_s=900, interval=6)
    await px.make_template(node, tid)
    return {"vmid": tid, "node": node, "name": name}


async def _vps_provision_task(db, order_id, service_id) -> None:
    """Background VM provisioning: match/auto-build template by OS, clone,
    terapkan spesifikasi produk + cloud-init (root pw + IP pool), start VM."""
    from portal import emails as _em
    order = await db.orders.find_one({"_id": order_id})
    svc = await db.services.find_one({"_id": service_id})
    if not (order and svc):
        return

    async def _log(step, msg):
        await db.orders.update_one(
            {"_id": order_id},
            {"$push": {"provision_log": {"at": _now(), "step": step, "message": msg}}})

    async def _fail(msg):
        await db.services.update_one({"_id": service_id},
                                     {"$set": {"config.provision_status": "pending"}})
        await _log("vm_create_failed",
                   f"{msg} Perlu tindak lanjut manual - buat VM dengan hostname yang sama lalu "
                   "gunakan 'Verifikasi VM by Hostname' di detail service.")
        await _notify_admin_manual_provision(db, order, msg[:120])

    cfg = dict(svc.get("config") or {})
    prod = await db.products.find_one({"_id": svc["product_id"]}) or {}
    prov = prod.get("provision") or {}

    # Spesifikasi VM = setting produk (admin) + extra dari opsi/add-on order klien
    extras = await _order_resource_extras(db, order, prod)
    cores = (int(prov.get("cores") or 0) or int(cfg.get("cpu") or 0) or 2) + extras["cores"]
    memory_mb = ((int(prov.get("memory_mb") or 0)
                  or (int(float(cfg.get("ram_gb") or 0)) * 1024) or 2048) + extras["memory_mb"])
    base_disk = int(prov.get("disk_gb") or cfg.get("disk_gb") or 0)
    disk_gb = (base_disk + extras["disk_gb"]) if (base_disk or extras["disk_gb"]) else 0
    if any(extras.values()):
        await _log("spec_resolved",
                   f"Spek produk '{prod.get('name', '')}' + extra order: {cores} vCPU, {memory_mb} MB RAM"
                   f"{f', {disk_gb} GB disk' if disk_gb else ''} "
                   f"(extra: +{extras['cores']} vCPU, +{extras['memory_mb']} MB RAM, "
                   f"+{extras['disk_gb']} GB disk, +{extras['ip']} IP).")

    # Multi-server load balance: pilih server+node dengan RAM bebas TERBANYAK yang muat spek
    pxs, target_node, report = await _pick_proxmox_server(
        db, cores=cores, memory_mb=memory_mb, disk_gb=disk_gb)
    if not pxs:
        # Fallback: tidak ada node yang memenuhi spek penuh - pakai node paling lega yang online
        best = None
        for r in report:
            if not r.get("ok"):
                continue
            for n in r.get("nodes", []):
                if best is None or n["free_mem_mb"] > best[0]:
                    best = (n["free_mem_mb"], r.get("server_id") or "legacy", n["node"], r.get("server", ""))
        if best:
            srv = await _proxmox_settings_by_id(db, best[1])
            if srv:
                pxs, target_node = srv, best[2]
                await _log("capacity_warning",
                           f"Tidak ada node yang memenuhi spesifikasi penuh - memakai node paling lega "
                           f"'{best[2]}' ({best[0]} MB RAM bebas) di server '{best[3] or 'Default'}'.")
    if not pxs:
        details = "; ".join(f"{r.get('server') or 'Default'}: {r.get('error') or 'tidak terjangkau'}"
                            for r in report)
        await _fail(f"Tidak ada server Proxmox yang bisa dipakai. {details or 'Integrasi Proxmox belum aktif.'}")
        return
    px = iv2.ProxmoxClient(pxs)
    picked = next((n for r in report if (r.get("server_id") or "legacy") == (pxs.get("server_id") or "legacy")
                   for n in r.get("nodes", []) if n.get("node") == target_node), {})
    free_mb = picked.get("free_mem_mb")
    await _log("server_selected",
               f"Load-balance: server '{pxs.get('name', 'Default')}' node '{target_node}' dipilih dari "
               f"{len(report)} server terdaftar"
               + (f" (RAM bebas {free_mb} MB)." if free_mb is not None else "."))
    try:
        os_choice = str(cfg.get("os") or "").strip()
        templates = await px.list_templates()
        catalog = await _get_os_catalog(db)
        tpl = _match_os_template(templates, os_choice) if os_choice else None
        if tpl:
            await _log("template_matched",
                       f"Template '{tpl['name']}' (VMID {tpl['vmid']}) cocok dengan OS '{os_choice}'.")
        if not tpl and prov.get("template_vmid"):
            tpl = next((t for t in templates if int(t["vmid"]) == int(prov["template_vmid"])), None)
            if tpl:
                await _log("template_product",
                           f"Memakai template produk '{prod.get('name', '')}': {tpl['name']} (VMID {tpl['vmid']}).")
        if not tpl and os_choice:
            entry = _catalog_entry_for(catalog, os_choice)
            if entry:
                await _log("template_autobuild_started",
                           f"Template '{os_choice}' belum ada di server - membuat OTOMATIS dari cloud image "
                           f"{entry['url'].split('/')[-1]} (±3-10 menit, sekali saja - dipakai ulang order berikutnya).")
                tpl = await _autobuild_ci_template(px, entry)
                await _log("template_autobuild_done",
                           f"Template '{tpl['name']}' (VMID {tpl['vmid']}) selesai dibuat di node {tpl['node']}.")
        iso = None
        if not tpl and os_choice:
            iso = _match_iso(await _list_cluster_isos(px), os_choice)
        if not tpl and not iso and not os_choice and templates:
            tpl = (next((t for t in templates
                         if int(t["vmid"]) == int(px.clone_template_vmid or 0)), None)
                   or templates[0])
            await _log("template_default",
                       f"OS tidak dipilih - memakai template default {tpl['name']} (VMID {tpl['vmid']}).")

        vm_name = re.sub(r"[^a-zA-Z0-9-]", "-",
                         str(cfg.get("hostname") or f"vm-{str(order_id)[-6:]}")).strip("-")[:60]

        # Anti-duplikat: cek nama VM di SEMUA server Proxmox terdaftar
        for s_chk in await _proxmox_servers(db):
            try:
                dup = await iv2.ProxmoxClient(s_chk).find_vm_by_name(vm_name)
            except Exception:
                dup = None
            if dup:
                await _fail(f"VM bernama '{vm_name}' sudah ada (VMID {dup['vmid']} di {dup['node']}, "
                            f"server '{s_chk.get('name', 'Default')}') - tidak membuat duplikat.")
                return

        if tpl:
            vm = await px.clone_vm(hostname=vm_name, template_vmid=tpl["vmid"], node=target_node)
            await _log("vm_cloned",
                       f"VM {vm['vmid']} di-clone dari template '{tpl['name']}' di node {vm['node']} - "
                       "menunggu clone selesai.")
            # Tunggu TASK clone selesai dulu (config VM baru belum ada sebelum task
            # rampung -> polling status/current terlalu dini memicu error 500
            # "Configuration file does not exist").
            if vm.get("upid"):
                await px.wait_task(vm.get("src_node") or vm["node"], vm["upid"],
                                   timeout_s=1800, interval=6)
            await px.wait_unlock(vm["node"], vm["vmid"], timeout_s=900)
            root_pw = secrets.token_urlsafe(12)
            conf = {"cores": cores, "memory": memory_mb, "ciuser": "root",
                    "cipassword": root_pw, "nameserver": "8.8.8.8 1.1.1.1"}
            try:
                _pkey = await _get_provision_ssh_key(db)
                conf["sshkeys"] = _ssh_pubkey_param(_pkey["public"])
            except Exception:
                pass
            _ip = ""
            if cfg.get("ip") and cfg.get("ip_prefixlen"):
                # Proxmox menolak gateway/IP yang masih mengandung prefix CIDR
                # (mis. "157.20.32.177/28"). Bersihkan agar ipconfig0 valid.
                _ip = str(cfg["ip"]).split("/")[0].strip()
                _gw = str(cfg.get("ip_gateway", "")).split("/")[0].strip()
                conf["ipconfig0"] = f"ip={_ip}/{cfg['ip_prefixlen']}" + (f",gw={_gw}" if _gw else "")
            else:
                conf["ipconfig0"] = "ip=dhcp"
            await px.set_config(vm["node"], vm["vmid"], conf)
            await _log("vm_configured",
                       f"Spesifikasi diterapkan: {cores} vCPU, {memory_mb} MB RAM, "
                       f"cloud-init root + {conf['ipconfig0']}.")
            if disk_gb:
                try:
                    await px.resize_disk(vm["node"], vm["vmid"], "scsi0", f"{disk_gb}G")
                    await _log("vm_disk_resized", f"Disk utama di-resize ke {disk_gb} GB.")
                except Exception as e:
                    await _log("vm_disk_resize_skipped", f"Resize disk dilewati: {str(e)[:100]}")
            try:
                await px.vm_action(vm["node"], vm["vmid"], "start")
                await _log("vm_started", f"VM {vm['vmid']} dinyalakan otomatis.")
                # SSH auto-config berjalan di background (tunggu VM boot + cloud-init).
                asyncio.create_task(_apply_ssh_config(db, _ip, root_pw, _log))
            except Exception as e:
                await _log("vm_start_failed", f"VM gagal start otomatis: {str(e)[:100]}")
            upd = {"config.node": vm["node"], "config.vmid": vm["vmid"],
                   "config.server_id": pxs.get("server_id") or "legacy",
                   "config.server_name": pxs.get("name", ""),
                   "config.os": os_choice or tpl["name"],
                   "config.root_username": "root", "config.root_password": root_pw,
                   "config.credentials_applied": True, "config.cpu": cores,
                   "config.ram_gb": round(memory_mb / 1024, 1),
                   "config.provision_status": "provisioned",
                   "config.provisioned_at": _now(), "status": "active"}
            if disk_gb:
                upd["config.disk_gb"] = disk_gb
            await db.services.update_one({"_id": service_id}, {"$set": upd})
            await db.orders.update_one({"_id": order_id}, {"$set": {"status": "active"}})
            await _log("service_activated", f"VM {vm['vmid']} aktif - service diserahkan ke klien.")
            u = await db.users.find_one({"_id": order["user_id"]})
            if u:
                try:
                    svc2 = await db.services.find_one({"_id": service_id}) or svc
                    await _em.on_vm_provisioned(db, u, svc2, {
                        "hostname": cfg.get("hostname", vm_name),
                        "ip": cfg.get("ip") or "DHCP",
                        "os": os_choice or tpl["name"],
                        "vmid": vm["vmid"], "node": vm["node"],
                        "username": "root", "password": root_pw})
                    await _log("credentials_emailed",
                               f"Detail VM + kredensial dikirim via email ke {u.get('email', '')}.")
                except Exception as e:
                    await _log("credentials_email_failed",
                               f"Gagal mengirim email detail VM: {str(e)[:100]}")
        elif iso:
            nodes = [n.get("node") for n in await px.list_nodes()]
            node = iso.get("node") if iso.get("node") in nodes else \
                (target_node if target_node in nodes else
                 (px.default_node if px.default_node in nodes else (nodes[0] if nodes else "")))
            newid = await px.next_vmid()
            params = {"vmid": newid, "name": vm_name, "cores": cores, "memory": memory_mb,
                      "net0": f"virtio,bridge={px.default_bridge or 'vmbr0'},firewall=1",
                      "scsihw": "virtio-scsi-single",
                      "scsi0": f"{px.default_storage or 'local-lvm'}:{disk_gb or 40}",
                      "ide2": f"{iso['volid']},media=cdrom",
                      "boot": "order=ide2;scsi0", "ostype": "l26"}
            upid = await px.create_vm(node, params)
            if isinstance(upid, str) and upid.startswith("UPID"):
                await px.wait_task(node, upid, timeout_s=300)
            await db.services.update_one({"_id": service_id}, {"$set": {
                "config.node": node, "config.vmid": newid, "config.cpu": cores,
                "config.server_id": pxs.get("server_id") or "legacy",
                "config.server_name": pxs.get("name", ""),
                "config.ram_gb": round(memory_mb / 1024, 1),
                "config.disk_gb": disk_gb or 40,
                "config.provision_status": "pending"}})
            await _log("vm_created_iso",
                       f"VM {newid} dibuat di node {node} dengan ISO {iso['name']} terpasang "
                       f"({cores} vCPU / {memory_mb} MB / {disk_gb or 40} GB). OS ini belum punya "
                       "template cloud-init - NOC install OS via console lalu klik 'Verifikasi VM' untuk aktivasi.")
            await _notify_admin_manual_provision(
                db, order, f"Install OS manual via console: VM {newid} ({iso['name']})")
        else:
            await _fail(f"Tidak ada template, katalog cloud image, atau ISO yang cocok "
                        f"untuk OS '{os_choice or '-'}'.")
    except Exception as e:
        await _fail(f"Provisioning Proxmox gagal: {str(e)[:200]}.")


# ============================================================
# DCIM / IPAM (native, not via NetBox)
# ============================================================
async def _allocate_ip_from_pool(db, prefix_doc: dict, *, hostname: str = "",
                                 customer: str = "", description: str = "") -> str | None:
    """Ambil IP bebas berikutnya dari sebuah prefix DCIM dan catat di dcim_ips."""
    import ipaddress as _ip
    try:
        net = _ip.ip_network(prefix_doc.get("prefix", ""), strict=False)
    except ValueError:
        return None
    used_docs = await db.dcim_ips.find({"prefix_id": prefix_doc["_id"]}).to_list(5000)
    used = {d.get("address", "").split("/")[0] for d in used_docs}
    # Jangan pernah alokasikan gateway prefix. Untuk subnet non-/24 (mis. /28)
    # gateway bisa berakhiran selain .1, jadi harus dikecualikan eksplisit.
    gw = str(prefix_doc.get("gateway") or "").strip().split("/")[0]
    reserved = {str(r).split("/")[0] for r in (prefix_doc.get("reserved") or [])}
    if gw:
        reserved.add(gw)
    for host in net.hosts():
        a = str(host)
        if a == str(net.network_address) or a in reserved or a in used:
            continue
        await db.dcim_ips.insert_one({
            "address": a, "prefix_id": prefix_doc["_id"], "status": "allocated",
            "role": "customer", "hostname": hostname, "customer": customer,
            "description": description, "created_at": _now(),
        })
        await db.dcim_prefixes.update_one({"_id": prefix_doc["_id"]}, {"$inc": {"usage": 1}})
        return a
    return None


async def _auto_allocate_customer_ip(db, *, hostname: str, customer: str, ref: str,
                                     purpose: str | None = None) -> dict | None:
    """Pilih prefix IPv4 customer dengan slot tersisa, lalu alokasikan IP.

    purpose="vps": HANYA prefix ber-flag `vps_provision` (pool khusus VPS/Cloud).
    purpose None : prefix umum (pool khusus VPS/Cloud di-skip agar tidak terpakai)."""
    import ipaddress as _ip
    prefixes = await db.dcim_prefixes.find({"family": 4}).to_list(100)
    for p in prefixes:
        if purpose == "vps":
            if not p.get("vps_provision"):
                continue
        elif p.get("vps_provision"):
            continue
        if str(p.get("site", "")).lower() == "internal":
            continue
        if int(p.get("usage", 0)) >= int(p.get("capacity", 0)):
            continue
        ip = await _allocate_ip_from_pool(db, p, hostname=hostname, customer=customer,
                                          description=f"Auto-allocated for {ref}")
        if ip:
            try:
                net = _ip.ip_network(p.get("prefix", ""), strict=False)
                prefixlen = net.prefixlen
                # Buang prefix CIDR bila admin mengisi gateway sebagai "x.x.x.x/28".
                gateway = str(p.get("gateway") or "").strip().split("/")[0] or str(next(net.hosts()))
            except (ValueError, StopIteration):
                prefixlen, gateway = 24, ""
            return {"ip": ip, "prefixlen": prefixlen, "gateway": gateway,
                    "prefix": p.get("prefix", "")}
    return None


# ============================================================
# PROXMOX - available OS templates & OS request ticket bridge
# ============================================================
@router.get("/admin/proxmox/os-templates")
async def proxmox_os_templates(staff=Depends(get_current_staff)):
    """Return OS templates as would be reported by Proxmox ISO storage.
    Reads from an admin-editable settings doc; falls back to a common list."""
    db = await _get_db()
    doc = await db.settings.find_one({"key": "proxmox_os_templates"})
    if doc and doc.get("value"):
        return doc["value"]
    return [
        {"name": "Ubuntu 22.04 LTS Server", "family": "ubuntu", "type": "iso"},
        {"name": "Ubuntu 20.04 LTS Server", "family": "ubuntu", "type": "iso"},
        {"name": "Debian 12", "family": "debian", "type": "iso"},
        {"name": "AlmaLinux 9", "family": "rhel", "type": "iso"},
        {"name": "Rocky Linux 9", "family": "rhel", "type": "iso"},
        {"name": "CentOS Stream 9", "family": "rhel", "type": "iso"},
        {"name": "Windows Server 2022 Std", "family": "windows", "type": "iso"},
        {"name": "cloud-init/ubuntu-24.04-noble", "family": "ubuntu", "type": "template"},
        {"name": "cloud-init/debian-12", "family": "debian", "type": "template"},
    ]


@router.put("/admin/proxmox/os-templates")
async def proxmox_os_templates_set(payload: list, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.settings.update_one(
        {"key": "proxmox_os_templates"},
        {"$set": {"key": "proxmox_os_templates", "value": payload}},
        upsert=True,
    )
    return payload


@router.post("/client/proxmox/os-request")
async def client_request_os(payload: dict, user=Depends(get_current_user)):
    """Client requests an OS that isn't currently in the Proxmox library.
    Creates a ticket in the technical department."""
    db = await _get_db()
    os_name = (payload.get("os_name") or "").strip()
    if not os_name:
        raise HTTPException(status_code=400, detail="os_name is required")
    now = _now()
    number = await _next_number(db, "tickets", "TCK")
    subject = f"OS Provision Request: {os_name}"
    doc = {
        "user_id": ObjectId(user["id"]),
        "number": number,
        "subject": subject,
        "department": "technical",
        "priority": "medium",
        "status": "open",
        "replies": [{
            "author_id": user["id"], "author_name": user["name"], "author_role": "client",
            "message": f"Hi team, I'd like to request that '{os_name}' be added to the Proxmox ISO library. Additional notes: {payload.get('notes','-')}",
            "created_at": now,
        }],
        "created_at": now, "updated_at": now,
    }
    r = await db.tickets.insert_one(doc)
    return {"ticket_number": number, "ticket_id": str(r.inserted_id)}


# ---------------- Proxmox live actions ----------------
@router.get("/admin/proxmox/nodes")
async def proxmox_nodes(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).list_nodes()


@router.get("/admin/proxmox/vms")
async def proxmox_vms(node: Optional[str] = None, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).list_vms(node)


@router.post("/admin/proxmox/vms/{node}/{vmid}/{action}")
async def proxmox_vm_action(node: str, vmid: int, action: str, admin=Depends(get_current_admin)):
    if action not in ("start", "stop", "reboot", "shutdown", "suspend", "resume"):
        raise HTTPException(status_code=400, detail="Unsupported action")
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).vm_action(node, vmid, action)


@router.get("/admin/proxmox/vnc/{node}/{vmid}")
async def proxmox_vnc(node: str, vmid: int, admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    ticket = await iv2.ProxmoxClient(s).vnc_ticket(node, vmid)
    return {"ticket": ticket, "wss": f"{iv2.ProxmoxClient(s).host}/?console=kvm&novnc=1&vmid={vmid}&node={node}"}


@router.post("/admin/provisioning/proxmox/create")
async def admin_provision_proxmox_vm(payload: dict, admin=Depends(require_roles("admin", "support"))):
    """Manual VM provisioning di Proxmox LIVE: match template by OS, auto-build
    template cloud-init bila belum ada di server, atau buat VM + ISO terpasang.
    Menolak hostname yang sudah ada VM-nya (anti double-provision)."""
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400,
                            detail="Integrasi Proxmox belum aktif. Konfigurasi kredensial di Admin - Integrations terlebih dahulu.")
    hostname = (payload.get("hostname") or "").strip()
    if not hostname:
        raise HTTPException(status_code=400, detail="Hostname wajib diisi")
    vm_name = re.sub(r"[^a-zA-Z0-9-]", "-", hostname).strip("-")[:60]
    px = iv2.ProxmoxClient(s)
    try:
        dup = await px.find_vm_by_name(vm_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal terhubung ke Proxmox: {str(e)[:150]}")
    if dup:
        raise HTTPException(status_code=409,
                            detail=f"VM dengan hostname '{vm_name}' sudah ada (VMID {dup['vmid']} "
                                   f"di node {dup['node']}). Tidak membuat duplikat.")
    os_choice = str(payload.get("os") or "").strip()
    cores = int(payload.get("cores") or 2)
    memory_mb = int(payload.get("memory") or 2048)
    disk_gb = int(payload.get("disk") or 0)
    root_pw = secrets.token_urlsafe(12)

    async def _configure_and_start(node, vmid, upid=None, src_node=None):
        try:
            if upid:
                await px.wait_task(src_node or node, upid, timeout_s=1800, interval=6)
            await px.wait_unlock(node, vmid, timeout_s=900)
            conf = {
                "cores": cores, "memory": memory_mb, "ciuser": "root",
                "cipassword": root_pw, "nameserver": "8.8.8.8 1.1.1.1"}
            try:
                _pkey = await _get_provision_ssh_key(db)
                conf["sshkeys"] = _ssh_pubkey_param(_pkey["public"])
            except Exception:
                pass
            _ip = str(payload.get("ip") or "").split("/")[0].strip()
            _pl = payload.get("prefixlen") or payload.get("ip_prefixlen")
            if _ip and _pl:
                _gw = str(payload.get("gateway") or payload.get("ip_gateway") or "").split("/")[0].strip()
                conf["ipconfig0"] = f"ip={_ip}/{int(_pl)}" + (f",gw={_gw}" if _gw else "")
            else:
                conf["ipconfig0"] = "ip=dhcp"
            await px.set_config(node, vmid, conf)
            if disk_gb:
                try:
                    await px.resize_disk(node, vmid, "scsi0", f"{disk_gb}G")
                except Exception:
                    pass
            await px.vm_action(node, vmid, "start")
            await _apply_ssh_config(db, _ip, root_pw)
        except Exception:
            logging.getLogger("portal.provision").exception("manual VM %s post-config failed", vmid)

    try:
        templates = await px.list_templates()
        tpl = _match_os_template(templates, os_choice) if os_choice else None
        if not tpl and os_choice:
            entry = _catalog_entry_for(await _get_os_catalog(db), os_choice)
            if entry:
                async def _build_then_clone():
                    try:
                        t = await _autobuild_ci_template(px, entry)
                        vm = await px.clone_vm(hostname=vm_name, template_vmid=t["vmid"])
                        await _configure_and_start(vm["node"], vm["vmid"],
                                                   upid=vm.get("upid"), src_node=vm.get("src_node"))
                    except Exception:
                        logging.getLogger("portal.provision").exception(
                            "autobuild+clone gagal untuk %s", vm_name)
                asyncio.create_task(_build_then_clone())
                return {"ok": True, "building": True, "root_password": root_pw,
                        "message": (f"Template cloud-init '{os_choice}' belum ada - sedang DIBUAT OTOMATIS "
                                    f"di server (download image ±3-10 menit). VM '{vm_name}' akan di-clone, "
                                    f"dikonfigurasi ({cores} vCPU/{memory_mb} MB) dan di-start otomatis. "
                                    f"Password root: {root_pw}. Pantau progres di menu Proxmox VMs.")}
            iso = _match_iso(await _list_cluster_isos(px), os_choice)
            if iso:
                nodes = [n.get("node") for n in await px.list_nodes()]
                node = iso.get("node") if iso.get("node") in nodes else \
                    (px.default_node if px.default_node in nodes else (nodes[0] if nodes else ""))
                newid = await px.next_vmid()
                params = {"vmid": newid, "name": vm_name, "cores": cores, "memory": memory_mb,
                          "net0": f"virtio,bridge={px.default_bridge or 'vmbr0'},firewall=1",
                          "scsihw": "virtio-scsi-single",
                          "scsi0": f"{px.default_storage or 'local-lvm'}:{disk_gb or 40}",
                          "ide2": f"{iso['volid']},media=cdrom",
                          "boot": "order=ide2;scsi0", "ostype": "l26"}
                upid = await px.create_vm(node, params)
                if isinstance(upid, str) and upid.startswith("UPID"):
                    await px.wait_task(node, upid, timeout_s=300)
                return {"ok": True, "vmid": newid, "node": node, "name": vm_name, "iso": iso["name"],
                        "message": f"VM {newid} dibuat dengan ISO {iso['name']} terpasang - "
                                   "install OS via console (noVNC)."}
        if not tpl:
            tpl = (next((t for t in templates
                         if int(t["vmid"]) == int(px.clone_template_vmid or 0)), None)
                   or (templates[0] if templates else None))
        if not tpl:
            raise HTTPException(status_code=400,
                                detail=f"OS '{os_choice or '-'}' tidak cocok dengan template/ISO manapun "
                                       "di cluster dan tidak ada di katalog cloud image.")
        vm = await px.clone_vm(hostname=vm_name, template_vmid=tpl["vmid"],
                               node=(payload.get("node") or "").strip() or None)
        asyncio.create_task(_configure_and_start(vm["node"], vm["vmid"],
                                                 upid=vm.get("upid"), src_node=vm.get("src_node")))
        return {"ok": True, "vmid": vm["vmid"], "node": vm["node"], "name": vm["name"],
                "root_password": root_pw,
                "message": f"VM {vm['vmid']} di-clone dari template '{tpl.get('name', '')}' - "
                           f"konfigurasi ({cores} vCPU/{memory_mb} MB) + auto-start berjalan di background. "
                           f"Password root: {root_pw}."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Provisioning Proxmox gagal: {str(e)[:180]}")


@router.get("/admin/proxmox/os-options")
async def admin_proxmox_os_options(staff=Depends(require_roles("admin", "support"))):
    """Daftar OS REAL untuk provisioning: template + ISO live dari Proxmox
    production + katalog cloud image (auto-build)."""
    db = await _get_db()
    return await _build_os_options(db)


@router.get("/client/proxmox/os-options")
async def client_proxmox_os_options(user=Depends(get_current_user)):
    """Pilihan OS untuk order VPS/Cloud (tanpa detail infrastruktur)."""
    db = await _get_db()
    data = await _build_os_options(db)
    return {"online": data["online"], "options": data["options"]}


@router.post("/admin/services/{sid}/verify-vm")
async def admin_service_verify_vm(sid: str, payload: dict,
                                  staff=Depends(require_roles("admin", "support"))):
    """Verifikasi deployment manual by HOSTNAME: cari VM di cluster Proxmox
    dengan nama = hostname service, tautkan (node+VMID) dan aktifkan service."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    cfg = svc.get("config") or {}
    hostname = (payload.get("hostname") or cfg.get("hostname") or "").strip()
    if not hostname:
        raise HTTPException(status_code=400,
                            detail="Service tidak punya hostname - kirim field 'hostname' pada request.")
    vm_name = re.sub(r"[^a-zA-Z0-9-]", "-", hostname).strip("-")[:60]
    servers = await _proxmox_servers(db)
    if not servers:
        raise HTTPException(status_code=400, detail="Integrasi Proxmox belum aktif.")
    found, found_srv, last_err = None, None, None
    for s in servers:
        try:
            found = await iv2.ProxmoxClient(s).find_vm_by_name(vm_name)
        except Exception as e:
            last_err = str(e)[:150]
            found = None
        if found:
            found_srv = s
            break
    if not found:
        if last_err and len(servers) == 1:
            raise HTTPException(status_code=400, detail=f"Gagal terhubung ke Proxmox: {last_err}")
        raise HTTPException(status_code=404,
                            detail=f"Tidak ada VM bernama '{vm_name}' di {len(servers)} server terdaftar. "
                                   "Buat VM dengan nama persis itu di Proxmox, lalu klik verifikasi lagi.")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "config.hostname": hostname,
        "config.server_id": found_srv.get("server_id") or "legacy",
        "config.server_name": found_srv.get("name", ""),
        "config.node": found["node"], "config.vmid": found["vmid"],
        "config.provision_status": "provisioned", "config.provisioned_at": _now(),
        "status": "active"}})
    if svc.get("order_id"):
        try:
            await db.orders.update_one(
                {"_id": _oid(svc["order_id"])},
                {"$set": {"status": "active"},
                 "$push": {"provision_log": {
                     "at": _now(), "step": "vm_verified",
                     "message": f"VM '{vm_name}' diverifikasi manual by hostname oleh "
                                f"{staff.get('name', 'staff')}: VMID {found['vmid']} di node "
                                f"{found['node']} (status {found.get('status', '')}). Service diaktifkan."}}})
        except Exception:
            pass
    return {"ok": True, "vmid": found["vmid"], "node": found["node"],
            "vm_status": found.get("status", ""),
            "message": f"VM ditemukan: VMID {found['vmid']} di node {found['node']} "
                       f"(status {found.get('status', '')}). Service diaktifkan."}


@router.post("/admin/provisioning/hosting/create")
async def admin_provision_hosting_account(payload: dict, admin=Depends(require_roles("admin", "support"))):
    """Manually create a hosting account on the LIVE control panel (cPanel/
    Plesk/DirectAdmin). Fails clearly when no integration is enabled."""
    db = await _get_db()
    panels = {"cpanel": ("cPanel/WHM", iv2.CpanelClient, "package"),
              "plesk": ("Plesk", iv2.PleskClient, "plan"),
              "directadmin": ("DirectAdmin", iv2.DirectAdminClient, "package")}
    key = (payload.get("panel") or "").lower()
    if key not in panels:
        raise HTTPException(status_code=400, detail="panel harus cpanel / plesk / directadmin")
    s = await iv2.get_settings(db, key)
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400,
                            detail=f"Integrasi {panels[key][0]} belum aktif. Konfigurasi kredensial di Admin - Integrations terlebih dahulu.")
    for req in ("domain", "username", "password"):
        if not payload.get(req):
            raise HTTPException(status_code=400, detail=f"Field '{req}' wajib diisi")
    label, cls, pkg_kw = panels[key]
    try:
        await cls(s).create_account(domain=payload["domain"], username=payload["username"],
                                    password=payload["password"],
                                    contact_email=payload.get("contact_email", ""),
                                    **{pkg_kw: payload.get("plan") or None})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{label} provisioning gagal: {str(e)[:180]}")
    return {"ok": True, "panel": label, "domain": payload["domain"], "username": payload["username"]}


async def _hosting_service_for_lifecycle(db, sid: str) -> tuple:
    try:
        service_id = _oid(sid)
    except Exception:
        raise HTTPException(status_code=404, detail="Hosting service not found")
    svc = await db.services.find_one({"_id": service_id})
    if not svc:
        raise HTTPException(status_code=404, detail="Hosting service not found")
    if svc.get("category") != "hosting":
        raise HTTPException(status_code=400, detail="Service bukan layanan hosting")
    username = ((svc.get("config") or {}).get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username hosting belum tersimpan")
    settings = await _cp_settings_for_service(db, svc)
    if not settings:
        raise HTTPException(status_code=400, detail="WHM server untuk service ini tidak ditemukan")
    return svc, username, iv2.CpanelClient(settings)


@router.post("/admin/hosting/{sid}/suspend")
async def admin_hosting_suspend(sid: str, payload: dict,
                                admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    svc, username, cp = await _hosting_service_for_lifecycle(db, sid)
    reason = (payload.get("reason") or "Suspended by administrator").strip()
    try:
        await cp.suspend_account(username, reason)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WHM suspend gagal: {str(e)[:180]}")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "status": "suspended", "config.provision_status": "suspended",
        "config.suspended_at": _now(), "config.suspend_reason": reason}})
    return {"ok": True, "status": "suspended"}


@router.post("/admin/hosting/{sid}/unsuspend")
async def admin_hosting_unsuspend(sid: str, payload: dict = {},
                                  admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    svc, username, cp = await _hosting_service_for_lifecycle(db, sid)
    try:
        await cp.unsuspend_account(username)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WHM unsuspend gagal: {str(e)[:180]}")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "status": "active", "config.provision_status": "provisioned",
        "config.unsuspended_at": _now()}, "$unset": {"config.suspend_reason": ""}})
    return {"ok": True, "status": "active"}


@router.post("/admin/hosting/{sid}/terminate")
async def admin_hosting_terminate(sid: str, payload: dict,
                                  admin=Depends(require_roles("admin", "support"))):
    if payload.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="confirm=true wajib untuk terminasi permanen")
    db = await _get_db()
    svc, username, cp = await _hosting_service_for_lifecycle(db, sid)
    try:
        await cp.remove_account(username)
    except Exception as e:
        await db.services.update_one({"_id": svc["_id"]}, {"$set": {
            "config.provision_status": "termination_pending",
            "config.termination_error": str(e)[:180]}})
        raise HTTPException(status_code=502, detail=f"WHM terminate gagal: {str(e)[:180]}")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "status": "terminated", "config.provision_status": "terminated",
        "config.terminated_at": _now()}, "$unset": {"config.termination_error": ""}})
    return {"ok": True, "status": "terminated"}


@router.post("/admin/hosting/{sid}/password")
async def admin_hosting_password(sid: str, payload: dict,
                                 admin=Depends(require_roles("admin", "support"))):
    password = payload.get("new_password") or ""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password baru minimal 8 karakter")
    db = await _get_db()
    _svc, username, cp = await _hosting_service_for_lifecycle(db, sid)
    try:
        await cp.change_password(username, password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WHM password reset gagal: {str(e)[:180]}")
    return {"ok": True}


@router.post("/admin/hosting/{sid}/package")
async def admin_hosting_package(sid: str, payload: dict,
                                admin=Depends(require_roles("admin", "support"))):
    requested = (payload.get("package") or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="Package wajib diisi")
    db = await _get_db()
    svc, username, cp = await _hosting_service_for_lifecycle(db, sid)
    try:
        available = await cp.list_packages()
        resolved = _match_whm_package(requested, available)
        if not resolved:
            raise HTTPException(status_code=400, detail="Package tidak ditemukan atau ambigu di WHM server")
        await cp.change_package(username, resolved)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WHM package change gagal: {str(e)[:180]}")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "config.whm_package": resolved, "config.package_changed_at": _now()}})
    return {"ok": True, "package": resolved}


@router.get("/admin/proxmox/templates")
async def admin_proxmox_templates(admin=Depends(require_roles("admin", "support"))):
    """LIVE list of clone templates on the Proxmox cluster + the configured VMID."""
    db = await _get_db()
    s = await _proxmox_settings(db)
    if not s:
        raise HTTPException(status_code=400, detail="Integrasi Proxmox belum aktif.")
    try:
        templates = await iv2.ProxmoxClient(s).list_templates()
    except Exception as e:
        raise HTTPException(status_code=400,
                            detail=f"Gagal membaca template dari cluster: {str(e)[:150]}")
    cfg = (s.get("options") or {}).get("clone_template_vmid")
    try:
        cfg = int(cfg) if cfg else None
    except (TypeError, ValueError):
        cfg = None
    return {"templates": templates, "configured_vmid": cfg}


# ---------------- Multi-server Proxmox registry (admin) ----------------
def _px_server_public(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d.get("name", ""), "host": d.get("host", ""),
            "token_id": d.get("token_id", ""), "has_secret": bool(d.get("token_secret")),
            "username": d.get("username", ""), "has_password": bool(d.get("password")),
            "default_node": d.get("default_node", ""),
            "default_storage": d.get("default_storage", ""),
            "default_bridge": d.get("default_bridge", ""),
            "enabled": d.get("enabled", True) is not False,
            "sort_order": d.get("sort_order", 0),
            "created_at": d.get("created_at", "")}


# ---------------- Multi-server WHM/cPanel registry (admin) ----------------
def _cp_server_to_settings(doc: dict) -> dict:
    return {
        "provider": "cpanel",
        "enabled": bool(doc.get("enabled", True)),
        "name": doc.get("name") or "Server",
        "server_id": str(doc.get("_id") or ""),
        "credentials": {"host": doc.get("host") or "",
                        "username": doc.get("username") or "",
                        "api_token": _sb_dec(doc.get("api_token") or ""),
                        "password": _sb_dec(doc.get("password") or "")},
        "options": {"max_accounts": int(doc.get("max_accounts") or 0),
                    "ssl_verify": bool(doc.get("ssl_verify", True))},
    }


def _cp_server_public(d: dict) -> dict:
    return {"id": str(d["_id"]), "name": d.get("name", ""), "host": d.get("host", ""),
            "username": d.get("username", ""), "has_api_token": bool(d.get("api_token")),
            "has_password": bool(d.get("password")),
            "max_accounts": int(d.get("max_accounts") or 0),
            "ssl_verify": bool(d.get("ssl_verify", True)),
            "enabled": d.get("enabled", True) is not False,
            "sort_order": d.get("sort_order", 0),
            "created_at": d.get("created_at", "")}


async def _cp_servers(db) -> list:
    """Semua WHM server aktif (multi-server). Bila registry kosong, fallback ke
    konfigurasi tunggal legacy (Integrations)."""
    docs = await db.whm_servers.find({"enabled": {"$ne": False}}).sort("sort_order", 1).to_list(50)
    out = [_cp_server_to_settings(d) for d in docs if d.get("host")]
    if out:
        return out
    legacy = await iv2.get_settings(db, "cpanel")
    if legacy and legacy.get("enabled"):
        legacy = dict(legacy)
        legacy.setdefault("name", "Default")
        legacy.setdefault("server_id", "legacy")
        return [legacy]
    return []


async def _cp_settings_by_id(db, server_id: str) -> Optional[dict]:
    if not server_id or server_id == "legacy":
        return (await iv2.get_settings(db, "cpanel")) or None
    try:
        doc = await db.whm_servers.find_one({"_id": _oid(server_id)})
    except Exception:
        doc = None
    if doc:
        return _cp_server_to_settings(doc)
    return (await iv2.get_settings(db, "cpanel")) or None


async def _cp_settings_for_service(db, svc: dict) -> Optional[dict]:
    """Settings WHM server yang menaungi hosting service ini (config.server_id), fallback legacy."""
    sid = ((svc.get("config") or {}).get("server_id") or "").strip()
    return await _cp_settings_by_id(db, sid)


async def _pick_cp_server(db, *, package_name: str = "") -> tuple:
    """Placement: pilih WHM server aktif dengan slot terbanyak (max_accounts - current)
    yang memiliki package_name, tie-breaker loadavg five. Return (settings, report)."""
    servers = await _cp_servers(db)
    report = []
    best = None
    for s in servers:
        cp = iv2.CpanelClient(s)
        cap = await cp.capacity()
        max_acct = int((s.get("options") or {}).get("max_accounts") or 0)
        current = int(cap.get("accounts") or 0)
        slots = max_acct - current if max_acct > 0 else 999999
        resolved_pkg = (_match_whm_package(package_name, cap.get("packages", []))
                        if package_name else None)
        has_pkg = (not package_name) or bool(resolved_pkg)
        entry = {"server": s.get("name", ""), "server_id": s.get("server_id", ""),
                 "ok": cap.get("ok"), "error": cap.get("error"),
                 "accounts": current, "max_accounts": max_acct, "slots": slots,
                 "has_package": has_pkg, "resolved_package": resolved_pkg,
                 "loadavg": cap.get("loadavg", {})}
        report.append(entry)
        if not cap.get("ok") or slots <= 0 or not has_pkg:
            continue
        load_five = (cap.get("loadavg") or {}).get("five", 9999.0)
        score = (slots, -float(load_five))
        if best is None or score > best[0]:
            best = (score, s)
    if best:
        return best[1], report
    return None, report


@router.get("/admin/cpanel/servers")
async def admin_cp_servers_list(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.whm_servers.find({}).sort("sort_order", 1).to_list(100)
    return [_cp_server_public(d) for d in docs]


@router.get("/admin/cpanel/servers/capacity")
async def admin_cp_servers_capacity(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    s, report = await _pick_cp_server(db)
    best = None
    if s:
        best = {"server": s.get("name", ""), "server_id": s.get("server_id", "")}
    return {"best": best, "report": report}


@router.post("/admin/cpanel/servers")
async def admin_cp_servers_create(payload: dict, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    host = (payload.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Host URL wajib diisi")
    doc = {"name": (payload.get("name") or "").strip() or host,
           "host": host,
           "username": (payload.get("username") or "").strip(),
           "api_token": _sb_enc((payload.get("api_token") or "").strip()),
           "password": _sb_enc(payload.get("password") or ""),
           "max_accounts": int(payload.get("max_accounts") or 0),
           "ssl_verify": payload.get("ssl_verify", True) is not False,
           "enabled": payload.get("enabled", True) is not False,
           "sort_order": int(payload.get("sort_order") or 100),
           "created_at": _now()}
    r = await db.whm_servers.insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="cpanel_server.create", category="integrations",
                    target_type="cpanel_server", target_id=str(r.inserted_id),
                    target_label=doc["name"], request=request)
    return _cp_server_public(doc)


@router.put("/admin/cpanel/servers/{spid}")
async def admin_cp_servers_update(spid: str, payload: dict, request: Request,
                                  admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.whm_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    upd = {}
    for k in ("name", "host", "username"):
        if k in payload:
            upd[k] = (payload.get(k) or "").strip()
    if (payload.get("api_token") or "").strip():
        upd["api_token"] = _sb_enc(payload["api_token"].strip())
    if payload.get("password"):
        upd["password"] = _sb_enc(payload["password"])
    if "max_accounts" in payload:
        upd["max_accounts"] = int(payload.get("max_accounts") or 0)
    if "ssl_verify" in payload:
        upd["ssl_verify"] = payload.get("ssl_verify") is not False
    if "enabled" in payload:
        upd["enabled"] = payload.get("enabled") is not False
    if "sort_order" in payload:
        upd["sort_order"] = int(payload.get("sort_order") or 100)
    if upd.get("host") == "":
        raise HTTPException(status_code=400, detail="Host URL wajib diisi")
    await db.whm_servers.update_one({"_id": doc["_id"]}, {"$set": upd})
    doc = await db.whm_servers.find_one({"_id": doc["_id"]})
    await log_audit(db, actor=admin, action="cpanel_server.update", category="integrations",
                    target_type="cpanel_server", target_id=spid,
                    target_label=doc.get("name", ""), request=request)
    return _cp_server_public(doc)


@router.delete("/admin/cpanel/servers/{spid}")
async def admin_cp_servers_delete(spid: str, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.whm_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.whm_servers.delete_one({"_id": doc["_id"]})
    await log_audit(db, actor=admin, action="cpanel_server.delete", category="integrations",
                    target_type="cpanel_server", target_id=spid,
                    target_label=doc.get("name", ""), severity="warning", request=request)
    return {"ok": True}


@router.post("/admin/cpanel/servers/{spid}/test")
async def admin_cp_servers_test(spid: str, staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = await db.whm_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    cp = iv2.CpanelClient(_cp_server_to_settings(doc))
    res = await cp.test_connection()
    if not res.get("ok"):
        return {"ok": False, "message": res.get("message", "Connection failed")}
    cap = await cp.capacity()
    return {"ok": True, "message": res.get("message", "OK"),
            "accounts": cap.get("accounts"), "loadavg": cap.get("loadavg"),
            "packages": cap.get("packages")}


@router.get("/admin/cpanel/servers/{spid}/packages")
async def admin_cp_server_packages(spid: str, staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = await db.whm_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    cp = iv2.CpanelClient(_cp_server_to_settings(doc))
    try:
        packages = await cp.list_packages()
        return {"packages": packages}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])


@router.get("/admin/proxmox/servers")
async def admin_px_servers_list(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.proxmox_servers.find({}).sort("sort_order", 1).to_list(100)
    return [_px_server_public(d) for d in docs]


@router.get("/admin/proxmox/servers/capacity")
async def admin_px_servers_capacity(staff=Depends(require_roles("admin", "support"))):
    """Laporan kapasitas live semua server + node yang akan dipilih load balancer."""
    db = await _get_db()
    s, node, report = await _pick_proxmox_server(db)
    best = None
    if s and node:
        picked = next((n for r in report if (r.get("server_id") or "legacy") == (s.get("server_id") or "legacy")
                       for n in r.get("nodes", []) if n.get("node") == node), {})
        best = {"server": s.get("name", "Default"), "server_id": s.get("server_id") or "legacy",
                "node": node, "free_mem_mb": picked.get("free_mem_mb", 0)}
    return {"best": best, "report": report}


@router.post("/admin/proxmox/servers")
async def admin_px_servers_create(payload: dict, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    host = (payload.get("host") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Host URL wajib diisi")
    doc = {"name": (payload.get("name") or "").strip() or host,
           "host": host,
           "token_id": (payload.get("token_id") or "").strip(),
           "token_secret": _sb_enc((payload.get("token_secret") or "").strip()),
           "username": (payload.get("username") or "").strip(),
           "password": _sb_enc(payload.get("password") or ""),
           "default_node": (payload.get("default_node") or "").strip(),
           "default_storage": (payload.get("default_storage") or "").strip() or "local-lvm",
           "default_bridge": (payload.get("default_bridge") or "").strip() or "vmbr0",
           "enabled": payload.get("enabled", True) is not False,
           "sort_order": int(payload.get("sort_order") or 100),
           "created_at": _now()}
    r = await db.proxmox_servers.insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="proxmox_server.create", category="integrations",
                    target_type="proxmox_server", target_id=str(r.inserted_id),
                    target_label=doc["name"], request=request)
    return _px_server_public(doc)


@router.put("/admin/proxmox/servers/{spid}")
async def admin_px_servers_update(spid: str, payload: dict, request: Request,
                                  admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.proxmox_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    upd = {}
    for k in ("name", "host", "token_id", "username", "default_node",
              "default_storage", "default_bridge"):
        if k in payload:
            upd[k] = (payload.get(k) or "").strip()
    # Secret/password: kosong = pertahankan yang tersimpan
    if (payload.get("token_secret") or "").strip():
        upd["token_secret"] = _sb_enc(payload["token_secret"].strip())
    if payload.get("password"):
        upd["password"] = _sb_enc(payload["password"])
    if "enabled" in payload:
        upd["enabled"] = payload.get("enabled") is not False
    if "sort_order" in payload:
        upd["sort_order"] = int(payload.get("sort_order") or 100)
    if upd.get("host") == "":
        raise HTTPException(status_code=400, detail="Host URL wajib diisi")
    await db.proxmox_servers.update_one({"_id": doc["_id"]}, {"$set": upd})
    doc = await db.proxmox_servers.find_one({"_id": doc["_id"]})
    await log_audit(db, actor=admin, action="proxmox_server.update", category="integrations",
                    target_type="proxmox_server", target_id=spid,
                    target_label=doc.get("name", ""), request=request)
    return _px_server_public(doc)


@router.delete("/admin/proxmox/servers/{spid}")
async def admin_px_servers_delete(spid: str, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.proxmox_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.proxmox_servers.delete_one({"_id": doc["_id"]})
    await log_audit(db, actor=admin, action="proxmox_server.delete", category="integrations",
                    target_type="proxmox_server", target_id=spid,
                    target_label=doc.get("name", ""), severity="warning", request=request)
    return {"ok": True}


@router.post("/admin/proxmox/servers/{spid}/test")
async def admin_px_servers_test(spid: str, staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = await db.proxmox_servers.find_one({"_id": _oid(spid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Server not found")
    px = iv2.ProxmoxClient(_px_server_to_settings(doc))
    res = await px.test_connection()
    if not res.get("ok"):
        return {"ok": False, "message": res.get("message", "Connection failed"), "nodes": []}
    cap = await px.capacity()
    return {"ok": True, "message": res.get("message", "OK"), "nodes": cap.get("nodes", [])}
