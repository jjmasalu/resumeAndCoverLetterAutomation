"use client";

import { useRouter } from "next/navigation";
import { useApp } from "@/components/AppContext";
import { apiJson } from "@/lib/api";

export default function ChatIndexPage() {
  const router = useRouter();
  const { refreshConversations } = useApp();

  const startChat = async (mode: "job_to_resume" | "find_jobs") => {
    const conv = await apiJson<{ id: string }>("/conversations", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    await refreshConversations();
    router.push(`/chat/${conv.id}`);
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6">
      <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <h2 className="text-base font-semibold text-text-primary mb-1.5">Start a conversation</h2>
      <p className="text-sm text-text-tertiary text-center max-w-xs mb-5">
        Paste a job posting URL or describe the role you&apos;re targeting. I&apos;ll tailor your resume and write a cover letter.
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => startChat("job_to_resume")}
          className="flex items-center gap-1.5 px-3.5 py-1.5 bg-bg-secondary border border-border rounded-lg text-xs text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-tertiary">
            <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          Paste a URL
        </button>
        <button
          onClick={() => startChat("find_jobs")}
          className="flex items-center gap-1.5 px-3.5 py-1.5 bg-bg-secondary border border-border rounded-lg text-xs text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-tertiary">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.35-4.35" />
          </svg>
          Search for jobs
        </button>
      </div>
    </div>
  );
}
