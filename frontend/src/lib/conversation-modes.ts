export type ConversationMode = "job_to_resume" | "find_jobs";

export const MODE_COPY: Record<
  ConversationMode,
  {
    label: string;
    tabLabel: string;
    description: string;
    emptyStateHint: string;
  }
> = {
  job_to_resume: {
    label: "Specific job",
    tabLabel: "Target a specific job",
    description: "Best when you already have a posting, target company, or pasted job description.",
    emptyStateHint: "Share a job URL, company + role, or paste the job description.",
  },
  find_jobs: {
    label: "Find jobs",
    tabLabel: "Find matching jobs",
    description: "Start from your resume or background and we’ll find roles that fit.",
    emptyStateHint: "Upload your resume or describe your background and target roles.",
  },
};

export function isConversationMode(value: string): value is ConversationMode {
  return value === "job_to_resume" || value === "find_jobs";
}

export function getModeCopy(mode: string) {
  if (isConversationMode(mode)) {
    return MODE_COPY[mode];
  }
  return {
    label: "Conversation",
    tabLabel: "Conversation",
    description: "Start a conversation about a job or your search.",
    emptyStateHint: "Share a job URL, your background, or what you want help with.",
  };
}
