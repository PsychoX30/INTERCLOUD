"""Module registry for third-party integrations (cPanel, Plesk, Proxmox, MikroTik,
Duitku, Xendit, Midtrans, SMTP, etc.).

Each module declares the fields the admin must fill in the "Add Server" dialog,
their type (text / password / select / number / bool), default values, and
required flags. The frontend renders the form dynamically from these schemas.
"""

FIELD = lambda key, label, type_="text", **kw: {"key": key, "label": label, "type": type_, **kw}

MODULE_SCHEMAS = {
    # ---------- Provisioning ----------
    "cpanel": {
        "label": "cPanel / WHM",
        "category": "provisioning",
        "description": "Auto-provision shared hosting accounts via WHM API.",
        "fields": [
            FIELD("hostname", "Hostname or IP Address", required=True, placeholder="whm.example.com"),
            FIELD("port", "Port", "number", default=2087),
            FIELD("protocol", "Protocol", "select", options=["https", "http"], default="https"),
            FIELD("username", "Username", required=True, placeholder="root"),
            FIELD("api_token", "API Token", "password", required=True),
        ],
    },
    "plesk": {
        "label": "Plesk",
        "category": "provisioning",
        "description": "Auto-provision Plesk hosting accounts via XML-API.",
        "fields": [
            FIELD("hostname", "Hostname or IP Address", required=True),
            FIELD("port", "Port", "number", default=8443),
            FIELD("protocol", "Protocol", "select", options=["https", "http"], default="https"),
            FIELD("username", "Username", required=True),
            FIELD("password", "Password", "password", required=True),
        ],
    },
    "proxmox": {
        "label": "Proxmox VE",
        "category": "virtualization",
        "description": "VPS auto-provisioning, console (noVNC), and lifecycle actions.",
        "fields": [
            FIELD("hostname", "Hostname or IP Address", required=True, placeholder="prox.icd-cust.net"),
            FIELD("port", "Port", "number", default=8006),
            FIELD("protocol", "Protocol", "select", options=["https"], default="https"),
            FIELD("username", "Username", required=True, placeholder="root@pam or apiuser@pve"),
            FIELD("password", "Password", "password"),
            FIELD("api_token_id", "API Token ID"),
            FIELD("api_token_secret", "API Token Secret", "password"),
            FIELD("default_node", "Default Node", placeholder="prox-jkt-05"),
        ],
    },
    "mikrotik": {
        "label": "MikroTik RouterOS",
        "category": "network",
        "description": "Looking Glass, BGP net-mon, blackhole, backup, restart, traffic monitor.",
        "fields": [
            FIELD("hostname", "Hostname or IP Address", required=True),
            FIELD("port", "API Port", "number", default=8728),
            FIELD("protocol", "Protocol", "select", options=["api", "api-ssl"], default="api-ssl"),
            FIELD("username", "Username", required=True),
            FIELD("password", "Password", "password", required=True),
            FIELD("router_name", "Router Label", placeholder="RTR-JKT-CORE-01"),
        ],
    },
    # ---------- Payment gateways ----------
    "duitku": {
        "label": "Duitku Payment Gateway",
        "category": "payment",
        "description": "Indonesian payment gateway — VA, e-wallet, QRIS, retail outlets.",
        "fields": [
            FIELD("merchant_code", "Merchant Code", required=True),
            FIELD("api_key", "API Key", "password", required=True),
            FIELD("environment", "Environment", "select", options=["sandbox", "production"], default="sandbox"),
            FIELD("callback_url", "Callback URL", placeholder="https://your-domain/api/portal/webhooks/duitku"),
            FIELD("return_url", "Return URL"),
        ],
    },
    "xendit": {
        "label": "Xendit",
        "category": "payment",
        "description": "Payment gateway supporting VA, e-wallet, QRIS, direct debit.",
        "fields": [
            FIELD("secret_key", "Secret Key", "password", required=True),
            FIELD("callback_token", "Callback Token", "password"),
            FIELD("webhook_url", "Webhook URL"),
        ],
    },
    "midtrans": {
        "label": "Midtrans",
        "category": "payment",
        "description": "Snap payment + core API (VA, e-wallet, credit card).",
        "fields": [
            FIELD("server_key", "Server Key", "password", required=True),
            FIELD("client_key", "Client Key", required=True),
            FIELD("environment", "Environment", "select", options=["sandbox", "production"], default="sandbox"),
            FIELD("callback_url", "Callback URL"),
        ],
    },
    # ---------- Mail ----------
    "smtp": {
        "label": "SMTP (Outbound Mail)",
        "category": "mail",
        "description": "Send invoices, notifications, and campaigns.",
        "fields": [
            FIELD("hostname", "SMTP Host", required=True, placeholder="smtp.example.com"),
            FIELD("port", "Port", "number", default=587),
            FIELD("protocol", "Encryption", "select", options=["tls", "ssl", "none"], default="tls"),
            FIELD("username", "Username", required=True),
            FIELD("password", "Password", "password", required=True),
            FIELD("from_email", "From Email", required=True, placeholder="no-reply@intercloud-digital.com"),
            FIELD("from_name", "From Name", default="Intercloud Digital Inovasi"),
        ],
    },
    # ---------- Utilities ----------
    "whois": {
        "label": "WHOIS Lookup API",
        "category": "diagnostic",
        "description": "Third-party WHOIS lookup service.",
        "fields": [
            FIELD("api_key", "API Key", "password", required=True),
            FIELD("endpoint", "Endpoint URL", default="https://www.whoisxmlapi.com/whoisserver/WhoisService"),
        ],
    },
    "blacklist": {
        "label": "IP Blacklist Check",
        "category": "diagnostic",
        "description": "Query multiple DNSBLs / RBLs for blacklist status.",
        "fields": [
            FIELD("api_key", "API Key", "password"),
            FIELD("endpoint", "Endpoint URL", default="https://api.blacklistchecker.com/check"),
        ],
    },
    "dcim": None,  # DCIM/IPAM is native to the admin console, not an external integration.
}


# Purge disabled entries at load time so the module list never returns them
MODULE_SCHEMAS = {k: v for k, v in MODULE_SCHEMAS.items() if v is not None}


def module_list():
    """Return an array of module definitions for the admin UI."""
    return [
        {"key": k, **v} for k, v in MODULE_SCHEMAS.items()
    ]


def module_schema(key: str):
    return MODULE_SCHEMAS.get(key)


# Masked fields: never return values in list/detail responses.
SECRET_FIELD_TYPES = {"password"}


def redact(cfg: dict, schema: dict | None) -> dict:
    if not schema:
        return cfg
    out = dict(cfg or {})
    for f in schema.get("fields", []):
        if f["type"] in SECRET_FIELD_TYPES and out.get(f["key"]):
            out[f["key"]] = "••••••••"
    return out


def mock_test_connection(module: str, cfg: dict) -> dict:
    """Simulate a Test Connection call. Returns {ok, message, latency_ms}."""
    import random
    schema = module_schema(module)
    if not schema:
        return {"ok": False, "message": f"Unknown module: {module}"}
    # Verify required fields
    missing = [f["label"] for f in schema["fields"]
               if f.get("required") and not cfg.get(f["key"])]
    if missing:
        return {"ok": False, "message": f"Missing required fields: {', '.join(missing)}"}
    # Simulate latency + occasional soft failure
    latency = random.randint(35, 320)
    return {
        "ok": True,
        "message": f"Connection to {schema['label']} succeeded (mock).",
        "latency_ms": latency,
    }
