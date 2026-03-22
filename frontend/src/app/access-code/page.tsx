"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { ApiError, apiJson } from "@/lib/api";
import {
  isTeamAccessReason,
  type TeamAccessReason,
} from "@/lib/team-access";

const BRAND_NAME = "Resume AI";

export default function AccessCodePage() {
  return (
    <Suspense>
      <AccessCodeContent />
    </Suspense>
  );
}

function AccessCodeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get("returnTo") || "/chat";
  const initialReason = searchParams.get("reason");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(initialReason === "team_access_blocked");

  const title = blocked ? "Access revoked" : "Team access required";
  const description = useMemo(() => {
    if (blocked) {
      return "This account is blocked for the current team test. Contact the admin if you need access restored.";
    }
    return "Enter the shared team access code to continue into the test environment.";
  }, [blocked]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!code.trim()) return;

    setLoading(true);
    setError("");

    try {
      const result = await apiJson<{ status: string }>("/access/verify", {
        method: "POST",
        body: JSON.stringify({ code }),
      });

      if (result.status === "disabled") {
        router.push(returnTo);
        return;
      }

      router.push(returnTo);
    } catch (unknownError) {
      if (unknownError instanceof ApiError) {
        setError(unknownError.message);
        if (unknownError.code === "team_access_blocked") {
          setBlocked(true);
        }
      } else {
        setError("Could not verify the access code. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSignOut = async () => {
    await createClient().auth.signOut();
    router.push("/login");
  };

  const reasonLabel: TeamAccessReason | null = isTeamAccessReason(initialReason)
    ? initialReason
    : null;

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-primary px-6">
      <div className="w-full max-w-sm rounded-2xl border border-border bg-bg-secondary p-6 shadow-sm">
        <div className="text-center mb-6">
          <div className="w-10 h-10 bg-accent rounded-xl flex items-center justify-center text-lg font-bold text-white mx-auto mb-3">
            R
          </div>
          <h1 className="text-xl font-semibold text-text-primary">{title}</h1>
          <p className="text-sm text-text-tertiary mt-2">{description}</p>
        </div>

        {!blocked && (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="block text-xs font-medium text-text-secondary mb-1.5">
                Access code
              </label>
              <input
                type="password"
                value={code}
                onChange={(event) => setCode(event.target.value)}
                placeholder="Enter shared code"
                className="w-full px-3 py-2.5 bg-bg-primary border border-border rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:ring-2 focus:ring-accent focus:border-transparent outline-none"
                autoFocus
                required
              />
            </div>

            {error && <p className="text-danger text-xs">{error}</p>}

            <button
              type="submit"
              disabled={loading || !code.trim()}
              className="w-full py-2.5 px-4 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover transition disabled:opacity-50"
            >
              {loading ? "Checking..." : "Continue"}
            </button>
          </form>
        )}

        {blocked && (
          <div className="space-y-3">
            {error && <p className="text-danger text-xs">{error}</p>}
            <button
              onClick={handleSignOut}
              className="w-full py-2.5 px-4 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover transition"
            >
              Sign out
            </button>
          </div>
        )}

        <div className="mt-5 text-center text-[11px] text-text-tertiary">
          {reasonLabel === "team_access_required"
            ? "Your previous code has expired or has been rotated."
            : `Protected team environment for ${BRAND_NAME}.`}
        </div>
      </div>
    </div>
  );
}
