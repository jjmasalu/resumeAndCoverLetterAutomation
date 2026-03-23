"use client";

import { useState } from "react";
import { downloadGeneratedDocument } from "@/lib/api";

interface DownloadCardProps {
  docType: string;
  documentId: string;
  filename: string;
}

export default function DownloadCard({
  docType,
  documentId,
  filename,
}: DownloadCardProps) {
  const label = docType === "resume" ? "Resume" : "Cover Letter";
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    try {
      setDownloading(true);
      await downloadGeneratedDocument(documentId, filename);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="ml-9 mb-4 flex items-center gap-3 rounded-lg border border-border border-l-2 border-l-accent bg-bg-secondary p-3">
      <svg
        className="h-6 w-6 flex-shrink-0 text-accent"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
      <div>
        <p className="text-sm font-medium text-text-primary">{label} ready</p>
        <p className="max-w-[28rem] truncate text-xs text-text-tertiary">{filename}</p>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="text-left text-xs text-accent transition hover:underline disabled:cursor-wait disabled:opacity-70"
        >
          {downloading ? "Preparing download..." : "Download file"}
        </button>
      </div>
    </div>
  );
}
