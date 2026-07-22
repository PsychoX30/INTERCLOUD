import { Link } from "react-router-dom";

/** Split-screen auth shell used by login/register/forgot pages. */
export default function AuthShell({ title, subtitle, children, footer }) {
  return (
    <div className="grid min-h-screen grid-cols-1 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      {/* Left: content */}
      <div className="flex flex-col justify-between bg-white px-6 py-10 sm:px-12 lg:px-16">
        <Link to="/login" className="flex items-center gap-2">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-[#0F172A] text-white">
            <span className="font-display text-sm font-bold tracking-tight">iC</span>
          </div>
          <div className="leading-tight">
            <div className="font-display text-[15px] font-bold tracking-tight text-slate-900">
              Intercloud
            </div>
            <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-slate-500">
              Portal
            </div>
          </div>
        </Link>

        <div className="mx-auto w-full max-w-md py-10">
          <div className="mb-8">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">
              {subtitle}
            </div>
            <h1 className="font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
              {title}
            </h1>
          </div>
          {children}
        </div>

        <div className="text-xs text-slate-500">{footer}</div>
      </div>

      {/* Right: image + captions */}
      <div className="relative hidden overflow-hidden bg-[#0F172A] lg:block">
        <img
          alt=""
          src="https://images.pexels.com/photos/2747599/pexels-photo-2747599.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=900&w=1200"
          className="absolute inset-0 h-full w-full object-cover opacity-80"
        />
        <div className="absolute inset-0 bg-gradient-to-br from-[#0F172A]/70 via-[#0F172A]/40 to-transparent" />
        <div className="grain" />
        <div className="relative z-10 flex h-full flex-col justify-between p-12 text-white">
          <div className="text-[11px] font-semibold uppercase tracking-[0.3em] text-white/70">
            Metode Garis Lurus
          </div>
          <div>
            <div className="max-w-md font-display text-3xl font-semibold leading-tight tracking-tight">
              Kelola aset & penyusutan dengan formula presisi.
            </div>
            <div className="mt-3 max-w-md text-sm text-white/70">
              (Harga Perolehan − Nilai Sisa) ÷ Umur Ekonomis. Setiap angka
              terhitung akurat, setiap laporan siap dipertanggungjawabkan.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
