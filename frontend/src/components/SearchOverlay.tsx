"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useApp, type Conversation } from "./AppContext";
import { MODE_COPY, getModeCopy } from "@/lib/conversation-modes";

interface SearchOverlayProps {
  open: boolean;
  onClose: () => void;
}

type ModeFilter = "all" | "job_to_resume" | "find_jobs";

export default function SearchOverlay({ open, onClose }: SearchOverlayProps) {
  if (!open) return null;
  return <SearchOverlayInner onClose={onClose} />;
}

function SearchOverlayInner({ onClose }: { onClose: () => void }) {
  const { conversations, loading } = useApp();
  const [query, setQuery] = useState("");
  const [modeFilter, setModeFilter] = useState<ModeFilter>("all");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const filtered = conversations.filter((c) => {
    const matchesQuery = !query || c.title.toLowerCase().includes(query.toLowerCase());
    const matchesMode = modeFilter === "all" || c.mode === modeFilter;
    return matchesQuery && matchesMode;
  });

  // Focus input on mount
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  const handleQueryChange = (value: string) => {
    setQuery(value);
    setSelectedIndex(0);
  };

  const handleModeFilterChange = (value: ModeFilter) => {
    setModeFilter(value);
    setSelectedIndex(0);
  };

  const handleSelect = useCallback(
    (conv: Conversation) => {
      onClose();
      router.push(`/chat/${conv.id}`);
    },
    [onClose, router]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && filtered[selectedIndex]) {
      e.preventDefault();
      handleSelect(filtered[selectedIndex]);
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60" />
      <div
        className="relative w-full max-w-lg bg-bg-secondary border border-border rounded-xl overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-tertiary flex-shrink-0">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Search conversations..."
            className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none"
          />
          <kbd className="text-[10px] bg-bg-tertiary px-1.5 py-0.5 rounded text-text-tertiary">ESC</kbd>
        </div>

        {/* Filter pills */}
        <div className="flex gap-1.5 px-4 py-2 border-b border-border">
          {(["all", "job_to_resume", "find_jobs"] as ModeFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => handleModeFilterChange(f)}
              className={`px-2.5 py-0.5 rounded-full text-[11px] transition ${
                modeFilter === f
                  ? "bg-accent-muted text-accent border border-accent/20"
                  : "bg-bg-tertiary text-text-secondary hover:text-text-primary"
              }`}
            >
              {f === "all" ? "All" : MODE_COPY[f].label}
            </button>
          ))}
        </div>

        {/* Results */}
        <div className="max-h-64 overflow-y-auto p-1">
          {loading && (
            <div className="py-8 text-center text-sm text-text-tertiary">Loading...</div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="py-8 text-center text-sm text-text-tertiary">No results found</div>
          )}
          {!loading &&
            filtered.map((c, i) => (
              <button
                key={c.id}
                onClick={() => handleSelect(c)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition ${
                  i === selectedIndex ? "bg-bg-tertiary" : "hover:bg-bg-tertiary"
                }`}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={i === selectedIndex ? "text-accent" : "text-text-tertiary"}>
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text-primary truncate">{c.title}</div>
                  <div className="text-[11px] text-text-tertiary">
                    {getModeCopy(c.mode).label} ·{" "}
                    {new Date(c.created_at).toLocaleDateString()}
                  </div>
                </div>
                {i === selectedIndex && (
                  <span className="text-[10px] text-text-tertiary">↵</span>
                )}
              </button>
            ))}
        </div>

        {/* Footer */}
        <div className="flex gap-4 px-4 py-2 border-t border-border text-[10px] text-text-tertiary">
          <span>↑↓ Navigate</span>
          <span>↵ Open</span>
          <span>ESC Close</span>
        </div>
      </div>
    </div>
  );
}
