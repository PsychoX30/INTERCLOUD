"""Reporting exports for graph monitoring data (PDF only)."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from html import escape

from fastapi.responses import StreamingResponse


# ---------------------------------------------------------------------------
# Adaptive unit formatting
# ---------------------------------------------------------------------------
# Mirrors the frontend ``fmtBps`` / ``fmtValue`` helpers in AdminMonitoring.jsx
# so a PDF export reads the same as the on-screen chart instead of dumping raw
# bits-per-second integers such as "328092637.0000".
_BPS_UNITS = ("bps", "kbps", "Mbps", "Gbps", "Tbps")

# Graph types whose samples are a bits-per-second rate even when the graph
# document carries no explicit unit.
_BPS_GRAPH_TYPES = {"snmp_traffic_in", "snmp_traffic_out", "snmp_traffic"}


def format_bps(value) -> str:
    """Auto-scale a bits-per-second value to bps/kbps/Mbps/Gbps/Tbps.

    Uses 1000-based prefixes, matching MRTG/Cacti/LibreNMS convention for
    network throughput (not 1024-based, which applies to storage).
    """
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    if num != num:  # NaN
        return "-"
    sign = "-" if num < 0 else ""
    abs_val = abs(num)
    idx = 0
    while abs_val >= 1000 and idx < len(_BPS_UNITS) - 1:
        abs_val /= 1000.0
        idx += 1
    # Sub-bps values keep no decimals; scaled units keep two.
    decimals = 2 if idx > 0 else 0
    return f"{sign}{abs_val:.{decimals}f} {_BPS_UNITS[idx]}"


def format_sample_value(value, unit: str = "", graph_type: str = "") -> str:
    """Format one sample for the PDF table according to its unit.

    Traffic graphs are rendered as auto-scaled bit rates; percentages, latency,
    and byte counters use their own conventions. Unknown units fall back to a
    two-decimal number with the unit appended.
    """
    if value is None:
        return "-"
    normalized = (unit or "").strip().lower()
    if normalized in {"bps", "bits/s", "bit/s"} or (
        not normalized and graph_type in _BPS_GRAPH_TYPES
    ):
        return format_bps(value)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return escape(str(value))
    if num != num:
        return "-"
    if normalized == "%":
        return f"{num:.1f}%"
    if normalized == "ms":
        return f"{num:.2f} ms"
    if normalized in {"kb", "mb", "gb", "tb"}:
        return f"{num:.2f} {normalized.upper()}"
    if normalized == "seconds":
        return f"{num:.0f} s"
    if normalized == "bytes":
        # Preserve the existing UI convention for historical graph documents.
        return format_bps(num)
    if normalized:
        return f"{num:.2f} {escape(unit.strip())}"
    return f"{num:.2f}"


# ---------------------------------------------------------------------------
# PDF export (HTML -> WeasyPrint)
# ---------------------------------------------------------------------------
def _graph_export_pdf_bytes(graph: dict, rows: list[dict]) -> bytes:
    """Build a PDF report for a graph's time series. Returns bytes."""
    from weasyprint import HTML

    name = escape(graph.get("name") or "")
    target = escape(graph.get("target") or "")
    raw_type = graph.get("type") or ""
    raw_unit = graph.get("unit") or ""
    gtype = escape(raw_type)
    # Traffic graphs may carry an empty unit; label the column so the reader
    # knows the values are auto-scaled bit rates.
    effective_unit = raw_unit or ("bps" if raw_type in _BPS_GRAPH_TYPES else "")
    unit = escape(effective_unit or "-")
    exported = escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    body_rows = []
    for row in rows:
        at = row.get("at")
        at_str = at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else escape(str(at))
        val_str = format_sample_value(row.get("value"), raw_unit, raw_type)
        mn_str = format_sample_value(row.get("min"), raw_unit, raw_type)
        mx_str = format_sample_value(row.get("max"), raw_unit, raw_type)
        body_rows.append(
            f"<tr><td>{escape(at_str)}</td><td>{escape(val_str)}</td>"
            f"<td>{escape(mn_str)}</td><td>{escape(mx_str)}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; color: #0a2350; margin: 32px; }}
  h1 {{ font-size: 20px; color: #0a2350; margin-bottom: 4px; }}
  .meta {{ color: #64748b; font-size: 12px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
  th {{ background: #0a2350; color: #fff; padding: 8px; text-align: left; font-size: 12px; }}
  td {{ border: 1px solid #d8dee9; padding: 6px 8px; font-size: 12px; }}
  tr:nth-child(even) td {{ background: #f8fafc; }}
  .footer {{ margin-top: 24px; font-size: 10px; color: #94a3b8; }}
</style></head>
<body>
  <h1>{name}</h1>
  <div class="meta">
    Target: {target} &nbsp;•&nbsp; Type: {gtype} &nbsp;•&nbsp; Unit: {unit}<br>
    Exported: {exported}
  </div>
  <table>
    <thead><tr><th>Timestamp</th><th>Value</th><th>Min</th><th>Max</th></tr></thead>
    <tbody>{''.join(body_rows) if body_rows else '<tr><td colspan="4">No data in range.</td></tr>'}</tbody>
  </table>
  <div class="footer">Generated by INTERCLOUD Monitoring</div>
</body></html>"""

    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Public helpers for routes
# ---------------------------------------------------------------------------
def graph_export_response(graph: dict, rows: list[dict], fmt: str):
    """Return a StreamingResponse for the given graph data as PDF."""
    if fmt != "pdf":
        raise ValueError("Only PDF export is supported for monitoring graphs")
    data = _graph_export_pdf_bytes(graph, rows)
    safe_name = "".join(c for c in (graph.get("name") or "graph") if c.isalnum() or c in "-_ ").strip().replace(" ", "-")
    filename = f"{safe_name or 'graph'}.pdf"

    return StreamingResponse(
        BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )