import React from "react";
import { FolderOpen, Folder, ChevronRight, Plus, X } from "lucide-react";

const FolderTree = ({
  folders,
  expanded,
  folderId,
  setFolderId,
  toggleExpand,
  createFolder,
  renameFolderCall,
  deleteFolder,
  setNewFolderParent,
  setFolderMenu,
  user,
}) => {
  const renderFolderNode = (f, depth = 0) => {
    const isOpen = expanded.has(f.id);
    const hasChildren = (f.children || []).length > 0;
    const isActive = folderId === f.id;
    const pad = depth * 14;
    return (
      <div key={f.id}>
        <div
          className={`group flex items-center gap-1 pr-2 py-1.5 rounded cursor-pointer text-sm ${isActive ? "bg-[#0a2350]/10 text-[#0a2350] font-bold" : "text-slate-700 hover:bg-slate-100"}`}
          style={{ paddingLeft: `${pad + 8}px` }}
          onClick={() => setFolderId(f.id)}
          onContextMenu={(e) => {
            e.preventDefault();
            if (setFolderMenu) setFolderMenu({ x: e.clientX, y: e.clientY, folder: f });
          }}
        >
          {hasChildren ? (
            <button
              className="p-0.5 rounded hover:bg-slate-200"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand(f.id);
              }}
            >
              <ChevronRight className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-90" : ""}`} />
            </button>
          ) : <span className="w-5" />}
          {isActive ? <FolderOpen className="h-4 w-4 text-[#f5b120]" /> : <Folder className="h-4 w-4 text-slate-400" />}
          <span className="truncate flex-1" title={f.path}>{f.name}</span>
          {user?.role === "admin" && (
            <button
              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-slate-200 rounded"
              onClick={(e) => {
                e.stopPropagation();
                setNewFolderParent(f.id);
              }}
              title="New subfolder"
            >
              <Plus className="h-3 w-3" />
            </button>
          )}
        </div>
        {isOpen && (f.children || []).map((c) => renderFolderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <aside className="w-64 shrink-0 bg-white rounded-2xl border border-slate-200 p-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500">Folders</h4>
        {user?.role === "admin" && (
          <button className="text-[#0a2350] hover:text-[#f5b120] p-1" onClick={() => setNewFolderParent("root")} title="New top folder">
            <Plus className="h-4 w-4" />
          </button>
        )}
      </div>
      <div
        className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm ${folderId === "root" ? "bg-[#0a2350]/10 text-[#0a2350] font-bold" : "text-slate-700 hover:bg-slate-100"}`}
        onClick={() => setFolderId("root")}
      >
        <FolderOpen className="h-4 w-4 text-[#f5b120]" /> <span>All documents</span>
      </div>
      <div
        className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm ${folderId === "" ? "bg-[#0a2350]/10 text-[#0a2350] font-bold" : "text-slate-700 hover:bg-slate-100"}`}
        onClick={() => setFolderId("")}
      >
        <Folder className="h-4 w-4 text-slate-400" /> <span>Unfiled</span>
      </div>
      <div className="mt-1">{folders.map((f) => renderFolderNode(f))}</div>
    </aside>
  );
};

export default FolderTree;