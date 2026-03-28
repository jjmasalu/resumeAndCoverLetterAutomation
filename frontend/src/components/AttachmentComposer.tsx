"use client";

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileKindLabel(type: string, name: string) {
  if (type === "application/pdf" || name.toLowerCase().endsWith(".pdf")) return "PDF";
  if (
    type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    name.toLowerCase().endsWith(".docx")
  ) {
    return "DOCX";
  }
  if (type === "image/png" || name.toLowerCase().endsWith(".png")) return "PNG";
  if (
    type === "image/jpeg" ||
    name.toLowerCase().endsWith(".jpg") ||
    name.toLowerCase().endsWith(".jpeg")
  ) {
    return "JPG";
  }
  return "File";
}

interface AttachmentComposerProps {
  files: File[];
  uploading: boolean;
  onRemove: (index: number) => void;
  disabled?: boolean;
}

export default function AttachmentComposer({
  files,
  uploading,
  onRemove,
  disabled = false,
}: AttachmentComposerProps) {
  if (files.length === 0) return null;

  return (
    <div className="mb-2 rounded-xl border border-border bg-bg-secondary/60 p-2.5">
      <div className="mb-2 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          {uploading ? (
            <div className="h-3.5 w-3.5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
          ) : (
            <div className="h-2.5 w-2.5 rounded-full bg-amber-400" />
          )}
          <span className="text-xs font-medium text-text-primary">
            {uploading
              ? `Uploading ${files.length} attachment${files.length === 1 ? "" : "s"}`
              : `${files.length} attachment${files.length === 1 ? "" : "s"} ready to send`}
          </span>
        </div>
        <span className="text-[11px] text-text-tertiary">
          {uploading ? "Sending with this message" : "Will upload on send"}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {files.map((file, index) => (
          <div
            key={`${file.name}-${file.size}-${index}`}
            className="inline-flex max-w-full items-center gap-2 rounded-full border border-border bg-bg-primary px-3 py-1.5 text-xs"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="shrink-0 text-accent"
            >
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
            <span className="truncate text-text-primary">{file.name}</span>
            <span className="text-text-tertiary">
              {fileKindLabel(file.type, file.name)} · {formatFileSize(file.size)}
            </span>
            <button
              onClick={() => onRemove(index)}
              disabled={disabled || uploading}
              className="shrink-0 text-text-tertiary hover:text-text-primary disabled:opacity-40"
              aria-label={`Remove ${file.name}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
