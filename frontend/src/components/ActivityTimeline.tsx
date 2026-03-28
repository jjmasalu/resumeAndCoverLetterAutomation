"use client";

import { useEffect, useState } from "react";

export interface ActivityStep {
  id: string;
  phase: string;
  label: string;
  state: "running" | "done" | "failed";
  tool?: string;
  detail?: string;
  meta?: Record<string, unknown>;
}

interface ActivityTimelineProps {
  steps: ActivityStep[];
  defaultExpanded?: boolean;
}

function stateClasses(state: ActivityStep["state"]) {
  if (state === "failed") {
    return {
      dot: "bg-danger",
      ring: "border-danger/30",
      text: "text-danger",
      badge: "Failed",
    };
  }
  if (state === "done") {
    return {
      dot: "bg-success",
      ring: "border-success/30",
      text: "text-success",
      badge: "Done",
    };
  }
  return {
    dot: "bg-accent animate-pulse",
    ring: "border-accent/30",
    text: "text-accent",
    badge: "Running",
  };
}

export default function ActivityTimeline({
  steps,
  defaultExpanded = true,
}: ActivityTimelineProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  useEffect(() => {
    if (steps.some((step) => step.state === "running")) {
      setExpanded(true);
    }
  }, [steps]);

  if (steps.length === 0) return null;

  const activeCount = steps.filter((step) => step.state === "running").length;

  return (
    <div className="ml-9 mb-4 rounded-xl border border-border bg-bg-secondary/70">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary">Activity</span>
            {activeCount > 0 && (
              <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent">
                Live
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-text-tertiary">
            {activeCount > 0
              ? `${activeCount} step${activeCount === 1 ? "" : "s"} in progress`
              : "Execution trace for this turn"}
          </p>
        </div>
        <span className="text-text-tertiary">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className={`transition-transform ${expanded ? "rotate-180" : ""}`}
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </button>

      {expanded && (
        <div className="border-t border-border px-4 py-3">
          <div className="space-y-3">
            {steps.map((step, index) => {
              const classes = stateClasses(step.state);
              return (
                <div key={step.id} className="relative flex gap-3">
                  <div className="flex w-4 flex-col items-center">
                    <span className={`mt-1 inline-block h-2.5 w-2.5 rounded-full ${classes.dot}`} />
                    {index < steps.length - 1 && (
                      <span className="mt-1 h-full w-px bg-border" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-text-primary">{step.label}</p>
                      <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${classes.ring} ${classes.text}`}>
                        {classes.badge}
                      </span>
                    </div>
                    {step.detail && (
                      <p className="mt-1 text-xs leading-relaxed text-text-secondary">
                        {step.detail}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
