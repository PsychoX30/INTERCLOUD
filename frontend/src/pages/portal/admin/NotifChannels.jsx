import React, { useState } from "react";
import { Card, btnSecondary, inputClass, labelClass } from "../ui";
import { BellRing, Mail, MessageCircle, Send, Webhook, Plus, Trash2, Check, X } from "lucide-react";

// Konfigurasi saluran notifikasi (data tiruan / CRUD lokal) - dispatcher live menyusul di fase backend.
const CHANNEL_META = {
  email: { label: "Email", icon: Mail, ph: "noc@perusahaan.com" },
  whatsapp: { label: "WhatsApp", icon: MessageCircle, ph: "0812xxxxxxx" },
  telegram: { label: "Telegram", icon: Send, ph: "@channel_atau_chat_id" },
  webhook: { label: "Webhook", icon: Webhook, ph: "https://hooks.contoh.com/..." },
};

const DEFAULT_CHANNELS = [
  { id: "c1", type: "email", target: "noc@intercloud-digital.com", events: ["ddos", "device_down"], enabled: true },
  { id: "c2", type: "whatsapp", target: "081310564242", events: ["ddos"], enabled: true },
  { id: "c3", type: "telegram", target: "@intercloud_noc", events: ["device_down"], enabled: false },
];

const EVENTS = [
  { key: "ddos", label: "Insiden DDoS" },
  { key: "device_down", label: "Device down" },
  { key: "invoice_overdue", label: "Invoice overdue" },
];

export const NotifChannels = () => {
  const [channels, setChannels] = useState(DEFAULT_CHANNELS);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ type: "email", target: "", events: ["ddos"] });

  const add = () => {
    if (!form.target.trim()) return;
    setChannels((cs) => [...cs, { ...form, id: `c${Date.now()}`, enabled: true }]);
    setAdding(false);
    setForm({ type: "email", target: "", events: ["ddos"] });
  };
  const del = (id) => setChannels((cs) => cs.filter((c) => c.id !== id));
  const toggle = (id) => setChannels((cs) => cs.map((c) => (c.id === id ? { ...c, enabled: !c.enabled } : c)));
  const toggleEvent = (k) => setForm((f) => ({
    ...f,
    events: f.events.includes(k) ? f.events.filter((e) => e !== k) : [...f.events, k],
  }));

  return (
    <Card className="overflow-hidden mb-6" data-testid="notif-channels">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <BellRing className="h-3.5 w-3.5 text-[#f5b120]" /> Saluran Notifikasi
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Ke mana alert insiden dikirim (data tiruan / CRUD lokal). Dispatcher live menyusul di fase backend.</div>
        </div>
        <button className={btnSecondary} onClick={() => setAdding(!adding)} data-testid="channel-add-toggle">
          <Plus className="h-4 w-4" /> Tambah Saluran
        </button>
      </div>

      {adding && (
        <div className="px-5 py-4 bg-[#f5b120]/5 border-b border-[#f5b120]/30" data-testid="channel-form">
          <div className="grid sm:grid-cols-3 gap-3">
            <label><div className={labelClass}>Tipe</div>
              <select className={inputClass} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} data-testid="channel-type">
                {Object.entries(CHANNEL_META).map(([k, m]) => <option key={k} value={k}>{m.label}</option>)}
              </select></label>
            <label className="sm:col-span-2"><div className={labelClass}>Tujuan *</div>
              <input className={inputClass} value={form.target} placeholder={CHANNEL_META[form.type].ph} onChange={(e) => setForm({ ...form, target: e.target.value })} data-testid="channel-target" /></label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={labelClass}>Event:</span>
            {EVENTS.map((ev) => (
              <button
                key={ev.key}
                onClick={() => toggleEvent(ev.key)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-bold border transition-colors ${form.events.includes(ev.key) ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"}`}
                data-testid={`channel-event-${ev.key}`}
              >
                {ev.label}
              </button>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <button className={btnSecondary} onClick={add} data-testid="channel-save"><Check className="h-4 w-4" /> Simpan</button>
            <button className={btnSecondary} onClick={() => setAdding(false)}><X className="h-4 w-4" /> Batal</button>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {channels.map((c) => {
          const m = CHANNEL_META[c.type];
          return (
            <div key={c.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`channel-row-${c.id}`}>
              <button
                onClick={() => toggle(c.id)}
                className={`relative h-5 w-9 rounded-full transition-colors ${c.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
                data-testid={`channel-toggle-${c.id}`}
              >
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${c.enabled ? "left-[18px]" : "left-0.5"}`} />
              </button>
              <span className="inline-flex items-center gap-1.5 text-sm font-bold text-[#0a2350] min-w-[110px]">
                <m.icon className="h-4 w-4 text-[#f5b120]" /> {m.label}
              </span>
              <span className={`font-mono text-xs ${c.enabled ? "text-slate-700" : "text-slate-400"}`}>{c.target}</span>
              <div className="flex flex-wrap gap-1">
                {c.events.map((e) => (
                  <span key={e} className="text-[10px] font-bold uppercase bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5 text-slate-500">
                    {EVENTS.find((x) => x.key === e)?.label || e}
                  </span>
                ))}
              </div>
              <button className="ml-auto p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50" onClick={() => del(c.id)} data-testid={`channel-del-${c.id}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

export default NotifChannels;
