import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import axios from "axios";
import { Loader2, Video, AlertTriangle, Clock } from "lucide-react";

// axios LANGSUNG, bukan `api.js`: interceptor 401 di sana melempar pengunjung
// publik ke /portal/login. Halaman ini tidak punya sesi portal.
const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
    <div className="w-full max-w-lg bg-white rounded-3xl shadow-xl border border-slate-200 p-8 md:p-10 text-center">
      {children}
    </div>
  </div>
);

export default function MeetJoin() {
  const { slug } = useParams();
  const [params] = useSearchParams();
  const key = params.get("k") || "";
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!key) {
      setErr("Tautan ini tidak memuat kunci undangan.");
      return;
    }
    let alive = true;
    setBusy(true);
    axios
      .get(`${API}/jitsi/join`, { params: { k: key, name: "" } })
      .then((r) => {
        if (!alive) return;
        // replace(), bukan push(): tombol back tidak boleh mendarat kembali di
        // halaman ini lalu me-remint token dan melempar pengguna maju lagi.
        window.location.replace(r.data.url);
      })
      .catch((e) => {
        if (!alive) return;
        setBusy(false);
        setErr(e?.response?.data?.detail || "Undangan tidak dapat dipakai.");
      });
    return () => {
      alive = false;
    };
  }, [key]);

  if (err) {
    const expired = /expired|berakhir/i.test(err);
    return (
      <Shell>
        <div data-testid="meet-join-error">
          {expired ? (
            <Clock className="h-14 w-14 text-amber-500 mx-auto" />
          ) : (
            <AlertTriangle className="h-14 w-14 text-red-500 mx-auto" />
          )}
          <h1 className="mt-4 text-2xl font-extrabold text-[#0a2350]">
            Undangan tidak dapat dipakai
          </h1>
          <p className="mt-2 text-slate-500 text-sm">{err}</p>
          <p className="mt-6 text-xs text-slate-400">
            Minta tautan baru ke penyelenggara rapat.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div data-testid="meet-join-loading">
        <Video className="h-14 w-14 text-[#f5b120] mx-auto" />
        <h1 className="mt-4 text-2xl font-extrabold text-[#0a2350]">
          Menyiapkan rapat…
        </h1>
        <p className="mt-2 text-slate-500 text-sm break-all">
          {slug ? `Rapat: ${slug}` : "Memeriksa undangan"}
        </p>
        {busy && (
          <Loader2 className="mt-6 h-6 w-6 animate-spin mx-auto text-[#0a2350]" />
        )}
      </div>
    </Shell>
  );
}
