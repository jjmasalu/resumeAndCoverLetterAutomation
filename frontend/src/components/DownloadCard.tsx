interface DownloadCardProps {
  docType: string;
  downloadUrl: string;
}

export default function DownloadCard({ docType, downloadUrl }: DownloadCardProps) {
  const label = docType === "resume" ? "Resume" : "Cover Letter";
  return (
    <div className="inline-flex items-center gap-3 p-3 bg-green-50 border border-green-200 rounded-lg mb-4">
      <svg
        className="w-8 h-8 text-green-600"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
      <div>
        <p className="font-medium text-green-800">{label} ready</p>
        <a
          href={downloadUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm text-green-600 hover:underline"
        >
          Download .docx
        </a>
      </div>
    </div>
  );
}
