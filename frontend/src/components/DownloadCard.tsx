interface DownloadCardProps {
  docType: string;
  downloadUrl: string;
}

export default function DownloadCard({ docType, downloadUrl }: DownloadCardProps) {
  const label = docType === "resume" ? "Resume" : "Cover Letter";
  const fileName = `${docType || "document"}.docx`;
  const href = downloadUrl
    ? `${downloadUrl}&download=${encodeURIComponent(fileName)}`
    : "#";

  return (
    <div className="ml-9 mb-4 flex items-center gap-3 p-3 bg-bg-secondary border border-border rounded-lg border-l-2 border-l-accent">
      <svg
        className="w-6 h-6 text-accent flex-shrink-0"
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
        <a
          href={href}
          download={fileName}
          className="text-xs text-accent hover:underline"
        >
          Download .docx
        </a>
      </div>
    </div>
  );
}
