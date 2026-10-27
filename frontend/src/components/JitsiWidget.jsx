import React, { useState } from "react";
import { Video, X } from "lucide-react";
import { useJitsiConfig } from "../hooks/useJitsiConfig";
import { v4 as uuidv4 } from "uuid";

/**
 * Tombol rapat Jitsi. Digate ke admin oleh PortalLayout (`{isAdmin && ...}`)
 * karena room dibuka tanpa JWT — jadi tidak boleh muncul di portal klien.
 */
export default function JitsiWidget() {
  const { enabled, domain, default_room_prefix, loading } = useJitsiConfig();
  const [open, setOpen] = useState(false);
  const [iframeSrc, setIframeSrc] = useState("");

  if (loading || !enabled) return null;

  const startMeeting = () => {
    const prefix = default_room_prefix || "ic";
    const room = `${prefix}-${uuidv4()}`;
    setIframeSrc(`https://${domain}/${room}`);
    setOpen(true);
  };

  const closeMeeting = () => {
    setIframeSrc("");
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        onClick={startMeeting}
        className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg bg-[#f5b120] text-[#0a2350] font-semibold shadow-lg hover:bg-[#e0a010] flex items-center gap-2"
        data-testid="jitsi-start-btn"
      >
        <Video className="h-5 w-5" />
        Start meeting
      </button>

      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center"
          onClick={closeMeeting}
          data-testid="jitsi-overlay"
        >
          <div
            className="relative w-full h-full max-w-6xl max-h-[90vh]"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={closeMeeting}
              className="absolute top-2 right-2 z-10 p-1 rounded-full bg-white/10 text-white hover:bg-white/20"
              aria-label="Close meeting"
            >
              <X className="h-5 w-5" />
            </button>
            <iframe
              src={iframeSrc}
              title="Jitsi meeting"
              allow="camera; microphone; fullscreen; display-capture"
              allowFullScreen
              referrerPolicy="no-referrer"
              style={{ width: "100%", height: "100%", border: "none", borderRadius: "8px" }}
            />
          </div>
        </div>
      )}
    </>
  );
}