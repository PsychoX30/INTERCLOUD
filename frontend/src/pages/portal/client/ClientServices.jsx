import React, { useEffect, useRef, useState } from "react";
import { Link as RLink } from "react-router-dom";
import { api, money, shortDate, getToken } from "../../../portal/api";
import { PageHeader, Card, Loading, StatusBadge, EmptyState, btnSecondary } from "../ui";
import { ServerCog, Cpu, Globe, ArrowRight, Copy, Play, Square, RotateCw, KeyRound, Monitor, X } from "lucide-react";
import RFB from "@novnc/novnc";
import { VmMetricsPanel } from "./VmMetricsPanel";

const catIcon = { vps: Cpu, hosting: Globe, colocation: ServerCog, dedicated: Cpu, cloud: Cpu };

const vmChip = {
  running: "bg-emerald-100 text-emerald-700 border-emerald-200",
  stopped: "bg-slate-200 text-slate-700 border-slate-300",
  paused: "bg-amber-100 text-amber-800 border-amber-200",
  unreachable: "bg-red-100 text-red-700 border-red-200",
  unknown: "bg-slate-100 text-slate-500 border-slate-200",
};

const VMControls = ({ serviceId }) => {
  const [vm, setVm] = useState(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);
  const [consoleOpen, setConsoleOpen] = useState(false);

  const load = React.useCallback(() => {
    api.get(`/client/services/${serviceId}/vm`)
      .then((r) => setVm(r.data))
      .catch(() => setVm({ configured: false, status: "unknown" }));
  }, [serviceId]);

  useEffect(() => { load(); }, [load]);

  const act = async (action) => {
    setBusy(action);
    setMsg(null);
    try {
      await api.post(`/client/services/${serviceId}/vm/${action}`);
      setMsg({ ok: true, text: `Perintah ${action} terkirim ke server.` });
      setTimeout(load, 3000);
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Gagal menjalankan aksi." });
    } finally {
      setBusy("");
    }
  };

  const status = vm?.status || "unknown";
  const configured = vm?.configured;
  const running = status === "running";
  const disabled = !configured || !!busy;

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-extrabold text-[#0a2350]">VPS management</div>
        {vm && (
          <span data-testid="vm-status-chip" className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-bold uppercase tracking-wide ${vmChip[status] || vmChip.unknown}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {configured ? status : "not linked"}
          </span>
        )}
      </div>
      {vm?.restart_required && (
        <div data-testid="vm-restart-required" className="mb-3 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2 text-[11px] font-semibold text-amber-800">
          Upgrade spesifikasi berhasil. Silakan <b>Reboot</b> VM dari panel ini agar vCPU/RAM baru diterapkan sepenuhnya.
        </div>
      )}
      <div className="grid grid-cols-3 gap-2">
        <button data-testid="vm-btn-start" className={btnSecondary} disabled={disabled || running} onClick={() => act("start")}>
          <Play className="h-4 w-4" /> {busy === "start" ? "..." : "Start"}
        </button>
        <button data-testid="vm-btn-stop" className={btnSecondary} disabled={disabled || !running} onClick={() => act("stop")}>
          <Square className="h-4 w-4" /> {busy === "stop" ? "..." : "Stop"}
        </button>
        <button data-testid="vm-btn-reboot" className={btnSecondary} disabled={disabled || !running} onClick={() => act("reboot")}>
          <RotateCw className="h-4 w-4" /> {busy === "reboot" ? "..." : "Reboot"}
        </button>
      </div>
      <button
        data-testid="vm-btn-console"
        className={`${btnSecondary} w-full mt-2`}
        disabled={disabled || !running}
        onClick={() => setConsoleOpen(true)}
      >
        <Monitor className="h-4 w-4" /> Console (noVNC)
      </button>
      {msg && (
        <p data-testid="vm-action-msg" className={`mt-3 text-xs font-semibold ${msg.ok ? "text-emerald-600" : "text-red-600"}`}>{msg.text}</p>
      )}
      {vm && !configured && (
        <p className="mt-3 text-[11px] text-slate-500">VM belum terhubung ke layanan ini. Hubungi support untuk aktivasi kontrol mandiri.</p>
      )}
      {vm && configured && running && vm.uptime != null && (
        <p className="mt-3 text-[11px] text-slate-500">Uptime {Math.floor(vm.uptime / 3600)} jam - node {vm.node} - VMID {vm.vmid}</p>
      )}
      {configured && <ResetPasswordPanel serviceId={serviceId} running={running} />}
      {consoleOpen && <VncConsoleModal serviceId={serviceId} onClose={() => { setConsoleOpen(false); load(); }} />}
    </Card>
  );
};

// X11 keysyms untuk tombol spesial console
const KS = {
  Esc: 0xff1b, Tab: 0xff09, Enter: 0xff0d, Backspace: 0xff08, Delete: 0xffff,
  Ctrl: 0xffe3, Alt: 0xffe9, Super: 0xffeb,
  F1: 0xffbe, F2: 0xffbf, F3: 0xffc0, F4: 0xffc1, F5: 0xffc2, F6: 0xffc3,
  F7: 0xffc4, F8: 0xffc5, F9: 0xffc6, F10: 0xffc7, F11: 0xffc8, F12: 0xffc9,
};

const VncConsoleModal = ({ serviceId, onClose }) => {
  const screenRef = useRef(null);
  const rfbRef = useRef(null);
  const [state, setState] = useState("connecting");
  const [err, setErr] = useState("");
  const [info, setInfo] = useState(null);
  const [menu, setMenu] = useState(""); // "keys" | "power" | "paste" | ""
  const [pasteText, setPasteText] = useState("");
  const [pasting, setPasting] = useState(false);
  const [powerMsg, setPowerMsg] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.get(`/client/services/${serviceId}/vm/console`)
      .then(({ data }) => {
        if (cancelled || !screenRef.current) return;
        setInfo(data);
        const base = process.env.REACT_APP_BACKEND_URL.replace(/^http/, "ws");
        const url = `${base}${data.ws_path}?token=${encodeURIComponent(getToken() || "")}` +
                    `&port=${encodeURIComponent(data.port)}&vncticket=${encodeURIComponent(data.ticket)}`;
        const rfb = new RFB(screenRef.current, url, {
          credentials: { password: data.ticket },
          wsProtocols: ["binary"],
        });
        rfb.scaleViewport = true;
        rfb.resizeSession = false;
        rfb.addEventListener("connect", () => setState("connected"));
        rfb.addEventListener("disconnect", (e) => {
          setState("disconnected");
          if (!(e.detail && e.detail.clean)) setErr("Koneksi console terputus. Tutup dan buka kembali.");
        });
        rfb.addEventListener("credentialsrequired", () => rfb.sendCredentials({ password: data.ticket }));
        rfbRef.current = rfb;
      })
      .catch((e) => {
        setState("error");
        setErr(e?.response?.data?.detail || "Gagal membuka console");
      });
    return () => {
      cancelled = true;
      try { rfbRef.current && rfbRef.current.disconnect(); } catch { /* noop */ }
    };
  }, [serviceId]);

  const sendKey = (keysym) => {
    const rfb = rfbRef.current;
    if (!rfb) return;
    try { rfb.sendKey(keysym, null, true); rfb.sendKey(keysym, null, false); } catch { /* noop */ }
    rfb.focus && rfb.focus();
  };

  const sendCombo = (mods, keysym) => {
    const rfb = rfbRef.current;
    if (!rfb) return;
    try {
      mods.forEach((m) => rfb.sendKey(m, null, true));
      rfb.sendKey(keysym, null, true);
      rfb.sendKey(keysym, null, false);
      [...mods].reverse().forEach((m) => rfb.sendKey(m, null, false));
    } catch { /* noop */ }
    rfb.focus && rfb.focus();
  };

  const specialKeys = [
    { label: "Ctrl+Alt+Del", run: () => { try { rfbRef.current?.sendCtrlAltDel(); } catch { /* noop */ } } },
    { label: "Esc", run: () => sendKey(KS.Esc) },
    { label: "Tab", run: () => sendKey(KS.Tab) },
    { label: "Enter", run: () => sendKey(KS.Enter) },
    ...["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"].map((f) => ({
      label: f, run: () => sendKey(KS[f]),
    })),
    { label: "Ctrl+Alt+F2 (TTY2)", run: () => sendCombo([KS.Ctrl, KS.Alt], KS.F2) },
  ];

  // Paste-as-typing: kirim teks sebagai ketikan keyboard ke VM (clipboard 2 arah
  // butuh agent dalam VM, tidak diperlukan untuk kasus umum).
  const pasteToVm = async () => {
    const rfb = rfbRef.current;
    if (!rfb || !pasteText) return;
    setPasting(true);
    try {
      for (const ch of pasteText) {
        let ks;
        if (ch === "\n") ks = KS.Enter;
        else if (ch === "\t") ks = KS.Tab;
        else {
          const cp = ch.codePointAt(0);
          ks = cp < 0x100 ? cp : 0x01000000 + cp;
        }
        rfb.sendKey(ks, null, true);
        rfb.sendKey(ks, null, false);
        await new Promise((r) => setTimeout(r, 12));
      }
      setMenu("");
      setPasteText("");
      rfb.focus && rfb.focus();
    } finally { setPasting(false); }
  };

  const powerAction = async (action, label) => {
    if (!window.confirm(`${label} VM ini sekarang?`)) return;
    setPowerMsg("");
    try {
      await api.post(`/client/services/${serviceId}/vm/${action}`);
      setPowerMsg(`Perintah ${label} terkirim.`);
      setMenu("");
    } catch (e) {
      setPowerMsg(e?.response?.data?.detail || `Gagal menjalankan ${label}.`);
    }
  };

  const menuBtn = "text-[11px] font-bold text-white/70 hover:text-white border border-white/20 rounded-lg px-2.5 py-1";
  const itemBtn = "block w-full text-left px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-white/10 rounded-lg";

  return (
    <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-2 sm:p-6" data-testid="vnc-console-modal">
      <div className="w-full max-w-5xl bg-[#0b0f19] rounded-2xl overflow-hidden shadow-2xl border border-white/10 flex flex-col" style={{ height: "min(80vh, 760px)" }}>
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#0a2350] text-white shrink-0 relative">
          <div className="flex items-center gap-2 text-sm font-bold">
            <Monitor className="h-4 w-4 text-[#f5b120]" />
            VM Console {info ? `- VMID ${info.vmid} @ ${info.node}` : ""}
            <span className={`ml-2 text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-full ${
              state === "connected" ? "bg-emerald-500/20 text-emerald-300"
              : state === "connecting" ? "bg-amber-500/20 text-amber-300"
              : "bg-red-500/20 text-red-300"}`} data-testid="vnc-state">
              {state}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button className={menuBtn} onClick={() => setMenu(menu === "keys" ? "" : "keys")} data-testid="vnc-keys-btn">
                Keys ▾
              </button>
              {menu === "keys" && (
                <div className="absolute right-0 top-8 z-20 w-44 max-h-72 overflow-y-auto bg-[#0b0f19] border border-white/15 rounded-xl p-1.5 shadow-2xl" data-testid="vnc-keys-menu">
                  {specialKeys.map((k) => (
                    <button key={k.label} className={itemBtn} onClick={() => { k.run(); setMenu(""); }} data-testid={`vnc-key-${k.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>
                      {k.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="relative">
              <button className={menuBtn} onClick={() => setMenu(menu === "paste" ? "" : "paste")} data-testid="vnc-paste-btn">
                Paste ▾
              </button>
              {menu === "paste" && (
                <div className="absolute right-0 top-8 z-20 w-72 bg-[#0b0f19] border border-white/15 rounded-xl p-3 shadow-2xl" data-testid="vnc-paste-panel">
                  <p className="text-[10px] text-white/50 mb-2">Teks dikirim sebagai ketikan keyboard ke VM (klik dulu posisi kursor di console).</p>
                  <textarea
                    data-testid="vnc-paste-input"
                    rows={3}
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder="Tempel / ketik teks di sini…"
                    className="w-full rounded-lg bg-white/10 border border-white/15 px-2 py-1.5 text-xs text-white font-mono"
                  />
                  <button
                    data-testid="vnc-paste-send"
                    className="mt-2 w-full rounded-lg bg-[#f5b120] text-[#0a2350] text-xs font-extrabold py-1.5 disabled:opacity-50"
                    disabled={pasting || !pasteText}
                    onClick={pasteToVm}
                  >
                    {pasting ? "Mengetik ke VM…" : "Kirim ke VM"}
                  </button>
                </div>
              )}
            </div>
            <div className="relative">
              <button className={menuBtn} onClick={() => setMenu(menu === "power" ? "" : "power")} data-testid="vnc-power-btn">
                Power ▾
              </button>
              {menu === "power" && (
                <div className="absolute right-0 top-8 z-20 w-48 bg-[#0b0f19] border border-white/15 rounded-xl p-1.5 shadow-2xl" data-testid="vnc-power-menu">
                  <button className={itemBtn} onClick={() => powerAction("start", "Start")} data-testid="vnc-power-start">Start</button>
                  <button className={itemBtn} onClick={() => powerAction("shutdown", "Shutdown (ACPI)")} data-testid="vnc-power-shutdown">Shutdown (ACPI)</button>
                  <button className={itemBtn} onClick={() => powerAction("reset", "Reset (paksa)")} data-testid="vnc-power-reset">Reset (paksa)</button>
                  <button className={`${itemBtn} text-red-300 hover:bg-red-500/20`} onClick={() => powerAction("stop", "Power Off (paksa)")} data-testid="vnc-power-stop">Power Off (paksa)</button>
                </div>
              )}
            </div>
            <button className="text-white/70 hover:text-white" onClick={onClose} data-testid="vnc-close-btn">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
        <div className="flex-1 relative min-h-0" onClick={() => menu && setMenu("")}>
          <div ref={screenRef} className="absolute inset-0" />
          {state === "connecting" && (
            <div className="absolute inset-0 flex items-center justify-center text-white/70 text-sm">Menghubungkan ke console…</div>
          )}
          {powerMsg && (
            <div className="absolute inset-x-0 top-0 bg-[#0a2350]/90 text-white text-xs px-4 py-1.5" data-testid="vnc-power-msg">{powerMsg}</div>
          )}
          {err && (
            <div className="absolute inset-x-0 bottom-0 bg-red-600/90 text-white text-xs px-4 py-2" data-testid="vnc-error">{err}</div>
          )}
        </div>
      </div>
    </div>
  );
};

const genPassword = () => {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%";
  return Array.from(crypto.getRandomValues(new Uint32Array(16)), (n) => chars[n % chars.length]).join("");
};

const ResetPasswordPanel = ({ serviceId, running }) => {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState("root");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    setBusy(true);
    setResult(null);
    try {
      await api.post(`/client/services/${serviceId}/vm/reset-password`, { username, password });
      setResult({ ok: true, text: `Password untuk "${username}" berhasil direset. Simpan password baru Anda sekarang.` });
    } catch (e) {
      setResult({ ok: false, text: e?.response?.data?.detail || "Gagal reset password." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 border-t border-dashed border-slate-200 pt-4">
      <button
        data-testid="vm-reset-pass-toggle"
        className="text-xs font-bold text-[#0a2350] hover:text-[#f5b120] transition-colors flex items-center gap-1.5"
        onClick={() => setOpen(!open)}
      >
        <KeyRound className="h-3.5 w-3.5" /> Reset password akun VM {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="mt-3 space-y-2.5">
          {!running && (
            <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">VM harus running untuk reset password.</p>
          )}
          <div className="grid grid-cols-2 gap-2">
            <input
              data-testid="vm-reset-username"
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Username (root)"
            />
            <div className="flex gap-1.5">
              <input
                data-testid="vm-reset-password"
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono min-w-0 flex-1"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password baru (min 8)"
              />
              <button
                data-testid="vm-reset-generate"
                className="rounded-lg border border-slate-300 px-2.5 text-xs font-bold text-[#0a2350] hover:border-[#f5b120] shrink-0"
                onClick={() => setPassword(genPassword())}
                title="Generate password acak"
              >
                Gen
              </button>
            </div>
          </div>
          <button
            data-testid="vm-reset-submit"
            className={btnSecondary}
            disabled={busy || !running || password.length < 8}
            onClick={submit}
          >
            {busy ? "Memproses..." : "Reset Password"}
          </button>
          {result && (
            <p data-testid="vm-reset-result" className={`text-xs font-semibold ${result.ok ? "text-emerald-600" : "text-red-600"}`}>{result.text}</p>
          )}
        </div>
      )}
    </div>
  );
};

const Stepper = ({ label, unit, value, onChange, max, step = 1 }) => (
  <div className="flex items-center justify-between gap-2">
    <span className="text-xs font-semibold text-slate-600 w-16">{label}</span>
    <div className="flex items-center gap-2">
      <button className="h-7 w-7 rounded-lg border border-slate-300 text-sm font-bold text-[#0a2350] hover:border-[#f5b120] disabled:opacity-50" disabled={value <= 0} onClick={() => onChange(Math.max(0, value - step))}>-</button>
      <span className="w-16 text-center text-sm font-extrabold text-[#0a2350]">+{value} {unit}</span>
      <button className="h-7 w-7 rounded-lg border border-slate-300 text-sm font-bold text-[#0a2350] hover:border-[#f5b120] disabled:opacity-50" disabled={value >= max} onClick={() => onChange(Math.min(max, value + step))}>+</button>
    </div>
  </div>
);

const UpgradePanel = ({ serviceId }) => {
  const [opts, setOpts] = useState(null);
  const [cpu, setCpu] = useState(0);
  const [ram, setRam] = useState(0);
  const [disk, setDisk] = useState(0);
  const [quote, setQuote] = useState(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get(`/client/services/${serviceId}/upgrade/options`).then((r) => setOpts(r.data)).catch(() => setOpts(false));
  }, [serviceId]);

  useEffect(() => {
    setQuote(null);
    setErr("");
    if (cpu + ram + disk === 0) return;
    const t = setTimeout(() => {
      api.post(`/client/services/${serviceId}/upgrade/preview`, { cpu, ram_gb: ram, disk_gb: disk })
        .then((r) => setQuote(r.data))
        .catch((e) => setErr(e?.response?.data?.detail || "Gagal menghitung harga"));
    }, 350);
    return () => clearTimeout(t);
  }, [cpu, ram, disk, serviceId]);

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      const r = await api.post(`/client/services/${serviceId}/upgrade`, { cpu, ram_gb: ram, disk_gb: disk });
      setDone(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal membuat invoice upgrade");
    } finally {
      setBusy(false);
    }
  };

  if (opts === null || opts === false) return null;

  return (
    <Card className="p-5" data-testid="upgrade-panel">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">Upgrade resource</div>
      <p className="text-[11px] text-slate-500 mb-3">Tambah CPU/RAM/Disk secara mandiri. Selisih biaya dihitung prorata sampai tanggal perpanjangan dan ditagihkan otomatis.</p>
      {done ? (
        <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-4 text-sm" data-testid="upgrade-success">
          <div className="font-extrabold text-emerald-700">Invoice {done.number} dibuat - {money(done.total)}</div>
          <p className="text-xs text-emerald-700/90 mt-1">Upgrade diterapkan setelah pembayaran. Setelah lunas, restart VM dari panel ini agar spesifikasi baru aktif. Bayar sekarang di halaman Invoices.</p>
          <RLink to="/portal/client/invoices" className="inline-flex items-center gap-1 mt-2 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]">Buka Invoices <ArrowRight className="h-3 w-3" /></RLink>
        </div>
      ) : opts.pending_upgrade ? (
        <p className="text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2" data-testid="upgrade-pending">Ada upgrade yang menunggu pembayaran. Selesaikan invoice-nya dulu di halaman Invoices.</p>
      ) : (
        <>
          <div className="space-y-2.5">
            <Stepper label="vCPU" unit="core" value={cpu} onChange={setCpu} max={64} />
            <Stepper label="RAM" unit="GB" value={ram} onChange={setRam} max={256} step={2} />
            <Stepper label="Disk" unit="GB" value={disk} onChange={setDisk} max={2000} step={10} />
          </div>
          {quote && (
            <div className="mt-3 rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs space-y-1" data-testid="upgrade-quote">
              <div className="flex justify-between"><span className="text-slate-500">Tambahan biaya bulanan</span><span className="font-bold text-[#0a2350]">{money(quote.monthly_delta)}/bln</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Prorata ({quote.days_left} hari)</span><span className="font-semibold">{money(quote.prorated_charge)}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">PPN {quote.tax_percent}%</span><span className="font-semibold">{money(quote.tax_amount)}</span></div>
              <div className="flex justify-between border-t border-slate-200 pt-1"><span className="font-bold text-[#0a2350]">Tagihan sekarang</span><span className="font-extrabold text-[#0a2350]" data-testid="upgrade-total">{money(quote.total)}</span></div>
            </div>
          )}
          {err && <p className="mt-2 text-xs font-semibold text-red-600" data-testid="upgrade-error">{err}</p>}
          <button
            data-testid="upgrade-submit"
            className={`${btnSecondary} mt-3`}
            disabled={busy || !quote}
            onClick={submit}
          >
            {busy ? "Memproses..." : "Buat Invoice Upgrade"}
          </button>
        </>
      )}
    </Card>
  );
};


const ClientServices = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);

  useEffect(() => {
    api.get("/client/services").then((r) => setRows(r.data));
  }, []);

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader
        title="My Services"
        subtitle="Active products & instances tied to your account. Click any service to see connection details and management shortcuts."
      />
      {rows.length === 0 && <EmptyState title="No services yet" body="Order a new service from the Order tab." />}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {rows.map((s) => {
          const Icon = catIcon[s.category] || ServerCog;
          return (
            <button
              key={s.id}
              onClick={() => setActive(s)}
              data-testid={`service-${s.id}`}
              className="text-left rounded-2xl bg-white border border-slate-200 hover:border-[#f5b120] hover:shadow-lg transition-all p-5"
            >
              <div className="flex items-start justify-between">
                <div className="h-11 w-11 rounded-xl bg-[#0a2350] flex items-center justify-center">
                  <Icon className="h-5 w-5 text-[#f5b120]" strokeWidth={1.9} />
                </div>
                <StatusBadge status={s.status} />
              </div>
              <div className="mt-4 text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">
                {s.category}
              </div>
              <div className="text-lg font-extrabold text-[#0a2350] leading-tight">{s.product_name}</div>
              <div className="text-sm text-slate-500 mt-1">{s.name}</div>
              <div className="mt-4 border-t border-dashed border-slate-200 pt-3 flex items-center justify-between text-sm">
                <span className="text-slate-500">Next renewal</span>
                <span className="font-semibold">{shortDate(s.next_renewal)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-sm">
                <span className="text-slate-500">Monthly</span>
                <span className="font-extrabold text-[#0a2350]">{money(s.price_monthly)}</span>
              </div>
            </button>
          );
        })}
      </div>

      {active && <ServiceDetail service={active} onClose={() => setActive(null)} />}
    </div>
  );
};

const CopyRow = ({ label, value }) => {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
      <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm text-[#0a2350]">{value || "-"}</span>
        {value && value !== "-" && (
          <button
            onClick={() => {
              navigator.clipboard.writeText(String(value));
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            }}
            className="text-slate-400 hover:text-[#f5b120]"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
        {copied && <span className="text-[10px] text-emerald-600 font-bold">Copied</span>}
      </div>
    </div>
  );
};

const AutoRenewToggle = ({ service }) => {
  const [on, setOn] = useState(service.auto_renew !== false);
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      const r = await api.put(`/client/services/${service.id}/auto-renew`, { auto_renew: !on });
      setOn(r.data.auto_renew);
      service.auto_renew = r.data.auto_renew;
    } finally { setBusy(false); }
  };
  return (
    <Card className="p-5" data-testid="auto-renew-panel">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-extrabold text-[#0a2350]">Auto-renewal</div>
          <p className="mt-1 text-xs text-slate-500">
            {on
              ? "Invoice perpanjangan dibuat otomatis sebelum jatuh tempo. Layanan tetap aktif tanpa perlu order ulang."
              : "Auto-renewal mati. Layanan TIDAK akan diperpanjang otomatis dan bisa nonaktif setelah tanggal renewal."}
          </p>
        </div>
        <button
          onClick={toggle}
          disabled={busy}
          aria-pressed={on}
          data-testid="auto-renew-toggle"
          className={`relative w-12 h-7 rounded-full transition-colors flex-shrink-0 ${on ? "bg-emerald-500" : "bg-slate-300"} ${busy ? "opacity-60" : ""}`}
        >
          <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-6" : "left-1"}`} />
        </button>
      </div>
    </Card>
  );
};

const TerminateRequestPanel = ({ service }) => {
  const [req, setReq] = useState(service.termination_request || null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (service.status === "terminated") {
    return (
      <Card className="p-5" data-testid="terminate-panel">
        <div className="text-sm font-extrabold text-red-700">Layanan telah diakhiri</div>
        <p className="mt-1 text-xs text-slate-500">Layanan ini sudah diterminasi. Hubungi sales untuk mengaktifkan layanan baru.</p>
      </Card>
    );
  }

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      const { data } = await api.post(`/client/services/${service.id}/terminate-request`, { reason });
      setReq(data.termination_request);
      service.termination_request = data.termination_request;
      setOpen(false);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal mengirim permintaan");
    } finally { setBusy(false); }
  };

  const cancel = async () => {
    setBusy(true); setErr("");
    try {
      await api.delete(`/client/services/${service.id}/terminate-request`);
      setReq(null);
      service.termination_request = null;
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal membatalkan permintaan");
    } finally { setBusy(false); }
  };

  const status = req?.status;
  return (
    <Card className="p-5" data-testid="terminate-panel">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">Akhiri layanan</div>
      {status === "pending" ? (
        <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-xs" data-testid="terminate-pending">
          <div className="font-bold text-amber-800">Permintaan pengakhiran menunggu persetujuan tim kami.</div>
          {req.reason && <p className="text-amber-700 mt-1">Alasan: {req.reason}</p>}
          <button onClick={cancel} disabled={busy} className="mt-2 text-xs font-bold text-red-600 hover:underline disabled:opacity-50" data-testid="terminate-cancel-btn">
            Batalkan permintaan
          </button>
        </div>
      ) : status === "rejected" ? (
        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3 text-xs">
          <div className="font-bold text-slate-700">Permintaan sebelumnya ditolak.</div>
          {req.note && <p className="text-slate-500 mt-1">Catatan: {req.note}</p>}
          <button onClick={() => { setReq(null); setOpen(true); }} className="mt-2 text-xs font-bold text-[#0a2350] hover:underline" data-testid="terminate-rerequest-btn">
            Ajukan lagi
          </button>
        </div>
      ) : open ? (
        <div className="space-y-2.5">
          <p className="text-[11px] text-slate-500">Permintaan pengakhiran perlu disetujui admin/support/sales. Layanan tetap aktif sampai disetujui.</p>
          <textarea
            data-testid="terminate-reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Alasan mengakhiri layanan (opsional)"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <div className="flex items-center gap-2">
            <button onClick={submit} disabled={busy} className="px-3 py-2 rounded-lg bg-red-600 text-white text-xs font-bold disabled:opacity-50" data-testid="terminate-submit-btn">
              {busy ? "Mengirim..." : "Kirim permintaan"}
            </button>
            <button onClick={() => setOpen(false)} disabled={busy} className="px-3 py-2 rounded-lg border border-slate-300 text-xs font-bold text-slate-600">
              Batal
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="text-[11px] text-slate-500 mb-2">Ingin mengakhiri layanan ini? Ajukan permintaan; tim kami akan meninjau &amp; menyetujui.</p>
          <button onClick={() => setOpen(true)} className="px-3 py-2 rounded-lg border border-red-200 text-red-600 text-xs font-bold hover:bg-red-50" data-testid="terminate-request-btn">
            Ajukan pengakhiran layanan
          </button>
        </>
      )}
      {err && <p className="mt-2 text-xs font-semibold text-red-600" data-testid="terminate-error">{err}</p>}
    </Card>
  );
};

const ServiceDetail = ({ service, onClose }) => {
  const s = service;
  const isVPS = s.category === "vps" || s.category === "dedicated" || s.category === "cloud";
  const isHosting = s.category === "hosting";
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
      >
        <div className="p-6 bg-[#0a2350] text-white flex items-start justify-between">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{s.category}</div>
            <div className="text-xl font-extrabold">{s.product_name}</div>
            <div className="text-sm text-white/70 mt-0.5">{s.name}</div>
          </div>
          <button className="text-white/70 hover:text-white text-2xl leading-none" onClick={onClose}>×</button>
        </div>
        <div className="p-6 overflow-y-auto space-y-5">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Status</div>
              <div className="mt-1"><StatusBadge status={s.status} /></div>
            </div>
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Start</div>
              <div className="mt-1 text-sm font-semibold">{shortDate(s.start_date)}</div>
            </div>
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Renewal</div>
              <div className="mt-1 text-sm font-semibold">{shortDate(s.next_renewal)}</div>
            </div>
          </div>

          <Card className="p-5">
            <div className="text-sm font-extrabold text-[#0a2350] mb-2">Connection details</div>
            <CopyRow label="IP Address" value={s.config?.ip} />
            <CopyRow label="Hostname" value={s.config?.hostname} />
            {isVPS && <CopyRow label="OS" value={s.config?.os} />}
            {isVPS && <CopyRow label="Proxmox Node" value={s.config?.node} />}
            {isHosting && <CopyRow label="Control Panel" value={s.config?.control_panel} />}
            {s.category === "colocation" && <CopyRow label="Rack" value={s.config?.rack} />}
          </Card>

          {isVPS && s.status !== "terminated" && <VMControls serviceId={s.id} />}
          {isVPS && s.status !== "terminated" && <VmMetricsPanel serviceId={s.id} />}
          {isVPS && s.status === "active" && <UpgradePanel serviceId={s.id} />}
          <AutoRenewToggle service={s} />
          <TerminateRequestPanel service={s} />

          {isHosting && (
            <Card className="p-5">
              <div className="text-sm font-extrabold text-[#0a2350] mb-3">Hosting management</div>
              <p className="mt-3 text-[11px] text-slate-500">Manajemen hosting (cPanel/Plesk) tampil di sini setelah admin mengaktifkan integrasi panel di portal.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};

export default ClientServices;
