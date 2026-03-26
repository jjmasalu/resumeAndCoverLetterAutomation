"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/components/AppContext";
import { apiJson, apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import { MODE_COPY, getModeCopy } from "@/lib/conversation-modes";

type ModeFilter = "all" | "job_to_resume" | "find_jobs";
type StatusFilter = "all" | "active" | "completed";

export default function HistoryPage() {
  const { conversations, loading, refreshConversations } = useApp();
  const [modeFilter, setModeFilter] = useState<ModeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    loading: boolean;
  }>({ open: false, title: "", message: "", onConfirm: () => {}, loading: false });
  const router = useRouter();

  const filtered = conversations.filter((c) => {
    const matchesMode = modeFilter === "all" || c.mode === modeFilter;
    const matchesStatus = statusFilter === "all" || c.status === statusFilter;
    return matchesMode && matchesStatus;
  });

  const handleNew = async () => {
    const conv = await apiJson<{ id: string }>("/conversations", {
      method: "POST",
      body: JSON.stringify({ mode: "job_to_resume" }),
    });
    await refreshConversations();
    router.push(`/chat/${conv.id}`);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    const allIds = filtered.map((c) => c.id);
    const allSelected = allIds.every((id) => selected.has(id));
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allIds));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelected(new Set());
  };

  const handleBulkDelete = () => {
    const count = selected.size;
    setConfirmState({
      open: true,
      title: "Delete conversations",
      message: `Are you sure you want to delete ${count} conversation${count === 1 ? "" : "s"}? This cannot be undone.`,
      loading: false,
      onConfirm: async () => {
        setConfirmState((prev) => ({ ...prev, loading: true }));
        try {
          await apiJson("/conversations/bulk-delete", {
            method: "POST",
            body: JSON.stringify({ conversation_ids: [...selected] }),
          });
          await refreshConversations();
          exitSelectMode();
          setConfirmState((prev) => ({ ...prev, open: false }));
        } catch {
          setConfirmState((prev) => ({ ...prev, loading: false }));
        }
      },
    });
  };

  const handleDeleteSingle = (id: string, title: string) => {
    setConfirmState({
      open: true,
      title: "Delete conversation",
      message: `Are you sure you want to delete "${title}"? This cannot be undone.`,
      loading: false,
      onConfirm: async () => {
        setConfirmState((prev) => ({ ...prev, loading: true }));
        try {
          await apiFetch(`/conversations/${id}`, { method: "DELETE" });
          await refreshConversations();
          setConfirmState((prev) => ({ ...prev, open: false }));
        } catch {
          setConfirmState((prev) => ({ ...prev, loading: false }));
        }
      },
    });
  };

  const allFilteredSelected =
    filtered.length > 0 && filtered.every((c) => selected.has(c.id));

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-3xl mx-auto">
        {/* Filters + Select button */}
        <div className="flex gap-1.5 mb-6 flex-wrap items-center">
          {(["all", "job_to_resume", "find_jobs"] as ModeFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setModeFilter(f)}
              className={`px-3 py-1 rounded-full text-xs transition ${
                modeFilter === f
                  ? "bg-accent-muted text-accent border border-accent/20"
                  : "bg-bg-secondary text-text-secondary border border-border hover:text-text-primary"
              }`}
            >
              {f === "all" ? "All modes" : MODE_COPY[f].label}
            </button>
          ))}
          <div className="w-px h-5 bg-border self-center mx-1" />
          {(["all", "active", "completed"] as StatusFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setStatusFilter(f)}
              className={`px-3 py-1 rounded-full text-xs transition ${
                statusFilter === f
                  ? "bg-accent-muted text-accent border border-accent/20"
                  : "bg-bg-secondary text-text-secondary border border-border hover:text-text-primary"
              }`}
            >
              {f === "all" ? "All status" : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          {!loading && filtered.length > 0 && !selectMode && (
            <>
              <div className="flex-1" />
              <button
                onClick={() => setSelectMode(true)}
                className="px-3 py-1 rounded-lg text-xs bg-bg-secondary border border-border text-text-secondary hover:text-text-primary transition"
              >
                Select
              </button>
            </>
          )}
        </div>

        {/* Selection action bar */}
        {selectMode && (
          <div className="bg-accent-muted border border-accent/20 rounded-lg px-4 py-2 mb-4 flex items-center gap-3">
            <input
              type="checkbox"
              checked={allFilteredSelected}
              onChange={toggleSelectAll}
              className="accent-accent w-4 h-4 cursor-pointer"
            />
            <span className="text-xs text-text-secondary flex-1">
              {selected.size} selected
            </span>
            <button
              onClick={handleBulkDelete}
              disabled={selected.size === 0}
              className={`px-3 py-1 rounded-lg text-xs border border-danger text-danger transition ${
                selected.size === 0
                  ? "opacity-40 cursor-not-allowed"
                  : "hover:bg-danger/10"
              }`}
            >
              Delete Selected
            </button>
            <button
              onClick={exitSelectMode}
              className="px-3 py-1 rounded-lg text-xs bg-bg-secondary border border-border text-text-secondary hover:text-text-primary transition"
            >
              Cancel
            </button>
          </div>
        )}

        {/* List */}
        {loading && (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-lg bg-bg-secondary animate-pulse" />
            ))}
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h3 className="text-sm font-medium text-text-primary mb-1">No conversations yet</h3>
            <p className="text-xs text-text-tertiary mb-4">Start a new chat to generate your first tailored resume.</p>
            <button
              onClick={handleNew}
              className="px-4 py-1.5 text-xs font-medium bg-accent text-white rounded-md hover:bg-accent-hover transition"
            >
              New Chat
            </button>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-1">
            {filtered.map((c) => (
              <div
                key={c.id}
                className="w-full text-left px-4 py-3 bg-bg-secondary border border-border rounded-lg hover:border-accent/30 transition flex items-center gap-3 group"
              >
                {/* Checkbox in select mode */}
                {selectMode && (
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={() => toggleSelect(c.id)}
                    onClick={(e) => e.stopPropagation()}
                    className="accent-accent w-4 h-4 flex-shrink-0 cursor-pointer"
                  />
                )}

                {/* Main content area — navigates when not in select mode */}
                <div
                  className="flex-1 min-w-0 flex items-center justify-between cursor-pointer"
                  onClick={() => {
                    if (selectMode) {
                      toggleSelect(c.id);
                    } else {
                      router.push(`/chat/${c.id}`);
                    }
                  }}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-text-primary truncate group-hover:text-accent transition">
                      {c.title}
                    </p>
                    <p className="text-[11px] text-text-tertiary mt-0.5">
                      {getModeCopy(c.mode).label} ·{" "}
                      {new Date(c.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full flex-shrink-0 ml-3 ${
                      c.status === "active"
                        ? "bg-accent-muted text-accent"
                        : "bg-bg-tertiary text-text-secondary"
                    }`}
                  >
                    {c.status === "active" ? "Active" : "Completed"}
                  </span>
                </div>

                {/* Trash icon — only visible on hover when NOT in select mode */}
                {!selectMode && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSingle(c.id, c.title);
                    }}
                    className="flex-shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-danger hover:bg-danger/10 transition"
                    aria-label="Delete conversation"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      <path d="M10 11v6" />
                      <path d="M14 11v6" />
                      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        loading={confirmState.loading}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((prev) => ({ ...prev, open: false }))}
      />
    </div>
  );
}
