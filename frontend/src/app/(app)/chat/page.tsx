"use client";

import { Suspense, useState, useCallback, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { apiJson, apiUpload } from "@/lib/api";
import { storePendingChatMessage } from "@/lib/pending-chat";
import FileUpload from "@/components/FileUpload";
import AttachmentComposer from "@/components/AttachmentComposer";
import { MODE_COPY } from "@/lib/conversation-modes";
import {
  clearPendingLandingIntent,
  readPendingLandingIntent,
} from "@/lib/pending-landing-intent";
import { takePendingFiles } from "@/lib/pending-files";
import { ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR, validateAttachmentFiles } from "@/lib/attachment-validation";
import { useFileDropzone } from "@/lib/use-file-dropzone";

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
  const [uploadingAttachments, setUploadingAttachments] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const stageFiles = useCallback((files: File[]) => {
    const { accepted, errorMessage } = validateAttachmentFiles(files);
    if (errorMessage) {
      setAttachError(errorMessage);
    }
    if (accepted.length === 0) {
      return;
    }
    setPendingFiles((prev) => [...prev, ...accepted]);
    setAttachError(null);
  }, []);

  const { isDragOver, dropzoneProps } = useFileDropzone(stageFiles);

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

  useEffect(() => {
    if (mode !== "job_to_resume" || input.trim()) {
      return;
    }

    const pendingIntent = readPendingLandingIntent();
    if (!pendingIntent || pendingIntent.kind !== "specific_job") {
      return;
    }

    setInput(pendingIntent.input);
    clearPendingLandingIntent();
  }, [mode, input]);

  useEffect(() => {
    if (mode !== "find_jobs") {
      return;
    }

    const pendingIntent = readPendingLandingIntent();
    if (!pendingIntent || pendingIntent.kind !== "find_jobs_attachment") {
      return;
    }

    const files = takePendingFiles(pendingIntent.token);
    if (files.length > 0) {
      setPendingFiles((prev) => [...prev, ...files]);
      setAttachError(null);
    }
    clearPendingLandingIntent();
  }, [mode]);

  const createAndRedirect = async (message: string, attachments: File[] = []) => {
    setSending(true);
    setAttachError(null);
    try {
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });

      let attachmentFileIds: string[] = [];
      if (attachments.length > 0) {
        setUploadingAttachments(true);
        const uploads = await Promise.all(
          attachments.map((file) =>
            apiUpload<{ file_id: string }>(`/conversations/${conv.id}/upload`, file)
          )
        );
        attachmentFileIds = uploads.map((upload) => upload.file_id);
        setUploadingAttachments(false);
      }

      storePendingChatMessage(conv.id, message, attachmentFileIds);
      window.location.assign(`/chat/${conv.id}`);
    } catch (err) {
      console.error("Failed to create conversation:", err);
      setSending(false);
      setUploadingAttachments(false);
      setAttachError(err instanceof Error ? err.message : "Upload failed — please try again.");
    }
  };

  const handleSend = () => {
    if (sending || uploadingAttachments) return;
    const trimmedInput = input.trim();
    if (!trimmedInput && pendingFiles.length === 0) return;

    const message =
      trimmedInput ||
      (mode === "find_jobs"
        ? `I've attached ${pendingFiles.map((file) => file.name).join(", ")}. Please review ${pendingFiles.length > 1 ? "them" : "it"} for my job search.`
        : `I've attached ${pendingFiles.map((file) => file.name).join(", ")}. Please use ${pendingFiles.length > 1 ? "them" : "it"} to tailor my application materials.`);

    createAndRedirect(message, pendingFiles);
  };

  const removePendingFile = (index: number) => {
    setPendingFiles((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isComposerBusy = sending || uploadingAttachments;

  return (
    <div className="flex flex-col h-full">
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
              {MODE_COPY.job_to_resume.emptyStateHint}
            </p>
          </>
        ) : (
          <>
            <FileUpload
              onFilesSelect={stageFiles}
              selecting={uploadingAttachments}
              selectedFilename={pendingFiles.length === 1 ? pendingFiles[0].name : null}
              statusLabel="Ready to send"
            />

            {!pendingFiles.length && !uploadingAttachments && (
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
            {MODE_COPY.job_to_resume.label}
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
            {MODE_COPY.find_jobs.label}
          </button>
        </div>
      </div>

      <div className="border-t border-border px-5 py-3">
        <div className="max-w-3xl mx-auto">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR}
            onChange={(e) => {
              const files = Array.from(e.target.files || []);
              if (files.length > 0) stageFiles(files);
              e.target.value = "";
            }}
            className="hidden"
          />
          <AttachmentComposer
            files={pendingFiles}
            uploading={uploadingAttachments}
            onRemove={removePendingFile}
            disabled={isComposerBusy}
          />
          <div
            {...dropzoneProps}
            className={`flex items-center gap-2 bg-bg-secondary border border-border rounded-xl px-3.5 py-2.5 transition ${
              isComposerBusy
                ? "opacity-50"
                : isDragOver
                  ? "border-accent bg-accent-muted/40 ring-1 ring-accent/30"
                  : ""
            }`}
          >
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isComposerBusy}
              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 bg-accent-muted text-accent hover:bg-accent/20 transition"
              aria-label="Attach file"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            {attachError && (
              <span className="text-xs text-red-500">{attachError}</span>
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                mode === "find_jobs"
                  ? "Describe your experience and what roles you're looking for..."
                  : "Paste a job URL, company + role, or job description..."
              }
              rows={1}
              disabled={isComposerBusy}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary resize-none outline-none max-h-40"
            />
            <button
              onClick={handleSend}
              disabled={isComposerBusy || (!input.trim() && pendingFiles.length === 0)}
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition ${
                (input.trim() || pendingFiles.length > 0) && !isComposerBusy
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
            <span>
              {isDragOver
                ? "Drop files here to stage them"
                : pendingFiles.length > 0 && !uploadingAttachments
                ? "Attachments stay local until you send"
                : uploadingAttachments
                  ? "Uploading attachments with this message..."
                  : "Enter to send · Shift+Enter for newline"}
            </span>
            <span>Powered by Gemini</span>
          </div>
        </div>
      </div>
    </div>
  );
}
