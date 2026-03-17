"use client";

import { Suspense, useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiJson, apiUpload } from "@/lib/api";
import { useApp } from "@/components/AppContext";
import FileUpload from "@/components/FileUpload";

export default function ChatIndexPage() {
  return (
    <Suspense>
      <ChatIndexContent />
    </Suspense>
  );
}

function ChatIndexContent() {
  const searchParams = useSearchParams();
  const modeParam = searchParams.get("mode");
  const [mode, setMode] = useState<"job_to_resume" | "find_jobs">(
    modeParam === "find_jobs" ? "find_jobs" : "job_to_resume"
  );
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const { refreshConversations } = useApp();

  const adjustTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, []);

  useEffect(() => {
    adjustTextarea();
  }, [input, adjustTextarea]);

  const createAndRedirect = async (message: string, file?: File) => {
    setSending(true);
    try {
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });

      if (file) {
        setUploading(true);
        await apiUpload(`/conversations/${conv.id}/upload`, file);
        setUploading(false);
      }

      await refreshConversations();
      router.push(`/chat/${conv.id}?initial=${encodeURIComponent(message)}`);
    } catch (err) {
      console.error("Failed to create conversation:", err);
      setSending(false);
      setUploading(false);
    }
  };

  const handleSend = () => {
    if (!input.trim() || sending) return;
    createAndRedirect(input.trim());
  };

  const handleFileSelect = (file: File) => {
    setUploadedFilename(file.name);
    // Auto-create conversation and redirect
    createAndRedirect(
      "I've uploaded my resume. Please analyze it and help me find matching jobs.",
      file
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Empty state */}
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        {mode === "job_to_resume" ? (
          <>
            <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h2 className="text-base font-semibold text-text-primary mb-1.5">Start a conversation</h2>
            <p className="text-sm text-text-tertiary text-center max-w-xs mb-5">
              Paste a job posting URL or describe the role you&apos;re targeting.
            </p>
          </>
        ) : (
          <>
            <FileUpload
              onFileSelect={handleFileSelect}
              uploading={uploading}
              uploadedFilename={uploadedFilename}
            />

            {!uploadedFilename && !uploading && (
              <>
                <div className="flex items-center gap-3 w-full max-w-xs my-4">
                  <div className="flex-1 h-px bg-border" />
                  <span className="text-xs text-text-tertiary">or</span>
                  <div className="flex-1 h-px bg-border" />
                </div>
                <p className="text-xs text-text-tertiary">Type your experience in the chat below</p>
              </>
            )}
          </>
        )}

        {/* Mode pills */}
        <div className="flex gap-2 mt-5">
          <button
            onClick={() => setMode("job_to_resume")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs transition ${
              mode === "job_to_resume"
                ? "bg-accent text-white"
                : "bg-bg-secondary border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
            }`}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Job &rarr; Resume
          </button>
          <button
            onClick={() => setMode("find_jobs")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs transition ${
              mode === "find_jobs"
                ? "bg-accent text-white"
                : "bg-bg-secondary border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
            }`}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            Find Jobs
          </button>
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t border-border px-5 py-3">
        <div className="max-w-3xl mx-auto">
          <div
            className={`flex items-center gap-2 bg-bg-secondary border border-border rounded-xl px-3.5 py-2.5 transition ${
              sending ? "opacity-50" : ""
            }`}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                mode === "find_jobs"
                  ? "Describe your experience and what roles you're looking for..."
                  : "Message Resume AI..."
              }
              rows={1}
              disabled={sending}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary resize-none outline-none max-h-40"
            />
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition ${
                input.trim() && !sending
                  ? "bg-accent text-white"
                  : "bg-bg-tertiary text-text-tertiary"
              }`}
              aria-label="Send message"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
          <div className="flex justify-between mt-1.5 text-[10px] text-text-tertiary px-1">
            <span>Enter to send &middot; Shift+Enter for newline</span>
            <span>Powered by Gemini</span>
          </div>
        </div>
      </div>
    </div>
  );
}
