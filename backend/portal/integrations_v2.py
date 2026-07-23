"""Real integration adapters for Proxmox, Mikrotik and payment gateways.

All credentials are read on-demand from the `integration_settings` collection.
Each integration exposes a small stateless class with:
  - `test_connection()`  → dict with `{ok, message, details}`
  - domain-specific methods (list_nodes, provision_vm, list_bgp, create_payment, verify_webhook)

The order-flow calls `provision_vm` / `provision_hosting` when an invoice is
marked paid; if the corresponding integration is not configured, the
existing mocked auto-provisioning takes over and the order is flagged for
manual completion.
"""

from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import httpx


# ============================================================
# Settings helpers
# ============================================================
async def get_settings(db, provider: str) -> Optional[dict]:
    return await db.integration_settings.find_one({"provider": provider})


async def upsert_settings(db, provider: str, payload: dict) -> dict:
    from datetime import datetime, timezone
    doc = {**payload, "provider": provider, "updated_at": datetime.now(timezone.utc).isoformat()}
    doc.pop("_id", None)
    await db.integration_settings.update_one({"provider": provider}, {"$set": doc}, upsert=True)
    return doc


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    return s[:keep] + "*" * max(0, len(s) - keep)


def redact(settings: Optional[dict]) -> Optional[dict]:
    """Return a safe copy of settings for admin UI (secrets partially masked)."""
    if not settings:
        return None
    out = dict(settings)
    creds = dict(out.get("credentials") or {})
    for k in list(creds.keys()):
        if any(x in k.lower() for x in ("secret", "password", "key", "token", "api_key")) and creds[k]:
            creds[k + "_masked"] = _mask(creds[k])
            creds[k] = ""   # never send back the raw secret
    out["credentials"] = creds
    out.pop("_id", None)
    return out


# ============================================================
# Proxmox VE
# ============================================================
class ProxmoxClient:
    """Thin async Proxmox VE REST client (token auth).

    Settings shape:
      {
        provider: "proxmox",
        enabled: true,
        credentials: {
          host: "https://pve.example.com:8006",
          token_id: "root@pam!ic-portal",
          token_secret: "<uuid>",
          # OR user/password
          username: "root@pam",
          password: "...",
        },
        options: {
          default_node: "pve-jkt-01",
          default_storage: "local-lvm",
          default_bridge: "vmbr0",
          ssl_verify: false,
          clone_template_vmid: 9000,
        }
      }
    """

    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        o = settings.get("options") or {}
        self.host = (c.get("host") or "").rstrip("/")
        self.token_id = c.get("token_id")
        self.token_secret = c.get("token_secret")
        self.username = c.get("username")
        self.password = c.get("password")
        self.default_node = o.get("default_node") or ""
        self.default_storage = o.get("default_storage") or "local-lvm"
        self.default_bridge = o.get("default_bridge") or "vmbr0"
        self.clone_template_vmid = o.get("clone_template_vmid")
        self.ssl_verify = bool(o.get("ssl_verify", False))

    def _headers(self) -> Dict[str, str]:
        if self.token_id and self.token_secret:
            return {"Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"}
        return {}

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(timeout=30, verify=self.ssl_verify) as c:
            r = await c.get(f"{self.host}/api2/json{path}", headers=self._headers())
            r.raise_for_status()
            return r.json().get("data")

    async def _post(self, path: str, payload: dict) -> Any:
        async with httpx.AsyncClient(timeout=60, verify=self.ssl_verify) as c:
            r = await c.post(f"{self.host}/api2/json{path}", headers=self._headers(), data=payload)
            r.raise_for_status()
            return r.json().get("data")

    async def test_connection(self) -> dict:
        try:
            v = await self._get("/version")
            return {"ok": True, "message": f"Proxmox VE {v.get('version')} ({v.get('release')})", "details": v}
        except Exception as e:
            return {"ok": False, "message": f"Connection failed: {type(e).__name__}: {e}"}

    async def list_nodes(self) -> list:
        try:
            return await self._get("/nodes") or []
        except Exception:
            return []

    async def list_vms(self, node: Optional[str] = None) -> list:
        node = node or self.default_node
        if not node:
            return []
        return await self._get(f"/nodes/{node}/qemu") or []

    async def next_vmid(self) -> int:
        return int(await self._get("/cluster/nextid"))

    async def clone_vm(self, *, hostname: str, template_vmid: Optional[int] = None, node: Optional[str] = None) -> dict:
        template_vmid = template_vmid or self.clone_template_vmid
        node = node or self.default_node
        if not (template_vmid and node):
            raise ValueError("Proxmox: clone requires template_vmid + node")
        newid = await self.next_vmid()
        await self._post(f"/nodes/{node}/qemu/{template_vmid}/clone", {"newid": newid, "name": hostname, "full": 1})
        return {"vmid": newid, "node": node, "name": hostname}

    async def vm_action(self, node: str, vmid: int, action: str) -> Any:
        assert action in ("start", "stop", "reboot", "shutdown", "suspend", "resume")
        return await self._post(f"/nodes/{node}/qemu/{vmid}/status/{action}", {})

    async def vnc_ticket(self, node: str, vmid: int) -> dict:
        """Returns {ticket, port, cert} for VNC proxy."""
        return await self._post(f"/nodes/{node}/qemu/{vmid}/vncproxy", {"websocket": 1})


# ============================================================
# Mikrotik RouterOS
# ============================================================
class MikrotikClient:
    """Wraps librouteros for BGP/interface/traffic reads.

    Settings shape:
      {
        provider: "mikrotik",
        enabled: true,
        credentials: {
          host: "10.0.0.1",
          port: 8728,        # 8729 for TLS
          username: "readonly",
          password: "...",
          use_tls: false,
        }
      }
    """

    def __init__(self, settings: dict):
        # Accept both integration_settings shape (credentials={...}) and a raw
        # mikrotik_devices doc where the connection fields live at top-level.
        c = settings.get("credentials") or settings or {}
        self.host = c.get("host")
        self.port = int(c.get("port") or 8728)
        self.username = c.get("username")
        self.password = c.get("password")
        self.use_tls = bool(c.get("use_tls", False))

    def _connect(self):
        """Connect to RouterOS, transparently handling the two login flavours.

        `librouteros.connect()` defaults to `token` login which works on
        RouterOS ≥6.43. On older devices — or when the user configured a
        "plain" account — the handshake fails. We try token first, then fall
        back to `plain` so both worlds work without extra configuration.
        """
        import librouteros
        from librouteros.login import plain, token
        base = {"host": self.host, "port": self.port,
                "username": self.username, "password": self.password,
                "timeout": 8}
        if self.use_tls:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            base["ssl_wrapper"] = ctx.wrap_socket
            # For TLS the classic recommendation is `plain`.
            return librouteros.connect(**base, login_method=plain)
        # Non-TLS: try token first, then plain on any login-related failure.
        try:
            return librouteros.connect(**base, login_method=token)
        except Exception:
            return librouteros.connect(**base, login_method=plain)

    def test_connection(self) -> dict:
        try:
            api = self._connect()
            info = list(api.path("system", "resource"))
            api.close()
            return {"ok": True, "message": f"RouterOS {info[0].get('version')}", "details": info[0]}
        except Exception as e:
            return {"ok": False, "message": f"Connection failed: {type(e).__name__}: {e}"}

    def list_interfaces(self) -> list:
        try:
            api = self._connect()
            rows = list(api.path("interface"))
            api.close()
            return rows
        except Exception:
            return []

    def list_bgp_peers(self) -> list:
        """RouterOS 6 uses /routing/bgp/peer; RouterOS 7 renamed to /routing/bgp/session.
        Try both so the caller doesn't need to know."""
        try:
            api = self._connect()
        except Exception:
            return []
        rows = []
        for path in (("routing", "bgp", "session"), ("routing", "bgp", "peer")):
            try:
                rows = list(api.path(*path))
                if rows:
                    break
            except Exception:
                continue
        try: api.close()
        except Exception: pass
        return rows

    # ---------- Looking Glass (ping / traceroute / bgp-route lookup) ----------
    def looking_glass(self, *, tool: str, target: str) -> dict:
        """Run a read-only lookup from the RouterOS itself.
        tool ∈ {ping, traceroute, bgp_route}."""
        try:
            api = self._connect()
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "rows": []}
        try:
            if tool == "ping":
                rows = list(api("/ping", address=target, count="5"))
            elif tool == "traceroute":
                rows = list(api("/tool/traceroute", address=target, count="1"))
            elif tool == "bgp_route":
                # Try both v6 and v7 route tables
                try:
                    rows = list(api.path("routing", "route"))
                except Exception:
                    rows = list(api.path("ip", "route"))
                rows = [r for r in rows if (r.get("dst-address") or "").startswith(target)]
            else:
                return {"ok": False, "error": f"Unknown tool '{tool}'", "rows": []}
        except Exception as e:
            try: api.close()
            except Exception: pass
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "rows": []}
        try: api.close()
        except Exception: pass
        return {"ok": True, "rows": rows, "tool": tool, "target": target}

    # ---------- Blackhole routes (/ip/route type=blackhole) ----------
    def blackhole_list(self) -> list:
        try:
            api = self._connect()
            rows = list(api.path("ip", "route"))
            api.close()
            return [r for r in rows if (r.get("type") or "").lower() == "blackhole"]
        except Exception:
            return []

    def blackhole_add(self, prefix: str, *, comment: str = "portal-blackhole") -> dict:
        try:
            api = self._connect()
            list(api("/ip/route/add",
                **{"dst-address": prefix, "type": "blackhole",
                   "distance": "1", "comment": comment}))
            api.close()
            return {"ok": True, "prefix": prefix}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def blackhole_remove(self, route_id: str) -> dict:
        try:
            api = self._connect()
            list(api("/ip/route/remove", **{".id": route_id}))
            api.close()
            return {"ok": True, "id": route_id}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- Backup ----------
    def backup_list(self) -> list:
        try:
            api = self._connect()
            files = list(api.path("file"))
            api.close()
            return [f for f in files
                    if (f.get("name") or "").endswith(".backup")
                    or (f.get("name") or "").endswith(".rsc")
                    or (f.get("type") or "").lower() == "backup"]
        except Exception:
            return []

    def backup_create(self, *, name: str | None = None) -> dict:
        import datetime as _dt
        name = name or _dt.datetime.utcnow().strftime("portal-%Y%m%d-%H%M%S")
        try:
            api = self._connect()
            list(api("/system/backup/save", **{"name": name, "dont-encrypt": "yes"}))
            api.close()
            return {"ok": True, "name": name}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def backup_delete(self, filename: str) -> dict:
        try:
            api = self._connect()
            list(api("/file/remove", **{"numbers": filename}))
            api.close()
            return {"ok": True, "name": filename}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- Reboot ----------
    def reboot(self) -> dict:
        try:
            api = self._connect()
            list(api("/system/reboot"))
            try: api.close()
            except Exception: pass
            return {"ok": True, "message": "Reboot command dispatched"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- System info ----------
    def system_resource(self) -> dict:
        try:
            api = self._connect()
            info = list(api.path("system", "resource"))
            api.close()
            return info[0] if info else {}
        except Exception as e:
            return {"error": str(e)}

    def traffic_monitor(self, interface: str) -> dict:
        try:
            api = self._connect()
            rows = list(api("/interface/monitor-traffic", **{"interface": interface, "once": ""}))
            api.close()
            return rows[0] if rows else {}
        except Exception as e:
            return {"error": str(e)}

    def torch(self, *, interface: str, duration: int = 2,
              src_address: str = "0.0.0.0/0", dst_address: str = "0.0.0.0/0",
              protocol: str = "any", port: str = "any", ip_version: str = "ipv4") -> dict:
        """Run `/tool/torch` for a short duration and return the aggregated flow list.

        Uses a bounded `duration` (2s default, 10s max) so the API socket does
        not stream indefinitely.  All arguments are validated by the caller —
        `interface` is required, everything else defaults to a wildcard.
        """
        try:
            duration = max(1, min(int(duration or 2), 10))
        except (TypeError, ValueError):
            duration = 2

        params: dict = {"interface": interface, "duration": str(duration)}
        # RouterOS uses hyphenated keys
        if src_address and src_address != "0.0.0.0/0":
            params["src-address"] = src_address
        if dst_address and dst_address != "0.0.0.0/0":
            params["dst-address"] = dst_address
        if protocol and protocol.lower() != "any":
            params["protocol"] = protocol.lower()
        # RouterOS accepts src-port / dst-port / port. Use `port` (both directions).
        if port and str(port).lower() != "any":
            params["port"] = str(port)
        if ip_version and ip_version.lower() == "ipv6":
            params["ip-version"] = "ipv6"

        try:
            api = self._connect()
            rows = list(api("/tool/torch", **params))
            api.close()
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "rows": []}

        # Normalize keys (RouterOS returns .id-suffixed and hyphenated names)
        norm = []
        for r in rows:
            norm.append({
                "src_address": r.get("src-address") or r.get("src_address") or "",
                "dst_address": r.get("dst-address") or r.get("dst_address") or "",
                "protocol":    r.get("protocol") or r.get("ip-protocol") or "",
                "src_port":    r.get("src-port") or r.get("src_port") or "",
                "dst_port":    r.get("dst-port") or r.get("dst_port") or "",
                "tx_rate":     int(r.get("tx", 0) or r.get("tx-rate", 0) or 0),
                "rx_rate":     int(r.get("rx", 0) or r.get("rx-rate", 0) or 0),
                "tx_packets":  int(r.get("tx-packets", 0) or 0),
                "rx_packets":  int(r.get("rx-packets", 0) or 0),
            })
        norm.sort(key=lambda x: (x["tx_rate"] + x["rx_rate"]), reverse=True)
        return {
            "ok": True,
            "interface": interface,
            "duration": duration,
            "flow_count": len(norm),
            "total_tx_rate": sum(x["tx_rate"] for x in norm),
            "total_rx_rate": sum(x["rx_rate"] for x in norm),
            "rows": norm,
        }


# ============================================================
# Payment gateways
# ============================================================
class MidtransGateway:
    """Midtrans Snap + notification signature verification."""

    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        self.sandbox = bool(settings.get("sandbox", True))
        self.server_key = c.get("server_key") or ""
        self.client_key = c.get("client_key") or ""
        self.base = "https://app.sandbox.midtrans.com" if self.sandbox else "https://app.midtrans.com"

    def _basic(self) -> str:
        return base64.b64encode(f"{self.server_key}:".encode()).decode()

    async def test_connection(self) -> dict:
        if not self.server_key:
            return {"ok": False, "message": "Missing server_key"}
        # Ping the Snap endpoint with a HEAD; any 401 means keys wrong.
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.base}/snap/v1", headers={"Authorization": f"Basic {self._basic()}"})
            # 200/404 => reachable, 401 => wrong key
            if r.status_code == 401:
                return {"ok": False, "message": "Midtrans rejected the server_key"}
            return {"ok": True, "message": f"Midtrans {'sandbox' if self.sandbox else 'production'} reachable"}
        except Exception as e:
            return {"ok": False, "message": f"HTTP error: {e}"}

    async def create_payment(self, *, invoice_id: str, amount_idr: int, customer_email: str, callback_url: str) -> dict:
        payload = {
            "transaction_details": {"order_id": invoice_id, "gross_amount": int(amount_idr)},
            "customer_details": {"email": customer_email},
        }
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.base}/snap/v1/transactions", json=payload,
                             headers={"Accept": "application/json", "Content-Type": "application/json",
                                      "Authorization": f"Basic {self._basic()}"})
            r.raise_for_status()
            data = r.json()
        return {"payment_url": data.get("redirect_url"), "snap_token": data.get("token"),
                "external_id": invoice_id, "raw": data}

    def verify_webhook(self, raw_body: bytes) -> dict:
        data = json.loads(raw_body)
        sig = data.get("signature_key", "")
        msg = f"{data['order_id']}{data['status_code']}{data['gross_amount']}{self.server_key}".encode()
        calc = hashlib.sha512(msg).hexdigest()
        if not hmac.compare_digest(sig, calc):
            raise ValueError("Invalid Midtrans signature")
        ts, fraud = data.get("transaction_status"), data.get("fraud_status")
        status = "paid" if (ts in ("settlement", "capture") and fraud in (None, "accept")) \
                 else ("pending" if ts == "pending" else "failed")
        return {"invoice_id": data["order_id"], "status": status,
                "external_id": data.get("transaction_id"), "raw": data}


class XenditGateway:
    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        self.secret_key = c.get("secret_key") or ""
        self.webhook_token = c.get("webhook_token") or ""
        self.channel = settings.get("channel", "VA")
        self.sandbox = bool(settings.get("sandbox", True))

    def _auth(self) -> str:
        return base64.b64encode(f"{self.secret_key}:".encode()).decode()

    async def test_connection(self) -> dict:
        if not self.secret_key:
            return {"ok": False, "message": "Missing secret_key"}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.xendit.co/balance",
                                headers={"Authorization": f"Basic {self._auth()}"})
            if r.status_code == 401:
                return {"ok": False, "message": "Xendit rejected the secret_key"}
            r.raise_for_status()
            return {"ok": True, "message": "Xendit reachable", "details": r.json()}
        except Exception as e:
            return {"ok": False, "message": f"HTTP error: {e}"}

    async def create_payment(self, *, invoice_id: str, amount_idr: int, customer_email: str, callback_url: str) -> dict:
        if self.channel == "VA":
            pm = {"type": "VIRTUAL_ACCOUNT", "reusability": "ONE_TIME_USE",
                  "virtual_account": {"channel_code": "BCA",
                                      "channel_properties": {"customer_name": customer_email.split("@")[0]}}}
        elif self.channel == "EWALLET":
            pm = {"type": "EWALLET", "reusability": "ONE_TIME_USE",
                  "ewallet": {"channel_code": "DANA",
                              "channel_properties": {"success_return_url": callback_url, "failure_return_url": callback_url}}}
        else:
            pm = {"type": "QR_CODE", "reusability": "ONE_TIME_USE",
                  "qr_code": {"channel_code": "QRIS"}}
        payload = {"reference_id": invoice_id, "amount": int(amount_idr), "currency": "IDR",
                   "payment_method": pm, "customer_email": customer_email}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.xendit.co/v3/payment_requests", json=payload,
                             headers={"Authorization": f"Basic {self._auth()}",
                                      "Content-Type": "application/json",
                                      "x-idempotency-key": invoice_id})
            r.raise_for_status()
            data = r.json()
        va = None
        if isinstance(data.get("payment_method", {}).get("virtual_account"), dict):
            va = data["payment_method"]["virtual_account"].get("virtual_account_number")
        qris = None
        if isinstance(data.get("payment_method", {}).get("qr_code"), dict):
            qris = data["payment_method"]["qr_code"].get("qr_string")
        pu = None
        acts = data.get("actions") or []
        if acts:
            pu = acts[0].get("url") or acts[0].get("desktop_web_checkout_url") or acts[0].get("mobile_web_checkout_url")
        return {"payment_url": pu, "va_number": va, "qris_url": qris,
                "external_id": data.get("id"), "raw": data}

    def verify_webhook(self, headers: dict, raw_body: bytes) -> dict:
        token = headers.get("x-callback-token") or headers.get("X-CALLBACK-TOKEN") or ""
        if not (self.webhook_token and hmac.compare_digest(token, self.webhook_token)):
            raise ValueError("Invalid Xendit webhook token")
        data = json.loads(raw_body)
        status_raw = data.get("status") or data.get("payment_request", {}).get("status")
        mapped = ("paid" if status_raw in ("SUCCEEDED", "COMPLETED", "PAID") else
                  "pending" if status_raw in ("ACCEPTING_PAYMENTS", "REQUIRES_ACTION", "AUTHORIZED", "PENDING") else
                  "failed")
        return {"invoice_id": data.get("reference_id") or data.get("external_id") or data.get("id"),
                "status": mapped, "external_id": data.get("id") or data.get("payment_request_id"),
                "raw": data}


class DuitkuGateway:
    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        self.sandbox = bool(settings.get("sandbox", True))
        self.merchant_code = c.get("merchant_code") or ""
        self.api_key = c.get("api_key") or ""
        self.base = "https://api-sandbox.duitku.com" if self.sandbox else "https://api-prod.duitku.com"

    def _sig_create(self, timestamp: str) -> str:
        s = f"{self.merchant_code}{timestamp}".encode()
        return hmac.new(self.api_key.encode(), s, hashlib.sha256).hexdigest()

    def _sig_callback(self, merchant_code: str, amount: str, order_id: str) -> str:
        s = f"{merchant_code}{amount}{order_id}".encode()
        return hmac.new(self.api_key.encode(), s, hashlib.sha256).hexdigest()

    async def test_connection(self) -> dict:
        if not (self.merchant_code and self.api_key):
            return {"ok": False, "message": "Missing merchant_code or api_key"}
        return {"ok": True, "message": f"Duitku creds present ({'sandbox' if self.sandbox else 'production'}). Live validation happens on first invoice."}

    async def create_payment(self, *, invoice_id: str, amount_idr: int, customer_email: str, callback_url: str) -> dict:
        ts = str(int(time.time() * 1000))
        payload = {"merchantCode": self.merchant_code, "paymentAmount": int(amount_idr),
                   "merchantOrderId": invoice_id, "productDetails": f"Invoice {invoice_id}",
                   "email": customer_email, "callbackUrl": callback_url, "returnUrl": callback_url}
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self.base}/api/merchant/createInvoice", json=payload,
                             headers={"Content-Type": "application/json",
                                      "x-duitku-timestamp": ts,
                                      "x-duitku-merchantcode": self.merchant_code,
                                      "x-duitku-signature": self._sig_create(ts)})
            r.raise_for_status()
            data = r.json()
        return {"payment_url": data.get("paymentUrl"),
                "external_id": data.get("reference", invoice_id),
                "raw": data}

    def verify_webhook(self, raw_body: bytes) -> dict:
        # Duitku callbacks are form-urlencoded
        body = raw_body.decode(errors="ignore")
        data = dict(x.split("=", 1) for x in body.split("&") if "=" in x)
        sig = data.get("signature", "")
        calc = self._sig_callback(data.get("merchantCode", ""), data.get("amount", ""),
                                  data.get("merchantOrderId", ""))
        if not hmac.compare_digest(sig, calc):
            raise ValueError("Invalid Duitku signature")
        status = "paid" if data.get("resultCode") == "00" else "failed"
        return {"invoice_id": data.get("merchantOrderId", ""), "status": status,
                "external_id": data.get("reference") or data.get("merchantOrderId"), "raw": data}


# ============================================================
# Factory + provider registry
# ============================================================
PAYMENT_PROVIDERS = {"midtrans": MidtransGateway, "xendit": XenditGateway, "duitku": DuitkuGateway}


def payment_gateway(provider: str, settings: dict):
    cls = PAYMENT_PROVIDERS.get(provider)
    if not cls:
        raise ValueError(f"Unknown payment provider: {provider}")
    return cls(settings)


INTEGRATION_SCHEMA = {
    "proxmox": {
        "label": "Proxmox VE",
        "category": "virtualization",
        "description": "VPS auto-provisioning, live start/stop/reboot, noVNC console.",
        "credentials": [
            {"key": "host", "label": "Host URL (https://…:8006)", "type": "text", "required": True},
            {"key": "token_id", "label": "API Token ID (e.g. root@pam!portal)", "type": "text"},
            {"key": "token_secret", "label": "API Token Secret", "type": "password"},
            {"key": "username", "label": "Or username (fallback)", "type": "text"},
            {"key": "password", "label": "Or password (fallback)", "type": "password"},
        ],
        "options": [
            {"key": "default_node", "label": "Default node name", "type": "text"},
            {"key": "default_storage", "label": "Default storage", "type": "text", "default": "local-lvm"},
            {"key": "default_bridge", "label": "Default network bridge", "type": "text", "default": "vmbr0"},
            {"key": "clone_template_vmid", "label": "Clone template VMID", "type": "number"},
            {"key": "ssl_verify", "label": "Verify SSL", "type": "checkbox", "default": False},
        ],
    },
    "mikrotik": {
        "label": "Mikrotik RouterOS",
        "category": "network",
        "description": "Looking Glass, BGP monitor, interface traffic, backup/restart.",
        "credentials": [
            {"key": "host", "label": "Host / IP", "type": "text", "required": True},
            {"key": "port", "label": "API port (8728 plain / 8729 TLS)", "type": "number", "default": 8728},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "use_tls", "label": "Use TLS", "type": "checkbox", "default": False},
        ],
        "options": [],
    },
    "cpanel": {
        "label": "cPanel / WHM",
        "category": "provisioning",
        "description": "Auto-provision shared hosting accounts via WHM API.",
        "credentials": [
            {"key": "host", "label": "WHM host (https://…:2087)", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True, "default": "root"},
            {"key": "api_token", "label": "WHM API Token", "type": "password", "required": True},
        ],
        "options": [
            {"key": "default_package", "label": "Default hosting package", "type": "text", "default": "default"},
            {"key": "ssl_verify", "label": "Verify SSL", "type": "checkbox", "default": True},
        ],
    },
    "plesk": {
        "label": "Plesk",
        "category": "provisioning",
        "description": "Auto-provision Plesk hosting subscriptions via XML-API.",
        "credentials": [
            {"key": "host", "label": "Plesk host (https://…:8443)", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
        ],
        "options": [
            {"key": "default_plan", "label": "Default subscription plan", "type": "text"},
            {"key": "ssl_verify", "label": "Verify SSL", "type": "checkbox", "default": True},
        ],
    },
    "midtrans": {
        "label": "Midtrans (Snap)",
        "category": "payment",
        "description": "Indonesian payment gateway — Snap + Core API (VA, e-wallet, QRIS, cards).",
        "credentials": [
            {"key": "server_key", "label": "Server Key", "type": "password", "required": True},
            {"key": "client_key", "label": "Client Key", "type": "text", "required": True},
        ],
        "options": [{"key": "sandbox", "label": "Sandbox mode", "type": "checkbox", "default": True}],
    },
    "xendit": {
        "label": "Xendit",
        "category": "payment",
        "description": "Payment gateway (VA, e-wallet, QRIS, direct debit).",
        "credentials": [
            {"key": "secret_key", "label": "Secret API Key", "type": "password", "required": True},
            {"key": "webhook_token", "label": "Webhook verification token", "type": "password"},
        ],
        "options": [
            {"key": "channel", "label": "Payment channel", "type": "select",
             "options": ["VA", "EWALLET", "QRIS"], "default": "VA"},
            {"key": "sandbox", "label": "Test mode", "type": "checkbox", "default": True},
        ],
    },
    "duitku": {
        "label": "Duitku",
        "category": "payment",
        "description": "Indonesian payment gateway — VA, e-wallet, QRIS, retail outlets.",
        "credentials": [
            {"key": "merchant_code", "label": "Merchant Code", "type": "text", "required": True},
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
        ],
        "options": [{"key": "sandbox", "label": "Sandbox mode", "type": "checkbox", "default": True}],
    },
    "smtp": {
        "label": "SMTP (Outgoing Email)",
        "category": "mail",
        "description": "Send invoices, notifications, and campaigns from your team address.",
        "credentials": [
            {"key": "host", "label": "SMTP host", "type": "text", "required": True},
            {"key": "port", "label": "Port (587 STARTTLS / 465 SSL)", "type": "number", "default": 587},
            {"key": "username", "label": "SMTP username", "type": "text", "required": True},
            {"key": "password", "label": "SMTP password", "type": "password", "required": True},
        ],
        "options": [
            {"key": "from_email", "label": "From address", "type": "text", "required": True},
            {"key": "from_name", "label": "From display name", "type": "text",
             "default": "Intercloud Digital Inovasi"},
            {"key": "use_tls", "label": "STARTTLS (587)", "type": "checkbox", "default": True},
            {"key": "use_ssl", "label": "Implicit SSL (465)", "type": "checkbox", "default": False},
        ],
    },
    "imap": {
        "label": "IMAP (Incoming Email)",
        "category": "mail",
        "description": "Pull inbox messages into the Webmail tab. Read-only, uses INBOX by default.",
        "credentials": [
            {"key": "host", "label": "IMAP host", "type": "text", "required": True,
             "placeholder": "imap.example.com"},
            {"key": "port", "label": "Port (993 SSL / 143 plain)", "type": "number", "default": 993},
            {"key": "username", "label": "IMAP username", "type": "text", "required": True},
            {"key": "password", "label": "IMAP password", "type": "password", "required": True},
        ],
        "options": [
            {"key": "use_ssl", "label": "Implicit SSL (993)", "type": "checkbox", "default": True},
            {"key": "mailbox", "label": "Mailbox / folder", "type": "text", "default": "INBOX"},
            {"key": "fetch_limit", "label": "Max messages to fetch", "type": "number", "default": 50},
        ],
    },
    "recaptcha": {
        "label": "Google reCAPTCHA v3",
        "category": "security",
        "description": "Score-based invisible bot protection for portal Login, Register, and Forgot-Password. Get keys at https://www.google.com/recaptcha/admin/create (choose v3).",
        "credentials": [
            {"key": "site_key", "label": "Site Key (public)", "type": "text", "required": True,
             "placeholder": "6Lc..."},
            {"key": "secret_key", "label": "Secret Key (server-side)", "type": "password", "required": True,
             "placeholder": "6Lc..."},
        ],
        "options": [
            {"key": "min_score", "label": "Min score threshold (0.0 – 1.0)", "type": "number", "default": 0.5},
            {"key": "expected_hostname", "label": "Expected hostname (leave blank to skip check)", "type": "text",
             "placeholder": "portal.intercloud-digital.com"},
            {"key": "verify_action", "label": "Enforce action match (login/register/forgot)", "type": "checkbox", "default": True},
        ],
    },
    "telegram": {
        "label": "Telegram Bot",
        "category": "security",
        "description": "Send security notifications (auto-blocks, high-risk logins) to a Telegram chat. Create a bot with @BotFather then get its chat_id via https://api.telegram.org/bot<TOKEN>/getUpdates.",
        "credentials": [
            {"key": "bot_token", "label": "Bot token", "type": "password", "required": True,
             "placeholder": "123456:ABC-DEF…"},
            {"key": "chat_id", "label": "Chat ID (user or group)", "type": "text", "required": True,
             "placeholder": "-100123456789"},
        ],
        "options": [
            {"key": "silent", "label": "Send silently (no push notification)", "type": "checkbox", "default": False},
        ],
    },
}


# Category labels used by the admin UI grouping.
CATEGORY_LABELS = {
    "virtualization": "Virtualization & Compute",
    "network": "Network",
    "provisioning": "Hosting Provisioning",
    "payment": "Payment Gateways",
    "mail": "Email (SMTP / IMAP)",
    "security": "Security & Anti-bot",
}


# ============================================================
# SMTP — password reset + generic transactional mail
# ============================================================
class SMTPMailer:
    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        o = settings.get("options") or {}
        self.host = c.get("host")
        self.port = int(c.get("port") or 587)
        self.username = c.get("username")
        self.password = c.get("password")
        self.use_tls = bool(o.get("use_tls", True))
        self.use_ssl = bool(o.get("use_ssl", False))
        self.from_email = o.get("from_email") or c.get("username")
        self.from_name = o.get("from_name") or "Intercloud"

    def test_connection(self) -> dict:
        try:
            import smtplib
            if self.use_ssl:
                s = smtplib.SMTP_SSL(self.host, self.port, timeout=10)
            else:
                s = smtplib.SMTP(self.host, self.port, timeout=10)
                if self.use_tls:
                    s.starttls()
            if self.username:
                s.login(self.username, self.password)
            s.quit()
            return {"ok": True, "message": f"SMTP reachable at {self.host}:{self.port}"}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    def send(self, *, to: str, subject: str, html: str, text: str = "") -> None:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.from_name} <{self.from_email}>"
        msg["To"] = to
        msg["Subject"] = subject
        if text:
            msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        if self.use_ssl:
            s = smtplib.SMTP_SSL(self.host, self.port, timeout=15)
        else:
            s = smtplib.SMTP(self.host, self.port, timeout=15)
            if self.use_tls:
                s.starttls()
        if self.username:
            s.login(self.username, self.password)
        s.sendmail(self.from_email, [to], msg.as_string())
        s.quit()


# ============================================================
# IMAP — read inbox for the Webmail tab
# ============================================================
class IMAPClient:
    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        o = settings.get("options") or {}
        self.host = c.get("host")
        self.port = int(c.get("port") or 993)
        self.username = c.get("username")
        self.password = c.get("password")
        self.use_ssl = bool(o.get("use_ssl", True))
        self.mailbox = o.get("mailbox") or "INBOX"
        self.fetch_limit = int(o.get("fetch_limit") or 50)

    def _connect(self):
        import imaplib
        if self.use_ssl:
            m = imaplib.IMAP4_SSL(self.host, self.port, timeout=15)
        else:
            m = imaplib.IMAP4(self.host, self.port, timeout=15)
        m.login(self.username, self.password)
        return m

    def test_connection(self) -> dict:
        try:
            m = self._connect()
            typ, _ = m.select(self.mailbox, readonly=True)
            m.logout()
            if typ != "OK":
                return {"ok": False, "message": f"Cannot open mailbox {self.mailbox}"}
            return {"ok": True, "message": f"IMAP reachable at {self.host}:{self.port} · mailbox {self.mailbox}"}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    def fetch_recent(self, limit: int | None = None) -> list[dict]:
        """Return the most recent messages (newest first). Best-effort — errors
        surface as an empty list; higher-level callers fall back to mocked data.
        """
        import email
        from email.header import decode_header, make_header
        limit = int(limit or self.fetch_limit)
        try:
            m = self._connect()
            m.select(self.mailbox, readonly=True)
            typ, data = m.search(None, "ALL")
            if typ != "OK":
                m.logout()
                return []
            ids = data[0].split()[-limit:][::-1]
            out = []
            for i in ids:
                typ, msg_data = m.fetch(i, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subj = str(make_header(decode_header(msg.get("Subject") or "")))
                from_ = str(make_header(decode_header(msg.get("From") or "")))
                date_ = msg.get("Date") or ""
                # Best-effort text body extraction
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = (part.get_payload(decode=True) or b"").decode(
                                part.get_content_charset() or "utf-8", errors="replace")
                            break
                else:
                    body = (msg.get_payload(decode=True) or b"").decode(
                        msg.get_content_charset() or "utf-8", errors="replace")
                out.append({
                    "id": i.decode(), "from": from_, "subject": subj,
                    "date": date_, "preview": body[:220].replace("\n", " "),
                    "body": body,
                })
            m.logout()
            return out
        except Exception:
            return []



# ============================================================
# reCAPTCHA v3 — score-based verification for auth endpoints
# ============================================================
class RecaptchaV3Verifier:
    """Async wrapper around Google's reCAPTCHA v3 siteverify endpoint.

    Reads its config from an `integration_settings` doc for `provider='recaptcha'`:
      credentials.site_key    → public, echoed to frontend
      credentials.secret_key  → server-only, used in siteverify POST
      options.min_score       → float, default 0.5
      options.expected_hostname
      options.verify_action   → bool, default True

    Usage from an endpoint:
        v = RecaptchaV3Verifier(settings)
        await v.verify(token, action='login', remote_ip=client_ip)
    Raises HTTPException(400/403) on failure. Fail-open only when disabled
    (the caller is expected to check `enabled` before invoking `verify()`).
    """

    SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"

    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        o = settings.get("options") or {}
        self.site_key = c.get("site_key") or ""
        self.secret_key = c.get("secret_key") or ""
        try:
            self.min_score = float(o.get("min_score", 0.5))
        except (TypeError, ValueError):
            self.min_score = 0.5
        self.expected_hostname = (o.get("expected_hostname") or "").strip() or None
        self.verify_action = bool(o.get("verify_action", True))

    async def test_connection(self) -> dict:
        """Test by calling siteverify with an obviously-invalid token.
        Google returns success=false + `invalid-input-response` — that means
        our secret_key is at least valid enough to make the call."""
        if not self.secret_key:
            return {"ok": False, "message": "Secret key is empty."}
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.post(self.SITEVERIFY_URL, data={
                    "secret": self.secret_key,
                    "response": "test",
                })
            j = r.json()
            errs = j.get("error-codes") or []
            if "invalid-input-secret" in errs:
                return {"ok": False, "message": "Google rejected the secret key. Double-check the value."}
            if "missing-input-secret" in errs:
                return {"ok": False, "message": "Secret key is missing."}
            # Any other error means the secret is being accepted (just the token was bogus).
            return {"ok": True, "message": "reCAPTCHA secret accepted by Google (test token expectedly failed).",
                    "details": {"error_codes": errs}}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    async def verify(self, token: Optional[str], action: str, remote_ip: Optional[str] = None):
        from fastapi import HTTPException  # local import to avoid pulling FastAPI in mock ctx
        if not self.secret_key:
            raise HTTPException(status_code=500, detail="reCAPTCHA is enabled but secret key is missing")
        if not token:
            raise HTTPException(status_code=400, detail="Missing reCAPTCHA token")

        data = {"secret": self.secret_key, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            async with httpx.AsyncClient(timeout=6.0) as c:
                r = await c.post(self.SITEVERIFY_URL, data=data)
                j = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"reCAPTCHA verify failed: {type(e).__name__}")

        if not j.get("success"):
            raise HTTPException(status_code=400, detail={
                "message": "reCAPTCHA verification failed",
                "errors": j.get("error-codes", []),
            })
        if self.verify_action and j.get("action") != action:
            raise HTTPException(status_code=400, detail="reCAPTCHA action mismatch")
        if self.expected_hostname and j.get("hostname") != self.expected_hostname:
            raise HTTPException(status_code=400, detail="reCAPTCHA hostname mismatch")
        try:
            score = float(j.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        if score < self.min_score:
            raise HTTPException(status_code=403, detail={
                "message": "reCAPTCHA score too low",
                "score": score, "min_score": self.min_score,
            })
        return {"success": True, "score": score, "action": j.get("action"),
                "hostname": j.get("hostname")}


async def get_recaptcha_settings(db) -> Optional[dict]:
    """Convenience helper — returns the doc only if enabled."""
    doc = await get_settings(db, "recaptcha")
    if doc and doc.get("enabled"):
        return doc
    return None


async def enforce_recaptcha(db, token: Optional[str], action: str, remote_ip: Optional[str] = None):
    """Verify reCAPTCHA if the integration is enabled; no-op otherwise.
    Call from auth endpoints:
        await iv2.enforce_recaptcha(db, payload.recaptcha_token, 'login', request.client.host)
    """
    doc = await get_recaptcha_settings(db)
    if not doc:
        return None
    return await RecaptchaV3Verifier(doc).verify(token, action, remote_ip)


# ============================================================
# Telegram Bot — security notifications
# ============================================================
class TelegramNotifier:
    """Minimal Telegram Bot API wrapper for sending Markdown-safe messages
    to a configured chat_id. Reads its settings from integrations_v2
    with provider='telegram'."""

    API_BASE = "https://api.telegram.org"

    def __init__(self, settings: dict):
        c = settings.get("credentials") or {}
        o = settings.get("options") or {}
        self.bot_token = c.get("bot_token") or ""
        self.chat_id = c.get("chat_id") or ""
        self.silent = bool(o.get("silent", False))

    async def test_connection(self) -> dict:
        if not self.bot_token:
            return {"ok": False, "message": "bot_token is empty"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.get(f"{self.API_BASE}/bot{self.bot_token}/getMe")
                j = r.json()
            if not j.get("ok"):
                return {"ok": False, "message": f"Bot rejected: {j.get('description')}"}
            u = j.get("result") or {}
            return {"ok": True, "message": f"Connected as @{u.get('username')} ({u.get('first_name')})",
                    "details": u}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    async def send(self, text: str, *, chat_id: str | None = None) -> dict:
        if not self.bot_token or not (chat_id or self.chat_id):
            raise RuntimeError("Telegram is not configured (bot_token/chat_id missing)")
        payload = {
            "chat_id": chat_id or self.chat_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_notification": bool(self.silent),
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as c:
                r = await c.post(f"{self.API_BASE}/bot{self.bot_token}/sendMessage", json=payload)
                j = r.json()
            if not j.get("ok"):
                return {"ok": False, "message": j.get("description")}
            return {"ok": True, "message_id": (j.get("result") or {}).get("message_id")}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}


async def get_telegram_settings(db) -> Optional[dict]:
    """Convenience helper — returns the doc only if enabled."""
    doc = await get_settings(db, "telegram")
    if doc and doc.get("enabled"):
        return doc
    return None

