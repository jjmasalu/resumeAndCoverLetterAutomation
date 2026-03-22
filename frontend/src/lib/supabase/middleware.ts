import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import {
  buildAccessCodePath,
  type TeamAccessReason,
} from "@/lib/team-access";

type TeamAccessDecision = {
  requiresCode: boolean;
  reason?: TeamAccessReason;
};

function buildReturnTo(request: NextRequest) {
  const search = request.nextUrl.search;
  const path = `${request.nextUrl.pathname}${search}`;
  return path === "/" ? "/chat" : path;
}

function isMissingTeamAccessSchema(message: string) {
  return message.includes("team_access_") || message.includes("team_access_version");
}

async function getTeamAccessDecision(
  supabase: ReturnType<typeof createServerClient>,
  userId: string
): Promise<TeamAccessDecision> {
  const stateResult = await supabase
    .from("team_access_state")
    .select("enabled, current_version")
    .eq("id", 1)
    .maybeSingle();

  if (stateResult.error) {
    if (isMissingTeamAccessSchema(stateResult.error.message)) {
      return { requiresCode: false };
    }
    throw stateResult.error;
  }

  if (!stateResult.data?.enabled) {
    return { requiresCode: false };
  }

  const profileResult = await supabase
    .from("profiles")
    .select("team_access_version, team_access_blocked")
    .eq("id", userId)
    .single();

  if (profileResult.error) {
    if (isMissingTeamAccessSchema(profileResult.error.message)) {
      return { requiresCode: false };
    }
    throw profileResult.error;
  }

  if (profileResult.data.team_access_blocked) {
    return { requiresCode: true, reason: "team_access_blocked" };
  }

  if ((profileResult.data.team_access_version ?? 0) !== stateResult.data.current_version) {
    return { requiresCode: true, reason: "team_access_required" };
  }

  return { requiresCode: false };
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (cookiesToSet) => {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const pathname = request.nextUrl.pathname;
  const isLoginRoute = pathname.startsWith("/login");
  const isAuthRoute = pathname.startsWith("/auth");
  const isAccessCodeRoute = pathname.startsWith("/access-code");
  const isPublic = pathname === "/" || isLoginRoute || isAuthRoute;

  if (!user && !isPublic) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("returnTo", buildReturnTo(request));
    return NextResponse.redirect(loginUrl);
  }

  if (!user) {
    return response;
  }

  let teamAccess: TeamAccessDecision = { requiresCode: false };
  try {
    teamAccess = await getTeamAccessDecision(supabase, user.id);
  } catch (error) {
    console.error("Failed to evaluate team access gate", error);
  }

  if (teamAccess.requiresCode && !isAccessCodeRoute && !isAuthRoute) {
    const redirectPath = buildAccessCodePath(
      buildReturnTo(request),
      teamAccess.reason
    );
    return NextResponse.redirect(new URL(redirectPath, request.url));
  }

  if (!teamAccess.requiresCode && isAccessCodeRoute) {
    const returnTo = request.nextUrl.searchParams.get("returnTo") || "/chat";
    return NextResponse.redirect(new URL(returnTo, request.url));
  }

  if (!teamAccess.requiresCode && isLoginRoute) {
    return NextResponse.redirect(new URL("/chat", request.url));
  }

  return response;
}
