import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import { Save, Loader2, Plus, Trash2, ExternalLink, Globe } from "lucide-react";

const BASE = process.env.REACT_APP_BACKEND_URL;

const AdminStatusPage = () => {
  const [cfg, setCfg] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");

  const load = () => api.get("/admin/status-page/config").then((r) => setCfg(r.data));
  useEffect(() => { load(); }, []);
  if (!cfg) return <Loading />;

  const setGroup = (i, patch) => {
    const groups = [...(cfg.groups || [])];
    groups[i] = { ...groups[i], ...patch };
    setCfg({ ...cfg, groups });
  };
  const addGroup = () => {
    const groups = [...(cfg.groups || []), { key: `group_${Date.now()}`, label: "New Group" }];
    setCfg({ ...cfg, groups });
  };
  const removeGroup = (i) => {
    const groups = [...(cfg.groups || [])];
    groups.splice(i, 1);
    setCfg({ ...cfg, groups });
  };

  const save = async () => {
    setSaving(true); setErr(""); setSaved(false);
    try {
      const { data } = await api.put("/admin/status-page/config", cfg);
      setCfg(data); setSaved(true); setTimeout(() => setSaved(false), 2500);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    finally { setSaving(false); }
  };

  return (
    <div data-testid="status-page-config">
      <PageHeader
        title="Public Status Page"
        subtitle="Konfigurasi halaman status publik di /status. Perangkat MikroTik dikelompokkan ke label abstrak — nama device dan IP tidak pernah bocor ke publik."
        actions={
          <a href={`${BASE.replace(/\/$/, '')}/status`} target="_blank" rel="noreferrer" className={btnSecondary} data-testid="status-page-preview">
            <ExternalLink className="h-4 w-4" /> Preview public page
          </a>
        }
      />

      <Card className="p-5 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <label className={labelClass}>Company display name</label>
            <input value={cfg.company || ""} onChange={(e) => setCfg({ ...cfg, company: e.target.value })}
                   className={inputClass} data-testid="status-company" />
          </div>
        </div>
        <div>
          <label className={labelClass}>Active incident note (optional)</label>
          <textarea value={cfg.incident_note || ""} onChange={(e) => setCfg({ ...cfg, incident_note: e.target.value })}
                    rows={2} placeholder="Kosongkan bila tidak ada gangguan. Bila diisi, akan ditampilkan sebagai banner kuning di /status."
                    className={inputClass + " h-auto py-2"} data-testid="status-incident-note" />
        </div>
      </Card>

      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-bold text-[#0a2350]">Service Groups</div>
            <div className="text-xs text-slate-500">Assign each MikroTik device's <code className="bg-slate-100 px-1 rounded">status_group</code> to one of these keys.</div>
          </div>
          <button onClick={addGroup} className={btnSecondary} data-testid="status-add-group"><Plus className="h-4 w-4" /> Add group</button>
        </div>

        {(cfg.groups || []).length === 0 && (
          <div className="text-center py-8 text-slate-500 text-sm">No groups configured. Add one to start.</div>
        )}
        <div className="space-y-2">
          {(cfg.groups || []).map((g, i) => (
            <div key={i} className="flex items-center gap-2 border border-slate-200 rounded-lg p-3" data-testid={`status-group-${i}`}>
              <div className="flex-1 grid grid-cols-2 gap-2">
                <div>
                  <label className={labelClass}>Key (internal)</label>
                  <input value={g.key} onChange={(e) => setGroup(i, { key: e.target.value })}
                         className={inputClass + " font-mono text-xs"} data-testid={`status-group-key-${i}`} />
                </div>
                <div>
                  <label className={labelClass}>Public label</label>
                  <input value={g.label} onChange={(e) => setGroup(i, { label: e.target.value })}
                         className={inputClass} data-testid={`status-group-label-${i}`} />
                </div>
              </div>
              <button onClick={() => removeGroup(i)} className="text-red-600 hover:text-red-800 p-2" data-testid={`status-group-remove-${i}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>

        <div className="mt-5 flex items-center gap-3">
          <button onClick={save} disabled={saving} className={btnPrimary} data-testid="status-save">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? "Saving…" : "Save configuration"}
          </button>
          {saved && <span className="text-sm font-bold text-emerald-600">Tersimpan ✓</span>}
          {err && <span className="text-sm text-red-700">{err}</span>}
        </div>
      </Card>
    </div>
  );
};

export default AdminStatusPage;
