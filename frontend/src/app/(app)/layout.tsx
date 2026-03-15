"use client";

import AppProvider, { useApp } from "@/components/AppContext";
import Sidebar from "@/components/Sidebar";
import ThemeToggle from "@/components/ThemeToggle";
import { usePathname } from "next/navigation";

function TopBar() {
  const { activeConversation } = useApp();
  const pathname = usePathname();

  let title = "New Chat";
  let status: string | null = null;

  if (pathname === "/history") {
    title = "All Conversations";
  } else if (activeConversation) {
    title = activeConversation.title;
    status = activeConversation.status;
  }

  return (
    <div className="h-12 border-b border-border flex items-center justify-between px-5 flex-shrink-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-medium text-sm text-text-primary truncate">{title}</span>
        {status && (
          <span
            className={`text-[10px] px-2 py-0.5 rounded-full border flex-shrink-0 ${
              status === "active"
                ? "bg-accent-muted text-accent border-accent/20"
                : "bg-bg-tertiary text-text-secondary border-border"
            }`}
          >
            {status === "active" ? "Active" : "Completed"}
          </span>
        )}
      </div>
      <ThemeToggle />
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <div className="flex h-screen bg-bg-primary">
        <Sidebar />
        <main className="flex-1 flex flex-col min-w-0">
          <TopBar />
          <div className="flex-1 flex flex-col overflow-hidden">{children}</div>
        </main>
      </div>
    </AppProvider>
  );
}
