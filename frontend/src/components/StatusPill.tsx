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
    <div className="flex items-center gap-2 text-sm text-gray-500 mb-3">
      {state === "running" ? (
        <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full animate-pulse" />
      ) : (
        <span className="inline-block w-2 h-2 bg-green-400 rounded-full" />
      )}
      {label}
      {state === "running" ? "..." : " — done"}
    </div>
  );
}
