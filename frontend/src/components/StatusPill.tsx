interface StatusPillProps {
  tool: string;
  state: "running" | "done";
}

const TOOL_LABELS: Record<string, string> = {
  search_jobs: "Searching for jobs",
  scrape_job: "Reading job posting",
  generate_document: "Generating document",
  save_user_context: "Saving your info",
};

export default function StatusPill({ tool, state }: StatusPillProps) {
  const label = TOOL_LABELS[tool] || tool;
  return (
    <div className="flex items-center gap-2 text-xs text-text-secondary mb-3 ml-9">
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full bg-accent ${
          state === "running" ? "animate-pulse" : ""
        }`}
      />
      <span>
        {label}
        {state === "running" ? "..." : " — done"}
      </span>
    </div>
  );
}
