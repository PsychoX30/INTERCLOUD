"""Real network diagnostic tools — ping, traceroute, DNS, whois, blacklist.

All commands are:
- Sandboxed: strict input validation (only alnum + `.` `-` `_` `:` for IPv6).
- Time-bounded: hard timeouts to avoid hanging worker.
- Async: uses `asyncio.create_subprocess_exec` for shell commands and threadpool
  for the `ping3` library (which uses socket.SOCK_DGRAM, no root).
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import shutil
import socket
import time
from typing import Any, Dict, List

# ---------------------------------------------------------------- validation
_TARGET_RX = re.compile(r"^[A-Za-z0-9\.\-\_\:]{1,253}$")

def validate_target(target: str) -> str:
    t = (target or "").strip().lower()
    if not t or not _TARGET_RX.match(t):
        raise ValueError("Target must be a hostname or IP (letters, digits, dot, dash, colon, underscore only)")
    return t


def resolve_ip(target: str) -> str:
    """Best-effort DNS resolve. Returns the original target if already an IP."""
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass
    try:
        return socket.gethostbyname(target)
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {target}: {e}")


# ---------------------------------------------------------------- exec helper
async def _run(argv: List[str], timeout: float, input_bytes: bytes | None = None) -> Dict[str, Any]:
    """Run a subprocess safely and capture stdout/stderr with a hard timeout."""
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(input=input_bytes), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return {"ok": False, "output": "", "error": f"Timeout after {timeout}s",
                    "exit_code": -1, "duration_ms": int((time.time() - start) * 1000)}
        return {
            "ok": proc.returncode == 0,
            "output": (out or b"").decode(errors="replace").strip(),
            "error":  (err or b"").decode(errors="replace").strip(),
            "exit_code": proc.returncode,
            "duration_ms": int((time.time() - start) * 1000),
        }
    except FileNotFoundError:
        return {"ok": False, "output": "", "error": f"{argv[0]} is not installed on this host",
                "exit_code": -1, "duration_ms": 0}


# ============================================================
# PING — pure-python ping3 (SOCK_DGRAM, works without root)
# ============================================================
async def run_ping(target: str, *, count: int = 5, timeout: float = 2.0) -> Dict[str, Any]:
    t = validate_target(target)
    ip = resolve_ip(t)
    count = max(1, min(int(count), 10))

    def _do_ping():
        from ping3 import ping as _p  # local import
        results = []
        for i in range(count):
            try:
                r = _p(ip, timeout=timeout, unit="ms")
            except Exception as e:
                r = None
                results.append({"seq": i, "rtt_ms": None, "error": str(e)})
                continue
            if r is None or r is False:
                results.append({"seq": i, "rtt_ms": None, "error": "timeout"})
            else:
                results.append({"seq": i, "rtt_ms": round(float(r), 2)})
            time.sleep(0.15)
        return results

    started = time.time()
    results = await asyncio.get_event_loop().run_in_executor(None, _do_ping)
    good = [r["rtt_ms"] for r in results if r.get("rtt_ms") is not None]
    lost = count - len(good)

    summary = {
        "target": t, "resolved_ip": ip, "count": count,
        "received": len(good), "lost": lost,
        "loss_percent": round((lost / count) * 100, 1),
        "min_ms": round(min(good), 2) if good else None,
        "max_ms": round(max(good), 2) if good else None,
        "avg_ms": round(sum(good) / len(good), 2) if good else None,
        "duration_ms": int((time.time() - started) * 1000),
    }
    lines = [f"PING {t} ({ip})"]
    for r in results:
        if r.get("rtt_ms") is None:
            lines.append(f"  seq={r['seq']}  {r.get('error','timeout')}")
        else:
            lines.append(f"  seq={r['seq']}  time={r['rtt_ms']:.2f} ms")
    lines.append("")
    if good:
        lines.append(f"--- {t} ping statistics ---")
        lines.append(f"{count} packets transmitted, {len(good)} received, "
                     f"{summary['loss_percent']}% packet loss")
        lines.append(f"rtt min/avg/max = {summary['min_ms']}/{summary['avg_ms']}/{summary['max_ms']} ms")
    else:
        lines.append("100% packet loss — host unreachable or ICMP filtered")

    return {"tool": "ping", "output": "\n".join(lines), "summary": summary, "results": results}


# ============================================================
# TRACEROUTE — /usr/bin/traceroute
# ============================================================
async def run_traceroute(target: str, *, max_hops: int = 15) -> Dict[str, Any]:
    t = validate_target(target)
    ip = resolve_ip(t)
    max_hops = max(1, min(int(max_hops), 30))
    if not shutil.which("traceroute"):
        return {"tool": "traceroute", "output": "", "error": "traceroute not installed"}
    r = await _run(["traceroute", "-n", "-w", "2", "-q", "1", "-m", str(max_hops), ip], timeout=90)
    return {"tool": "traceroute", "output": r["output"] or r["error"],
            "summary": {"target": t, "resolved_ip": ip, "max_hops": max_hops,
                        "duration_ms": r["duration_ms"], "exit_code": r["exit_code"]}}


# ============================================================
# NSLOOKUP / DIG — bind9 dig
# ============================================================
async def run_dns(target: str, *, record: str = "A") -> Dict[str, Any]:
    t = validate_target(target)
    record = (record or "A").upper()
    if record not in {"A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "SRV", "ANY"}:
        raise ValueError(f"Unsupported record type {record}")
    if not shutil.which("dig"):
        return {"tool": "dns", "output": "", "error": "dig not installed"}
    r = await _run(["dig", "+time=3", "+tries=1", "+nocmd", "+multiline", t, record], timeout=8)
    return {"tool": "dns", "output": r["output"] or r["error"],
            "summary": {"target": t, "record": record, "duration_ms": r["duration_ms"],
                        "exit_code": r["exit_code"]}}


# ============================================================
# WHOIS
# ============================================================
async def run_whois(target: str) -> Dict[str, Any]:
    t = validate_target(target)
    if not shutil.which("whois"):
        return {"tool": "whois", "output": "", "error": "whois not installed"}
    r = await _run(["whois", "-H", t], timeout=20)
    return {"tool": "whois", "output": r["output"] or r["error"],
            "summary": {"target": t, "duration_ms": r["duration_ms"], "exit_code": r["exit_code"]}}


# ============================================================
# BLACKLIST — DNSBL lookups
# ============================================================
DNSBL_ZONES = [
    ("Spamhaus ZEN",   "zen.spamhaus.org"),
    ("SpamCop",        "bl.spamcop.net"),
    ("SORBS DUL",      "dnsbl.sorbs.net"),
    ("Barracuda",      "b.barracudacentral.org"),
    ("UCEPROTECT-1",   "dnsbl-1.uceprotect.net"),
    ("PSBL",           "psbl.surriel.com"),
    ("Manitu-NIX",     "ix.dnsbl.manitu.net"),
    ("SpamRats DYNA",  "dyna.spamrats.com"),
]

async def run_blacklist(target: str) -> Dict[str, Any]:
    t = validate_target(target)
    ip = resolve_ip(t)
    try:
        octets = ip.split(".")
        if len(octets) != 4:
            raise ValueError("Blacklist checks require an IPv4 address")
        [int(o) for o in octets]  # sanity
    except Exception as e:
        raise ValueError(f"Invalid IPv4 for blacklist check: {e}")
    reverse = ".".join(reversed(octets))

    async def _check(name: str, zone: str):
        q = f"{reverse}.{zone}"
        try:
            answers = await asyncio.get_event_loop().run_in_executor(
                None, lambda: socket.gethostbyname_ex(q)
            )
            return {"name": name, "zone": zone, "listed": True, "response": answers[2]}
        except socket.gaierror:
            return {"name": name, "zone": zone, "listed": False}
        except Exception as e:
            return {"name": name, "zone": zone, "listed": False, "error": str(e)}

    results = await asyncio.gather(*(_check(n, z) for n, z in DNSBL_ZONES))
    listed_count = sum(1 for r in results if r["listed"])

    lines = [f"DNSBL check for {ip} ({t}) across {len(DNSBL_ZONES)} zones:", ""]
    for r in results:
        status = ("LISTED " + ",".join(r.get("response", []))) if r["listed"] else "clean"
        marker = "⚠" if r["listed"] else "✓"
        lines.append(f"  {marker}  {r['name']:<16} {r['zone']:<24} {status}")
    lines.append("")
    lines.append(f"Overall: {listed_count}/{len(DNSBL_ZONES)} zones list this IP.")
    return {
        "tool": "blacklist",
        "output": "\n".join(lines),
        "summary": {
            "target": t, "resolved_ip": ip,
            "listed_count": listed_count, "total_zones": len(DNSBL_ZONES),
        },
        "results": results,
    }


# ============================================================
# PORT SCAN — TCP connect against a curated well-known list
# ============================================================
COMMON_PORTS = [21, 22, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995,
                3000, 3306, 3389, 5432, 6379, 8080, 8443, 27017]

async def run_port_scan(target: str, *, ports: List[int] | None = None) -> Dict[str, Any]:
    t = validate_target(target)
    ip = resolve_ip(t)
    port_list = [int(p) for p in (ports or COMMON_PORTS)]
    port_list = [p for p in port_list if 1 <= p <= 65535][:64]  # safety cap

    async def _probe(port: int):
        started = time.time()
        try:
            fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(fut, timeout=1.5)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {"port": port, "open": True, "latency_ms": int((time.time() - started) * 1000)}
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return {"port": port, "open": False}

    started = time.time()
    results = await asyncio.gather(*[_probe(p) for p in port_list])
    open_ports = [r for r in results if r["open"]]

    lines = [f"TCP port scan against {t} ({ip}) — {len(port_list)} common ports", ""]
    for r in results:
        state = f"OPEN ({r['latency_ms']}ms)" if r["open"] else "closed"
        lines.append(f"  {r['port']:>6}/tcp   {state}")
    lines.append("")
    lines.append(f"Open: {len(open_ports)}/{len(port_list)}")

    return {
        "tool": "portscan",
        "output": "\n".join(lines),
        "summary": {"target": t, "resolved_ip": ip, "open_count": len(open_ports),
                    "total_scanned": len(port_list),
                    "duration_ms": int((time.time() - started) * 1000)},
        "results": results,
    }


# ============================================================
# HTTP HEAD — fetch a URL, return status/headers/timing
# ============================================================
async def run_http_check(target: str) -> Dict[str, Any]:
    import httpx
    t = target.strip()
    if not t.startswith(("http://", "https://")):
        t = "http://" + validate_target(t)
    started = time.time()
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as c:
            r = await c.get(t)
    except Exception as e:
        return {"tool": "http", "output": f"Request failed: {e}",
                "summary": {"target": t, "error": str(e), "duration_ms": int((time.time() - started) * 1000)}}
    headers_pretty = "\n".join(f"  {k}: {v}" for k, v in r.headers.items())
    body_preview = (r.text or "")[:400].strip()
    output = (f"HTTP {r.status_code} {r.reason_phrase}\n"
              f"URL: {r.url}\nElapsed: {int((time.time() - started) * 1000)} ms\n\n"
              f"Response headers:\n{headers_pretty}\n\n"
              f"Body preview (400 chars):\n{body_preview}")
    return {
        "tool": "http",
        "output": output,
        "summary": {"target": str(r.url), "status_code": r.status_code,
                    "reason": r.reason_phrase,
                    "duration_ms": int((time.time() - started) * 1000),
                    "content_type": r.headers.get("content-type", "")},
    }


# ============================================================
# MIKROTIK TORCH — /tool/torch via librouteros
# ============================================================
_IFACE_RX  = re.compile(r"^[A-Za-z0-9\.\-_:/ ]{1,64}$")
_CIDR_RX   = re.compile(r"^[0-9a-fA-F:\.\/]{1,45}$")
_PROTO_RX  = re.compile(r"^(any|tcp|udp|icmp|gre|esp|ah|ipsec-esp|ipsec-ah|ospf|[0-9]{1,3})$", re.I)
_PORT_RX   = re.compile(r"^(any|[0-9]{1,5}(-[0-9]{1,5})?)$", re.I)

async def run_torch(target: str | None = None, *, interface: str = "",
                    src_address: str = "0.0.0.0/0",
                    dst_address: str = "0.0.0.0/0",
                    protocol: str = "any", port: str = "any",
                    duration: int = 2, ip_version: str = "ipv4",
                    _db=None) -> Dict[str, Any]:
    """Run MikroTik `/tool/torch` on a live router and return the top flows.

    Unlike the other tools this one reads its target from the configured
    `mikrotik` integration (host/credentials) instead of the free-form target
    field, and requires `interface` to be specified.
    """
    if not interface or not _IFACE_RX.match(interface):
        raise ValueError("interface is required (letters, digits, dot, dash, underscore, colon, slash)")
    for name, value in (("src_address", src_address), ("dst_address", dst_address)):
        if value and value != "0.0.0.0/0" and not _CIDR_RX.match(value):
            raise ValueError(f"{name} must be a valid IPv4/IPv6 address or CIDR")
    if protocol and not _PROTO_RX.match(protocol):
        raise ValueError("protocol must be one of any/tcp/udp/icmp/gre/esp/ah/ospf or an IP protocol number")
    if port and not _PORT_RX.match(str(port)):
        raise ValueError("port must be `any`, a single port, or a range like 80-90")

    if _db is None:
        raise ValueError("Torch requires the configured MikroTik integration — server did not supply db handle")

    from portal import integrations_v2 as iv2
    settings = await iv2.get_settings(_db, "mikrotik")
    if not settings or not settings.get("enabled"):
        raise ValueError("MikroTik integration is not enabled — configure it in Admin ▸ Integrations first")

    started = time.time()
    client = iv2.MikrotikClient(settings)
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.torch(interface=interface, duration=duration,
                             src_address=src_address, dst_address=dst_address,
                             protocol=protocol, port=port, ip_version=ip_version),
    )
    elapsed = int((time.time() - started) * 1000)

    if not result.get("ok"):
        return {"tool": "torch",
                "output": f"Torch failed: {result.get('error') or 'unknown error'}",
                "summary": {"interface": interface, "duration": duration,
                            "error": result.get("error"), "duration_ms": elapsed},
                "results": []}

    rows = result.get("rows") or []
    def _fmt_rate(bps: int) -> str:
        if bps >= 1_000_000_000: return f"{bps/1_000_000_000:.2f} Gbps"
        if bps >= 1_000_000:     return f"{bps/1_000_000:.2f} Mbps"
        if bps >= 1_000:         return f"{bps/1_000:.1f} kbps"
        return f"{bps} bps"

    lines = [
        f"/tool/torch  interface={interface}  duration={result['duration']}s  ip-version={ip_version}",
        f"  src-address={src_address}  dst-address={dst_address}  protocol={protocol}  port={port}",
        "",
        f"{'PROTO':<6} {'SRC':<24} {'SPORT':<7} {'DST':<24} {'DPORT':<7} {'TX':>12} {'RX':>12}",
        "-" * 100,
    ]
    for r in rows[:100]:
        lines.append(f"{str(r['protocol'] or 'any'):<6} "
                     f"{str(r['src_address'])[:24]:<24} "
                     f"{str(r['src_port'] or '-'):<7} "
                     f"{str(r['dst_address'])[:24]:<24} "
                     f"{str(r['dst_port'] or '-'):<7} "
                     f"{_fmt_rate(r['tx_rate']):>12} "
                     f"{_fmt_rate(r['rx_rate']):>12}")
    if not rows:
        lines.append("(no traffic matched the filter during the sample window)")
    lines.append("")
    lines.append(f"Total flows: {result['flow_count']}   "
                 f"TX: {_fmt_rate(result['total_tx_rate'])}   "
                 f"RX: {_fmt_rate(result['total_rx_rate'])}")

    return {
        "tool": "torch",
        "output": "\n".join(lines),
        "summary": {
            "interface": interface,
            "duration": result["duration"],
            "flow_count": result["flow_count"],
            "total_tx_rate": result["total_tx_rate"],
            "total_rx_rate": result["total_rx_rate"],
            "duration_ms": elapsed,
        },
        "results": rows,
    }


# ============================================================
# DISPATCHER
# ============================================================
TOOLS = {
    "ping":       run_ping,
    "traceroute": run_traceroute,
    "dns":        run_dns,
    "nslookup":   run_dns,  # alias
    "whois":      run_whois,
    "blacklist":  run_blacklist,
    "portscan":   run_port_scan,
    "http":       run_http_check,
    "torch":      run_torch,
}

async def dispatch(tool: str, target: str, *, db=None, **kwargs) -> Dict[str, Any]:
    fn = TOOLS.get((tool or "").lower())
    if not fn:
        raise ValueError(f"Unknown tool '{tool}'. Available: {sorted(TOOLS)}")
    if fn is run_torch:
        # Torch doesn't use the `target` field, and needs the db handle to
        # read the MikroTik integration credentials.
        return await fn(target=None, _db=db, **kwargs)
    return await fn(target, **kwargs)
