import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, btnPrimary, inputClass, labelClass } from "../ui";
import {
  TerminalSquare, Loader2, PlayCircle, Copy, Signal, Route, Search,
  Info, Globe2, Radar, Shield, AlertTriangle, Activity,
} from "lucide-react";

const TOOLS = [
  { key: "ping",       label: "Ping",         icon: Signal,   hint: "ICMP echo probes" },
  { key: "traceroute", label: "Traceroute",   icon: Route,    hint: "Hop-by-hop path" },
  { key: "dns",        label: "DNS Lookup",   icon: Search,   hint: "A / AAAA / MX / TXT / …" },
  { key: "whois",      label: "WHOIS",        icon: Info,     hint: "Domain / IP record" },
  { key: "blacklist",  label: "DNSBL",        icon: Shield,   hint: "8 major blocklists" },
  { key: "portscan",   label: "Port Scan",    icon: Radar,    hint: "TCP on common ports" },
  { key: "http",       label: "HTTP Check",   icon: Globe2,   hint: "Fetch + status/headers" },
  { key: "torch",      label: "MikroTik Torch", icon: Activity, hint: "Live flow monitor (RouterOS)" },
];

const RECORD_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "PTR", "ANY"];
const PROTOCOLS = ["any", "tcp", "udp", "icmp", "gre", "esp", "ah", "ospf"];

const AdminDiagnostics = () => {
  const [tool, setTool] = useState("ping");
  const [target, setTarget] = useState("google.com");
  const [record, setRecord] = useState("A");
  const [count, setCount] = useState(5);
  const [maxHops, setMaxHops] = useState(15);
  // Torch state
  const [interfaces, setInterfaces] = useState([]);
  const [iface, setIface] = useState("");
  const [srcAddr, setSrcAddr] = useState("0.0.0.0/0");
  const [dstAddr, setDstAddr] = useState("0.0.0.0/0");
  const [proto, setProto] = useState("any");
  const [port, setPort] = useState("any");
  const [duration, setDuration] = useState(2);

  const [availableTools, setAvailableTools] = useState(null);
  const [toolMeta, setToolMeta] = useState({});
  const [mikrotikReady, setMikrotikReady] = useState(false);
  const [out, setOut] = useState("");
  const [summary, setSummary] = useState(null);
  const [torchRows, setTorchRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/admin/diagnostics/tools").then((r) => {
      setAvailableTools(r.data.tools);
      setToolMeta(r.data.meta || {});
      setMikrotikReady(!!r.data.mikrotik_ready);
    }).catch(() => setAvailableTools([]));
  }, []);

  // Lazy-load interfaces when torch is selected
  useEffect(() => {
    if (tool === "torch" && mikrotikReady && interfaces.length === 0) {
      api.get("/admin/mikrotik/interfaces").then((r) => {
        const list = Array.isArray(r.data) ? r.data : [];
        setInterfaces(list);
        if (!iface && list[0]) setIface(list[0].name || list[0][".id"] || "");
      }).catch(() => setInterfaces([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, mikrotikReady]);

  const run = async (e) => {
    e?.preventDefault?.();
    setBusy(true); setOut(""); setErr(""); setSummary(null); setTorchRows(null);
    try {
      const payload = { tool };
      if (tool !== "torch") payload.target = target;
      if (tool === "ping") payload.count = Number(count);
      if (tool === "traceroute") payload.max_hops = Number(maxHops);
      if (tool === "dns") payload.record = record;
      if (tool === "torch") {
        payload.interface = iface;
        payload.src_address = srcAddr || "0.0.0.0/0";
        payload.dst_address = dstAddr || "0.0.0.0/0";
        payload.protocol = proto || "any";
        payload.port = port || "any";
        payload.duration = Number(duration);
      }
      const { data } = await api.post("/admin/diagnostics/run", payload);
      setOut(data.output || "(no output)");
      setSummary(data.summary || null);
      if (data.tool === "torch") setTorchRows(data.results || []);
    } catch (er) {
      setErr(er?.response?.data?.detail || er.message);
    } finally {
      setBusy(false);
    }
  };

  const copy = () => { navigator.clipboard.writeText(out); };
  const current = TOOLS.find((t) => t.key === tool);
  const CurrentIcon = current?.icon || TerminalSquare;
  const isToolAvailable = (t) => {
    if (t.key === "torch") return mikrotikReady;
    return !availableTools || availableTools.includes(t.key);
  };

  const fmtRate = (bps) => {
    if (!bps) return "0";
    if (bps >= 1e9) return (bps/1e9).toFixed(2) + " Gbps";
    if (bps >= 1e6) return (bps/1e6).toFixed(2) + " Mbps";
    if (bps >= 1e3) return (bps/1e3).toFixed(1) + " kbps";
    return bps + " bps";
  };

  return (
    <div>
      <PageHeader
        title="Diagnostic Tools"
        subtitle="Real network diagnostics executed from the portal host + MikroTik Torch via the configured RouterOS integration."
      />

      {/* Tool picker */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 mb-5" data-testid="diag-tool-picker">
        {TOOLS.map((t) => {
          const Icon = t.icon;
          const avail = isToolAvailable(t);
          return (
            <button
              key={t.key}
              type="button"
              disabled={!avail}
              onClick={() => setTool(t.key)}
              data-testid={`diag-tool-${t.key}`}
              className={`px-3 py-3 rounded-xl border text-left transition-colors ${
                tool === t.key
                  ? "border-[#0a2350] bg-[#0a2350] text-white shadow-sm"
                  : avail
                    ? "border-slate-200 bg-white text-[#0a2350] hover:border-[#f5b120]"
                    : "border-slate-100 bg-slate-50 text-slate-300 cursor-not-allowed"
              }`}
              title={t.hint}
            >
              <div className="flex items-center gap-2 font-bold text-sm">
                <Icon className="h-4 w-4" /> {t.label}
              </div>
              <div className={`mt-0.5 text-[10px] leading-tight ${tool === t.key ? "text-white/80" : "text-slate-500"}`}>{t.hint}</div>
            </button>
          );
        })}
      </div>

      {tool === "torch" && !mikrotikReady && (
        <Card className="p-4 mb-4 bg-amber-50 border border-amber-200 text-amber-800">
          <div className="flex items-start gap-2 text-sm">
            <AlertTriangle className="h-4 w-4 mt-0.5" />
            <div>
              <div className="font-bold">MikroTik integration not configured</div>
              <div>Go to <b>Admin ▸ Integrations ▸ MikroTik RouterOS</b>, paste host + credentials, hit Test, and enable. Torch reads live flows via the RouterOS API.</div>
            </div>
          </div>
        </Card>
      )}

      <Card className="p-5 mb-5">
        <form onSubmit={run} className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
          {tool !== "torch" && (
            <div className="md:col-span-3">
              <div className={labelClass}>Target ({tool === "http" ? "URL or host" : "hostname or IP"})</div>
              <input required value={target} onChange={(e) => setTarget(e.target.value)} className={inputClass}
                placeholder={tool === "http" ? "https://example.com" : "google.com or 8.8.8.8"} data-testid="diag-target-input" />
            </div>
          )}

          {tool === "ping" && (
            <div><div className={labelClass}>Packets</div>
              <input type="number" min="1" max="10" value={count} onChange={(e) => setCount(e.target.value)} className={inputClass} data-testid="diag-count" />
            </div>
          )}
          {tool === "traceroute" && (
            <div><div className={labelClass}>Max hops</div>
              <input type="number" min="1" max="30" value={maxHops} onChange={(e) => setMaxHops(e.target.value)} className={inputClass} data-testid="diag-hops" />
            </div>
          )}
          {tool === "dns" && (
            <div><div className={labelClass}>Record</div>
              <select value={record} onChange={(e) => setRecord(e.target.value)} className={inputClass} data-testid="diag-record">
                {RECORD_TYPES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          )}

          {tool === "torch" && (
            <>
              <div className="md:col-span-2">
                <div className={labelClass}>Interface *</div>
                <select required value={iface} onChange={(e) => setIface(e.target.value)} className={inputClass} data-testid="diag-torch-interface">
                  <option value="">— pick interface —</option>
                  {interfaces.map((it, i) => (
                    <option key={i} value={it.name || it[".id"]}>
                      {it.name || it[".id"]}{it.type ? ` (${it.type})` : ""}{it.running === "false" ? " · down" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className={labelClass}>Src address / CIDR</div>
                <input value={srcAddr} onChange={(e) => setSrcAddr(e.target.value)} className={inputClass} placeholder="0.0.0.0/0" data-testid="diag-torch-src" />
              </div>
              <div>
                <div className={labelClass}>Dst address / CIDR</div>
                <input value={dstAddr} onChange={(e) => setDstAddr(e.target.value)} className={inputClass} placeholder="0.0.0.0/0" data-testid="diag-torch-dst" />
              </div>
              <div>
                <div className={labelClass}>Protocol</div>
                <select value={proto} onChange={(e) => setProto(e.target.value)} className={inputClass} data-testid="diag-torch-proto">
                  {PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <div className={labelClass}>Port</div>
                <input value={port} onChange={(e) => setPort(e.target.value)} className={inputClass} placeholder="any / 443 / 80-90" data-testid="diag-torch-port" />
              </div>
              <div>
                <div className={labelClass}>Duration (s)</div>
                <input type="number" min="1" max="10" value={duration} onChange={(e) => setDuration(e.target.value)} className={inputClass} data-testid="diag-torch-duration" />
              </div>
            </>
          )}

          <div className={tool === "torch" ? "md:col-span-6" : "md:col-span-2"}>
            <button className={btnPrimary} disabled={busy || (tool === "torch" && (!mikrotikReady || !iface))} data-testid="diag-run-btn">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              {busy ? "Running…" : (tool === "torch" ? `Torch ${iface || "…"}` : "Run")}
            </button>
          </div>
        </form>
      </Card>

      {err && (
        <Card className="p-4 mb-4 bg-red-50 border border-red-200 text-red-700" data-testid="diag-error">
          <div className="flex items-center gap-2 text-sm">
            <AlertTriangle className="h-4 w-4" /> {typeof err === "string" ? err : JSON.stringify(err)}
          </div>
        </Card>
      )}

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4" data-testid="diag-summary">
          {Object.entries(summary).slice(0, 8).map(([k, v]) => (
            <div key={k} className="rounded-xl bg-white border border-slate-200 px-4 py-3">
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">{k}</div>
              <div className="text-sm font-bold text-[#0a2350] tabular-nums truncate">
                {v === null || v === undefined ? "—" : (typeof v === "number" && k.includes("rate")) ? fmtRate(v) : String(v)}
              </div>
            </div>
          ))}
        </div>
      )}

      {torchRows && torchRows.length > 0 && (
        <Card className="p-0 overflow-hidden mb-5" data-testid="diag-torch-table">
          <div className="px-4 py-2 border-b border-slate-100 bg-slate-50 text-xs font-bold uppercase tracking-widest text-[#0a2350]">
            Live flows · sorted by combined TX+RX
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left">Proto</th>
                  <th className="px-3 py-2 text-left">Src Address</th>
                  <th className="px-3 py-2 text-left">Src Port</th>
                  <th className="px-3 py-2 text-left">Dst Address</th>
                  <th className="px-3 py-2 text-left">Dst Port</th>
                  <th className="px-3 py-2 text-right">TX</th>
                  <th className="px-3 py-2 text-right">RX</th>
                </tr>
              </thead>
              <tbody>
                {torchRows.slice(0, 100).map((r, i) => (
                  <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-3 py-2 uppercase text-xs font-bold text-[#f5b120]">{r.protocol || "any"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.src_address || "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.src_port || "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.dst_address || "—"}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.dst_port || "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-semibold text-emerald-700">{fmtRate(r.tx_rate)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-semibold text-[#0a2350]">{fmtRate(r.rx_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-100 flex items-center gap-2 bg-slate-50">
          <CurrentIcon className="h-4 w-4 text-[#0a2350]" />
          <span className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">{current?.label} · {tool === "torch" ? (iface || "—") : (target || "—")}</span>
          <button type="button" onClick={copy} disabled={!out} className={`ml-auto text-xs ${out ? "text-[#0a2350] hover:text-[#f5b120]" : "text-slate-300"}`} data-testid="diag-copy">
            <Copy className="h-3 w-3 inline" /> Copy
          </button>
        </div>
        <pre className="bg-slate-900 text-emerald-300 text-xs p-5 overflow-x-auto min-h-[280px] font-mono whitespace-pre-wrap" data-testid="diag-output">
{busy ? "Running…\n" : (out || "// Output will appear here after running a tool")}
        </pre>
      </Card>
    </div>
  );
};

export default AdminDiagnostics;
