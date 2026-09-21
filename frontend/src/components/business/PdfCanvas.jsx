import React, { useEffect, useRef, useState } from "react";

/* PDF rendered via pdf.js into <canvas> — avoids iframe/CSP blocking and
   works with an authenticated blob (no public URL exposure). */
const PdfCanvas = ({ blob }) => {
  const containerRef = useRef(null);
  const [err, setErr] = useState("");
  const [pages, setPages] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let pdfDoc = null;
    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist/build/pdf.mjs");
        // webpack 5 resolves this as an asset module and returns a real URL.
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url
        ).toString();
        const buf = await blob.arrayBuffer();
        if (cancelled) return;
        pdfDoc = await pdfjs.getDocument({ data: buf }).promise;
        if (cancelled) return;
        setPages(pdfDoc.numPages);
        const container = containerRef.current;
        if (!container) return;
        container.innerHTML = "";
        const maxPages = Math.min(pdfDoc.numPages, 30);
        for (let n = 1; n <= maxPages; n++) {
          const page = await pdfDoc.getPage(n);
          if (cancelled) return;
          const targetWidth = container.clientWidth || 800;
          const unscaled = page.getViewport({ scale: 1 });
          const scale = Math.min(2, targetWidth / unscaled.width);
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.className = "w-full mb-3 rounded-lg border border-slate-200 shadow-sm";
          const ctx = canvas.getContext("2d");
          container.appendChild(canvas);
          await page.render({ canvasContext: ctx, viewport }).promise;
        }
      } catch (e) {
        if (!cancelled) setErr("Gagal menampilkan PDF: " + (e?.message || e));
      }
    })();
    return () => { cancelled = true; if (pdfDoc) pdfDoc.destroy(); };
  }, [blob]);

  if (err) return <div className="text-sm text-red-600 py-6">{err}</div>;
  return (
    <div className="overflow-auto max-h-[70vh]" data-testid="doc-pdf-canvas">
      <div ref={containerRef} />
      {pages > 30 && (
        <div className="text-xs text-slate-400 text-center py-2">
          Menampilkan 30 dari {pages} halaman. Gunakan Download untuk file lengkap.
        </div>
      )}
    </div>
  );
};

export default PdfCanvas;
