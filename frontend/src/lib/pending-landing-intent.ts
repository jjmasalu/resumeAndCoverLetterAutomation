"use client";

const PENDING_LANDING_INTENT_KEY = "pending-landing-intent";

export type PendingLandingIntent =
  | {
      kind: "specific_job";
      input: string;
    }
  | {
      kind: "find_jobs_attachment";
      token: string;
      filename: string;
    };

export function storePendingLandingIntent(intent: PendingLandingIntent) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(PENDING_LANDING_INTENT_KEY, JSON.stringify(intent));
}

export function readPendingLandingIntent(): PendingLandingIntent | null {
  if (typeof window === "undefined") return null;
  const raw = window.sessionStorage.getItem(PENDING_LANDING_INTENT_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingLandingIntent;
    if (parsed?.kind === "specific_job" && typeof parsed.input === "string") {
      return parsed;
    }
    if (
      parsed?.kind === "find_jobs_attachment" &&
      typeof parsed.token === "string" &&
      typeof parsed.filename === "string"
    ) {
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

export function clearPendingLandingIntent() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(PENDING_LANDING_INTENT_KEY);
}
