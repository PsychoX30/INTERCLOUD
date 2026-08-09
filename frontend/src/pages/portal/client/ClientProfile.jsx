import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../portal/api";
import { useAuth } from "../../../portal/AuthContext";
import { PageHeader, Card, btnPrimary, inputClass, labelClass } from "../ui";
import { User, Building2, Phone, MapPin, Hash, CheckCircle2, XCircle, AlertTriangle } from "lucide-react";

const ClientProfile = () => {
  const { user, refresh } = useAuth();
  const [form, setForm] = useState({
    name: "", company: "", phone: "", attention: "",
    address_line1: "", address_line2: "", city: "",
    province: "", postal_code: "", country: "Indonesia",
    npwp: "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (user) {
      setForm({
        name: user.name || "",
        company: user.company || "",
        phone: user.phone || "",
        attention: user.attention || "",
        address_line1: user.address_line1 || "",
        address_line2: user.address_line2 || "",
        city: user.city || "",
        province: user.province || "",
        postal_code: user.postal_code || "",
        country: user.country || "Indonesia",
        npwp: user.npwp || "",
      });
    }
  }, [user]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const save = async () => {
    setBusy(true); setMsg(""); setErr("");
    try {
      await api.put("/auth/me", form);
      await refresh();
      setMsg("Profil berhasil diperbarui.");
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan profil.");
    } finally { setBusy(false); }
  };

  if (!user) return null;

  const isComplete =
    form.name && form.company && form.phone &&
    form.address_line1 && form.city && form.province && form.postal_code;

  return (
    <div>
      <PageHeader
        title="Profil"
        subtitle="Data profil Anda digunakan untuk registrasi domain dan billing. Lengkapi semua field agar domain dapat didaftarkan atas nama Anda sendiri."
      />

      {msg && (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 p-4 flex items-center gap-3 text-sm" data-testid="profile-success">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{msg}</span>
        </div>
      )}
      {err && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 text-red-800 p-4 flex items-center gap-3 text-sm" data-testid="profile-error">
          <XCircle className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{err}</span>
        </div>
      )}

      <Card className="p-6">
        <div className="flex items-center gap-2 mb-4">
          <User className="h-5 w-5 text-[#0a2350]" />
          <h2 className="text-lg font-extrabold text-[#0a2350]">Informasi Pribadi</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Nama Lengkap *</span>
            <input value={form.name} onChange={set("name")} className={inputClass} placeholder="Budi Santoso" data-testid="profile-name" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Email</span>
            <input value={user.email} disabled className={`${inputClass} bg-slate-50 text-slate-500`} />
          </label>
        </div>
      </Card>

      <Card className="p-6 mt-4">
        <div className="flex items-center gap-2 mb-4">
          <Building2 className="h-5 w-5 text-[#0a2350]" />
          <h2 className="text-lg font-extrabold text-[#0a2350]">Perusahaan</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Nama Perusahaan / Organisasi *</span>
            <input value={form.company} onChange={set("company")} className={inputClass} placeholder="PT Contoh Digital" data-testid="profile-company" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>NPWP</span>
            <input value={form.npwp} onChange={set("npwp")} className={inputClass} placeholder="00.000.000.0-000.000" data-testid="profile-npwp" />
          </label>
        </div>
      </Card>

      <Card className="p-6 mt-4">
        <div className="flex items-center gap-2 mb-4">
          <MapPin className="h-5 w-5 text-[#0a2350]" />
          <h2 className="text-lg font-extrabold text-[#0a2350]">Alamat</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block sm:col-span-2">
            <span className={`${labelClass} mb-1 block`}>Alamat Baris 1 *</span>
            <input value={form.address_line1} onChange={set("address_line1")} className={inputClass} placeholder="Jl. Sudirman Kav. 52-53" data-testid="profile-addr1" />
          </label>
          <label className="block sm:col-span-2">
            <span className={`${labelClass} mb-1 block`}>Alamat Baris 2</span>
            <input value={form.address_line2} onChange={set("address_line2")} className={inputClass} placeholder="Gedung, lantai, unit" data-testid="profile-addr2" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Kota *</span>
            <input value={form.city} onChange={set("city")} className={inputClass} placeholder="Jakarta Pusat" data-testid="profile-city" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Provinsi *</span>
            <input value={form.province} onChange={set("province")} className={inputClass} placeholder="DKI Jakarta" data-testid="profile-province" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Kode Pos *</span>
            <input value={form.postal_code} onChange={set("postal_code")} className={inputClass} placeholder="10340" data-testid="profile-postal" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Negara</span>
            <input value={form.country} onChange={set("country")} className={inputClass} placeholder="Indonesia" data-testid="profile-country" />
          </label>
        </div>
      </Card>

      <Card className="p-6 mt-4">
        <div className="flex items-center gap-2 mb-4">
          <Phone className="h-5 w-5 text-[#0a2350]" />
          <h2 className="text-lg font-extrabold text-[#0a2350]">Kontak</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Telepon / WhatsApp *</span>
            <input value={form.phone} onChange={set("phone")} className={inputClass} placeholder="+62 812 3456 7890" data-testid="profile-phone" />
          </label>
          <label className="block">
            <span className={`${labelClass} mb-1 block`}>Nama Kontak (Attention)</span>
            <input value={form.attention} onChange={set("attention")} className={inputClass} placeholder={form.name || "Contact person"} data-testid="profile-attention" />
          </label>
        </div>
      </Card>

      {!isComplete && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 flex items-center gap-3" data-testid="profile-incomplete">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span>
            Profil Anda belum lengkap. Domain yang didaftarkan akan menggunakan akun Intercloud. Lengkapi semua field bertanda * agar domain terdaftar atas nama Anda sendiri.
          </span>
        </div>
      )}

      <div className="mt-6 flex items-center gap-3">
        <button className={btnPrimary} onClick={save} disabled={busy} data-testid="profile-save">
          {busy ? "Menyimpan..." : "Simpan Profil"}
        </button>
        <Link to="/portal/client/settings/password" className="text-sm font-semibold text-[#0a2350] hover:text-[#f5b120] transition-colors">
          Ubah Password
        </Link>
      </div>
    </div>
  );
};
export default ClientProfile;