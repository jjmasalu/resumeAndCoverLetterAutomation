import { createClient } from "@/lib/supabase/client";
import {
  buildAccessCodePath,
  isTeamAccessReason,
  type TeamAccessReason,
} from "@/lib/team-access";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export async function toApiError(response: Response) {
  let message = `API error: ${response.status}`;
  let code: string | undefined;

  try {
    const payload = await response.clone().json();
    const detail = payload?.detail;

    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      if (typeof detail.message === "string") {
        message = detail.message;
      }
      if (typeof detail.code === "string") {
        code = detail.code;
      }
    }
  } catch {
    const text = await response.text();
    if (text) {
      message = text;
    }
  }

  return new ApiError(message, response.status, code);
}

export function handleTeamAccessRedirect(
  error: ApiError,
  returnTo?: string
) {
  if (typeof window === "undefined") {
    return;
  }

  if (!isTeamAccessReason(error.code)) {
    return;
  }

  const target =
    returnTo || `${window.location.pathname}${window.location.search}`;
  window.location.assign(
    buildAccessCodePath(target, error.code as TeamAccessReason)
  );
}

export async function apiFetch(path: string, options: RequestInit = {}) {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    throw new Error("Not authenticated");
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.access_token}`,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const error = await toApiError(res);
    handleTeamAccessRedirect(error);
    throw error;
  }

  return res;
}

export async function apiJson<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await apiFetch(path, options);
  return res.json();
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    throw new Error("Not authenticated");
  }

  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session?.access_token}` },
    body: form,
  });

  if (!res.ok) {
    const error = await toApiError(res);
    handleTeamAccessRedirect(error);
    throw error;
  }
  return res.json();
}
