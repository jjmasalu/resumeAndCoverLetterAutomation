"use client";

import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useApp } from "./AppContext";
import { apiJson } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

const BRAND_NAME = "Resume AI";
const MAX_RECENT = 8;

export default function Sidebar({ onOpenSearch }: { onOpenSearch?: () => void }) {
  const { conversations, loading, error, refreshConversations } = useApp();
  const [mode, setMode] = useState<"job_to_resume" | "find_jobs">("job_to_resume");
  const [userEmail, setUserEmail] = useState<string>("");
  const [menuOpen, setMenuOpen] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  // Fetch authenticated user
  useEffect(() => {
    createClient().auth.getUser().then(({ data }) => {
      if (data.user?.email) setUserEmail(data.user.email);
    });
  }, []);

  const recent = conversations.slice(0, MAX_RECENT);
  const hasMore = conversations.length > MAX_RECENT;

  const handleNew = async () => {
    const conv = await apiJson<{ id: string }>("/conversations", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    await refreshConversations();
    router.push(`/chat/${conv.id}`);
  };

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  };

  return (
    <aside className="w-60 bg-bg-secondary border-r border-border flex flex-col h-screen flex-shrink-0">
      {/* Header */}
      <div className="px-4 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 bg-accent rounded-md flex items-center justify-center text-[11px] font-bold text-white">
            R
          </div>
          <span className="font-semibold text-sm text-text-primary">{BRAND_NAME}</span>
        </div>
        <button
          onClick={handleNew}
          className="w-7 h-7 rounded-md bg-bg-tertiary flex items-center justify-center hover:bg-border transition"
          aria-label="New chat"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-secondary">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>

      {/* Mode selector */}
      <div className="px-3 pb-3 flex gap-1">
        <button
          onClick={() => setMode("job_to_resume")}
          className={`flex-1 py-1.5 text-[11px] font-medium rounded-md transition ${
            mode === "job_to_resume"
              ? "bg-accent text-white"
              : "bg-bg-tertiary text-text-secondary hover:text-text-primary"
          }`}
        >
          Job → Resume
        </button>
        <button
          onClick={() => setMode("find_jobs")}
          className={`flex-1 py-1.5 text-[11px] font-medium rounded-md transition ${
            mode === "find_jobs"
              ? "bg-accent text-white"
              : "bg-bg-tertiary text-text-secondary hover:text-text-primary"
          }`}
        >
          Find Jobs
        </button>
      </div>

      {/* Recent conversations */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        <div className="text-[10px] uppercase tracking-wider text-text-tertiary font-medium px-2 py-2">
          Recent
        </div>
        {loading && (
          <>
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-8 mx-2 mb-1 rounded-md bg-bg-tertiary animate-pulse" />
            ))}
          </>
        )}
        {error && (
          <div className="px-2 text-xs text-text-tertiary">
            {error}.{" "}
            <button onClick={refreshConversations} className="text-accent hover:underline">
              Retry
            </button>
          </div>
        )}
        {!loading &&
          !error &&
          recent.map((c) => (
            <button
              key={c.id}
              onClick={() => router.push(`/chat/${c.id}`)}
              className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs truncate transition ${
                pathname === `/chat/${c.id}`
                  ? "bg-bg-tertiary text-text-primary"
                  : "text-text-secondary hover:bg-bg-tertiary hover:text-text-primary"
              }`}
            >
              {c.title}
            </button>
          ))}
        <button
          onClick={() => router.push("/history")}
          className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs transition ${
            pathname === "/history"
              ? "bg-bg-tertiary text-text-primary"
              : "text-text-tertiary hover:bg-bg-tertiary hover:text-text-primary"
          }`}
        >
          {hasMore ? "View all →" : "History"}
        </button>
      </div>

      {/* Search trigger + User */}
      <div className="px-3 py-2 border-t border-border space-y-2">
        <button
          onClick={onOpenSearch}
          className="w-full px-2.5 py-1.5 rounded-md bg-bg-tertiary text-text-tertiary text-[11px] flex items-center justify-between hover:bg-border transition"
        >
          <span className="flex items-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            Search...
          </span>
          <kbd className="text-[10px] bg-bg-secondary px-1.5 py-0.5 rounded text-text-tertiary">⌘K</kbd>
        </button>

        <div className="flex items-center gap-2 px-1 relative">
          <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-[10px] font-semibold text-white flex-shrink-0">
            {userEmail ? userEmail[0].toUpperCase() : "U"}
          </div>
          <span className="text-xs text-text-secondary flex-1 truncate">{userEmail || "User"}</span>
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="text-text-tertiary hover:text-text-secondary transition"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="1" />
              <circle cx="12" cy="5" r="1" />
              <circle cx="12" cy="19" r="1" />
            </svg>
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute bottom-full right-0 mb-1 w-36 bg-bg-secondary border border-border rounded-lg shadow-lg z-50 py-1">
                <button
                  onClick={() => { setMenuOpen(false); handleSignOut(); }}
                  className="w-full text-left px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-tertiary hover:text-text-primary transition"
                >
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
