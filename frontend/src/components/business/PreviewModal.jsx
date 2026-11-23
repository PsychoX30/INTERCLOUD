import React, { useEffect, useState } from "react";
import { api, getToken } from "../../portal/api";
import { btnSecondary, Loading } from "../../pages/portal/ui";
import { Download, X, FileText } from "lucide-react";
import PdfCanvas from "./PdfCanvas";

const PreviewModal = ({ doc, onClose }) => {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [blobUrl, setBlobUrl] = useState(null);
  const [pdfBlob, setPdfBlob] = useState(null);
  const [streamUrl, setStreamUrl] = useState(null);

  // Media (video/audio) must be streamed by the browser so HTTP Range works:
  // a 300 MB MP4 cannot be buffered into a Blob, and Chrome needs 206 replies
  // to seek. The token rides along as a query param (auth.py supports it).
  const withToken = (path) => {
    const t = getToken();
    if (!t) return path;
    return `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}`;
  };

  // Fetch preview metadata and any binary blob through the authenticated
  // Axios instance so the portal Bearer token is attached. Plain <img src>
  // or <iframe src> cannot send our Authorization header.
  useEffect(() => {
    let cancelled = false;
    let objUrl = null;
    setBlobUrl(null); setPdfBlob(null); setStreamUrl(null); setErr(""); setData(null);
    api.get(`/admin/documents/${doc.id}/preview`)
      .then(async (r) => {
        if (cancelled) return;
        const info = r.data;
        setData(info);
        const blobKinds = ["image", "pdf"];
        if (info.preview_pdf_url && info.render_mode === "libreoffice") {
          // LibreOffice-rendered Office/ODF → fetch the converted PDF blob.
          const path = info.preview_pdf_url.replace(/^\/api\/portal/, "");
          const br = await api.get(path, { responseType: "blob" });
          if (cancelled) return;
          setPdfBlob(new Blob([br.data], { type: "application/pdf" }));
        } else if (info.kind === "audio" || info.kind === "video") {
          // Streamed with Range support - never buffered through axios.
          if (info.file_url) setStreamUrl(withToken(info.file_url));
        } else if (info.file_url && blobKinds.includes(info.kind)) {
          const path = info.file_url.replace(/^\/api\/portal/, "");
          const br = await api.get(path, { responseType: "blob" });
          if (cancelled) return;
          objUrl = URL.createObjectURL(new Blob([br.data], { type: info.content_type || "application/octet-stream" }));
          setBlobUrl(objUrl);
          if (info.kind === "pdf") {
            setPdfBlob(new Blob([br.data], { type: info.content_type || "application/pdf" }));
          }
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(e?.response?.data?.detail || "Gagal memuat preview");
      });
    return () => {
      cancelled = true;
      if (objUrl) URL.revokeObjectURL(objUrl);
    };
  }, [doc.id]);

  const download = async () => {
    try {
      const r = await api.get(`/admin/documents/${doc.id}/download`, { responseType: "blob" });
      const objUrl = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = data?.filename || doc.filename || "dokumen";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objUrl), 60000);
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal mengunduh dokumen");
    }
  };

  const kind = data?.kind || "none";
  const htmlKinds = ["docx", "xlsx", "pptx", "odt", "ods", "odp", "text"];
  // If LibreOffice converted the Office file to a preview PDF, render it
  // just like a normal PDF — this gives Google Drive/Nextcloud-level fidelity.
  const renderPdf = data?.preview_pdf_url && data?.render_mode === "libreoffice";

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="w-full max-w-5xl bg-white rounded-3xl p-6 max-h-[92vh] flex flex-col"
           data-testid="doc-preview-modal">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="min-w-0">
            <h3 className="text-xl font-extrabold text-[#0a2350] truncate">{data?.title || doc.title}</h3>
            <div className="text-xs text-slate-500 truncate">
              {data?.filename || doc.filename}
              {data?.folder_path ? ` · ${data.folder_path}` : ""}
              {data?.owner_name ? ` · Owner: ${data.owner_name}` : ""}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button className={btnSecondary} onClick={download} data-testid="doc-download">
              <Download className="h-4 w-4 mr-1" /> Download
            </button>
            <button className="p-2 rounded-full hover:bg-slate-100 text-slate-500" onClick={onClose} aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
        {err && <div className="text-sm text-red-600" data-testid="doc-preview-error">{err}</div>}
        {!data && !err && <Loading />}
        {data && kind === "image" && blobUrl && (
          <img src={blobUrl} alt={data.title} className="max-h-[70vh] w-full object-contain bg-slate-50 rounded-xl" />
        )}
        {data && kind === "audio" && streamUrl && (
          <audio controls preload="metadata" src={streamUrl} className="w-full mt-4" data-testid="doc-preview-audio" />
        )}
        {data && kind === "video" && streamUrl && (
          <video controls preload="metadata" playsInline src={streamUrl}
                 className="max-h-[70vh] w-full bg-black rounded-xl" data-testid="doc-preview-video" />
        )}
        {data && (kind === "pdf" || renderPdf) && pdfBlob && <PdfCanvas blob={pdfBlob} />}
        {data && (kind === "pdf" || renderPdf) && !pdfBlob && (
          <div className="py-12 text-center text-slate-400 text-sm">Memuat berkas…</div>
        )}
        {data && kind === "image" && !blobUrl && (
          <div className="py-12 text-center text-slate-400 text-sm">Memuat berkas…</div>
        )}
        {data && htmlKinds.includes(kind) && !renderPdf && (
          <div className="overflow-auto max-h-[70vh] border border-slate-200 rounded-xl p-4 doc-preview-html"
               data-testid="doc-preview-html"
               dangerouslySetInnerHTML={{ __html: data.html || "<p><i>Preview kosong</i></p>" }} />
        )}
        {data && kind === "none" && (
          <div className="py-16 text-center text-slate-500">
            <FileText className="h-10 w-10 mx-auto mb-2 text-slate-300" />
            <div className="text-sm">Preview tidak tersedia untuk tipe file ini.</div>
            <button className={btnSecondary + " mt-4"} onClick={download}>
              <Download className="h-4 w-4 mr-1" /> Download file
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default PreviewModal;
