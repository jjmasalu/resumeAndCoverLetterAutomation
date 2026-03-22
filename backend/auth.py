import logging
from copy import deepcopy

import bcrypt
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import settings
from db import supabase

logger = logging.getLogger(__name__)
security = HTTPBearer()

jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
jwks_client = PyJWKClient(jwks_url, cache_keys=True)

TEAM_ACCESS_REQUIRED_DETAIL = {
    "code": "team_access_required",
    "message": "Enter the current team access code to continue.",
}
TEAM_ACCESS_BLOCKED_DETAIL = {
    "code": "team_access_blocked",
    "message": "Your access has been revoked. Contact the admin for a new code.",
}
INVALID_TEAM_ACCESS_CODE_DETAIL = {
    "code": "invalid_team_access_code",
    "message": "That access code is not valid.",
}
TEAM_ACCESS_UNCONFIGURED_DETAIL = {
    "code": "team_access_unconfigured",
    "message": "Team access is enabled, but no active code has been configured yet.",
}

_missing_team_access_schema_logged = False


def _log_missing_team_access_schema(error: Exception):
    global _missing_team_access_schema_logged
    if _missing_team_access_schema_logged:
        return
    logger.warning(
        "Team access schema is not available yet; access gating is temporarily disabled: %s",
        error,
    )
    _missing_team_access_schema_logged = True


def _is_missing_team_access_schema_error(error: Exception) -> bool:
    message = str(error)
    return "team_access_" in message or "team_access_version" in message


def get_team_access_state() -> dict | None:
    try:
        result = (
            supabase.table("team_access_state")
            .select("enabled, current_version")
            .eq("id", 1)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception as error:
        if _is_missing_team_access_schema_error(error):
            _log_missing_team_access_schema(error)
            return None
        raise


def get_team_access_profile(user_id: str) -> dict | None:
    try:
        result = (
            supabase.table("profiles")
            .select("id, team_access_version, team_access_blocked")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return result.data
    except Exception as error:
        if _is_missing_team_access_schema_error(error):
            _log_missing_team_access_schema(error)
            return None
        raise


def verify_team_access_code(code: str, code_hash: str) -> bool:
    try:
        return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))
    except ValueError:
        logger.warning("Stored team access hash has an unexpected format")
        return False


def ensure_team_access(user_id: str):
    state = get_team_access_state()
    if not state or not state.get("enabled"):
        return

    profile = get_team_access_profile(user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if profile.get("team_access_blocked"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=deepcopy(TEAM_ACCESS_BLOCKED_DETAIL),
        )

    current_version = int(state.get("current_version") or 0)
    user_version = int(profile.get("team_access_version") or 0)
    if user_version != current_version:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=deepcopy(TEAM_ACCESS_REQUIRED_DETAIL),
        )


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Decode Supabase JWT and return user ID."""
    token = credentials.credentials
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: no subject",
            )
        return user_id
    except jwt.PyJWTError as e:
        logger.error(f"JWT decode failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


async def get_current_user(
    user_id: str = Depends(get_authenticated_user),
) -> str:
    ensure_team_access(user_id)
    return user_id
