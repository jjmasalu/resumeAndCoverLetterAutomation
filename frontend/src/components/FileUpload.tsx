"use client";

import { useState, useRef, useCallback } from "react";
import {
  ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR,
  validateAttachmentFiles,
} from "@/lib/attachment-validation";

interface FileUploadProps {
  onFilesSelect: (files: File[]) => void;
  selecting?: boolean;
  selectedFilename?: string | null;
  statusLabel?: string;
}

export default function FileUpload({
  onFilesSelect,
  selecting,
  selectedFilename,
  statusLabel = "Ready to send",
}: FileUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    (files: File[]) => {
      setError(null);
      const { accepted, errorMessage } = validateAttachmentFiles(files);
      if (errorMessage) {
        setError(errorMessage);
      }
      if (accepted.length === 0) {
        return;
      }
      onFilesSelect(accepted);
    },
    [onFilesSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files || []);
      if (files.length > 0) handleFile(files);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(e.target.files || []);
      if (files.length > 0) handleFile(files);
      e.target.value = "";
    },
    [handleFile]
  );

  // Uploaded state
  if (selectedFilename) {
    return (
      <div className="w-full max-w-xs border border-border rounded-xl px-4 py-3 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-accent-muted flex items-center justify-center flex-shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-xs text-text-primary truncate">{selectedFilename}</div>
          <div className="text-[10px] text-text-tertiary">{statusLabel}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-xs">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl px-6 py-8 text-center cursor-pointer transition ${
          dragOver
            ? "border-accent bg-accent-muted"
            : error
              ? "border-danger/50"
              : "border-border hover:border-text-tertiary"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ATTACHMENT_ACCEPTED_EXTENSIONS_ATTR}
          onChange={handleChange}
          className="hidden"
        />

        {selecting ? (
          <>
            <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <div className="text-xs text-text-secondary">Preparing...</div>
          </>
        ) : (
          <>
            <div className="w-10 h-10 rounded-lg bg-accent-muted flex items-center justify-center mx-auto mb-3">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
              </svg>
            </div>
            <div className="text-sm font-medium text-text-primary mb-1">Upload your resume</div>
            <div className="text-xs text-text-tertiary mb-3">PDF, DOCX, or image &mdash; we&apos;ll extract everything</div>
            <div className="inline-block bg-accent text-white text-xs font-medium px-4 py-1.5 rounded-lg">
              Choose file
            </div>
          </>
        )}
      </div>

      {error && (
        <div className="mt-2 flex items-center gap-1.5 px-1">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-danger flex-shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M15 9l-6 6M9 9l6 6" />
          </svg>
          <span className="text-xs text-danger">{error}</span>
          <button onClick={() => setError(null)} className="text-xs text-text-tertiary hover:text-text-secondary ml-auto">
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
