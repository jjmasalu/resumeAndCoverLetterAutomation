export type TeamAccessReason =
  | "team_access_required"
  | "team_access_blocked";

export function isTeamAccessReason(
  value: string | null | undefined
): value is TeamAccessReason {
  return (
    value === "team_access_required" || value === "team_access_blocked"
  );
}

export function buildAccessCodePath(
  returnTo = "/chat",
  reason?: TeamAccessReason
) {
  const params = new URLSearchParams();
  params.set("returnTo", returnTo);

  if (reason) {
    params.set("reason", reason);
  }

  return `/access-code?${params.toString()}`;
}
