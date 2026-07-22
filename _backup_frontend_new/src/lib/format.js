// Indonesian currency + date formatting
export function formatIDR(value, opts = {}) {
  const n = Number(value || 0);
  const { withSymbol = true, decimals = 0 } = opts;
  const s = n.toLocaleString("id-ID", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return withSymbol ? `Rp ${s}` : s;
}

export function formatNumber(value, decimals = 0) {
  return Number(value || 0).toLocaleString("id-ID", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatDate(value, locale = "id-ID") {
  if (!value) return "-";
  const d = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function todayISO() {
  return new Date().toISOString().slice(0, 10);
}
