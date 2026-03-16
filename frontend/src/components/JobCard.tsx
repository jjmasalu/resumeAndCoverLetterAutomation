"use client";

interface JobCardProps {
  title: string;
  url: string;
  snippet: string;
  matchScore: number;
  company?: string;
  location?: string;
  onAction: (action: string) => void;
}

function scoreBadge(score: number) {
  if (score >= 80) return { bg: "bg-[rgba(34,197,94,0.1)]", text: "text-success" };
  if (score >= 60) return { bg: "bg-[rgba(245,158,11,0.1)]", text: "text-warning" };
  return { bg: "bg-[rgba(239,68,68,0.1)]", text: "text-danger" };
}

export default function JobCard({ title, url, snippet, matchScore, company, location, onAction }: JobCardProps) {
  const badge = scoreBadge(matchScore);

  return (
    <div className="ml-9 my-2 bg-bg-secondary border border-border border-l-2 border-l-accent rounded-xl p-3.5 max-w-md">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="text-sm font-medium text-text-primary">{title}</div>
        <span className={`${badge.bg} ${badge.text} text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0`}>
          {matchScore}% match
        </span>
      </div>

      {/* Meta */}
      {(company || location) && (
        <div className="text-xs text-text-tertiary mb-1.5">
          {company}{company && location ? " · " : ""}{location}
        </div>
      )}

      {/* Snippet */}
      <div className="text-xs text-text-secondary leading-relaxed mb-2.5 line-clamp-2">
        {snippet}
      </div>

      {/* URL */}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[11px] text-accent hover:underline truncate block mb-3"
        style={{ overflowWrap: "anywhere" }}
      >
        {url.length > 60 ? url.slice(0, 60) + "..." : url}
      </a>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onAction(`Generate a tailored resume for this job: ${title} at ${company || "this company"} (${url})`)}
          className="bg-accent text-white text-[11px] font-medium px-3 py-1 rounded-lg hover:bg-accent-hover transition"
        >
          Generate Resume
        </button>
        <button
          onClick={() => onAction(`Show me the full job description for: ${title} at ${company || "this company"} (${url})`)}
          className="bg-bg-tertiary text-text-secondary text-[11px] font-medium px-3 py-1 rounded-lg hover:text-text-primary transition"
        >
          View Details
        </button>
      </div>
    </div>
  );
}
