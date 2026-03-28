#!/usr/bin/env python3
"""Backend API test runner. Tests all endpoints with real auth and streaming.

Usage:
    python test_api.py                    # Run all tests
    python test_api.py --test upload      # Run specific test
    python test_api.py --verbose          # Show full response bodies
"""

import argparse
import json
import mimetypes
import os
import sys
import time
import httpx
from config import settings
from supabase import create_client

DEFAULT_BASE_URL = os.getenv("TEST_API_BASE_URL", "http://127.0.0.1:8000")
BASE_URL = DEFAULT_BASE_URL
TEST_EMAIL = "test-api@example.com"
TEST_PASSWORD = "TestPass123!"
RESUME_PATH = None  # Set via --resume flag
DEFAULT_TEAM_ACCESS_CODE = os.getenv("TEAM_ACCESS_CODE")
TEAM_ACCESS_CODE = DEFAULT_TEAM_ACCESS_CODE

# ─── Helpers ───────────────────────────────────────────────────────────────────

class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = None
        self.details = []

    def ok(self, detail: str = ""):
        self.passed = True
        if detail:
            self.details.append(detail)
        return self

    def fail(self, error: str):
        self.passed = False
        self.error = error
        return self

    def info(self, detail: str):
        self.details.append(detail)
        return self


def get_or_create_user() -> str:
    """Sign in or sign up test user, return access token."""
    sb = create_client(settings.supabase_url, settings.supabase_service_key)
    try:
        res = sb.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        return res.session.access_token
    except Exception:
        res = sb.auth.admin.create_user({
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "email_confirm": True,
        })
        res2 = sb.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
        return res2.session.access_token


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def guess_mime_type(path: str) -> str:
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type or "application/octet-stream"


def error_payload(resp: httpx.Response) -> tuple[str, str | None]:
    try:
        detail = resp.json().get("detail")
        if isinstance(detail, dict):
            return detail.get("message", json.dumps(detail)), detail.get("code")
        if isinstance(detail, str):
            return detail, None
    except Exception:
        pass
    return resp.text, None


def create_conversation_or_fail(token: str, mode: str) -> tuple[str | None, str | None]:
    resp = httpx.post(f"{BASE_URL}/conversations", headers=headers(token), json={"mode": mode})
    if resp.status_code != 200:
        message, _ = error_payload(resp)
        return None, f"Status {resp.status_code} for mode={mode}: {message}"
    body = resp.json()
    conv_id = body.get("id")
    if not conv_id:
        return None, f"Missing id in response: {body}"
    return conv_id, None


def ensure_team_access(token: str, access_code: str | None) -> TestResult:
    r = TestResult("Team access verification")
    profile_resp = httpx.get(f"{BASE_URL}/profile", headers=headers(token))
    if profile_resp.status_code == 200:
        return r.ok("already verified")

    if profile_resp.status_code not in (401, 403):
        message, code = error_payload(profile_resp)
        return r.fail(f"Profile probe failed ({profile_resp.status_code}, {code}): {message}")

    message, code = error_payload(profile_resp)
    if code == "team_access_blocked":
        return r.fail(message)
    if code != "team_access_required":
        return r.fail(f"Unexpected auth response ({profile_resp.status_code}, {code}): {message}")
    if not access_code:
        return r.fail("Team access code required. Pass --access-code or set TEAM_ACCESS_CODE.")

    verify_resp = httpx.post(
        f"{BASE_URL}/access/verify",
        headers=headers(token),
        json={"code": access_code},
    )
    if verify_resp.status_code != 200:
        verify_message, verify_code = error_payload(verify_resp)
        return r.fail(f"Verification failed ({verify_resp.status_code}, {verify_code}): {verify_message}")

    body = verify_resp.json()
    return r.ok(f"verified version {body.get('current_version')}")


def parse_sse(text: str) -> list[dict]:
    """Parse SSE text into list of {event, data} dicts."""
    events = []
    current_event = "message"
    for line in text.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                events.append({"event": current_event, "data": data})
            except json.JSONDecodeError:
                pass
    return events


# ─── Tests ─────────────────────────────────────────────────────────────────────

def test_health(token: str, verbose: bool) -> TestResult:
    r = TestResult("GET /health")
    resp = httpx.get(f"{BASE_URL}/health")
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    body = resp.json()
    if body.get("status") != "ok":
        return r.fail(f"Unexpected body: {body}")
    return r.ok()


def test_create_conversation(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations")
    for mode in ["job_to_resume", "find_jobs"]:
        conv_id, error = create_conversation_or_fail(token, mode)
        if error:
            return r.fail(error)
        r.info(f"mode={mode} → id={conv_id[:8]}...")
    return r.ok()


def test_list_conversations(token: str, verbose: bool) -> TestResult:
    r = TestResult("GET /conversations")
    resp = httpx.get(f"{BASE_URL}/conversations", headers=headers(token))
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    body = resp.json()
    r.info(f"Found {len(body)} conversations")
    return r.ok()


def test_get_conversation(token: str, verbose: bool) -> TestResult:
    r = TestResult("GET /conversations/:id")
    # Create one first
    conv_id, error = create_conversation_or_fail(token, "job_to_resume")
    if error:
        return r.fail(error)

    resp = httpx.get(f"{BASE_URL}/conversations/{conv_id}", headers=headers(token))
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    body = resp.json()
    if body.get("id") != conv_id:
        return r.fail(f"Wrong conversation returned: {body.get('id')}")
    if "messages" not in body:
        return r.fail("Missing 'messages' key")
    r.info(f"Messages: {len(body['messages'])}, Documents: {len(body.get('documents', []))}")
    return r.ok()


def test_send_message_stream(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations/:id/messages (SSE stream)")
    # Create conversation
    conv_id, error = create_conversation_or_fail(token, "job_to_resume")
    if error:
        return r.fail(error)

    # Send message and read SSE stream
    r.info(f"Conversation: {conv_id[:8]}...")
    r.info("Sending: 'Hello, I'm looking for a software developer role.'")

    try:
        with httpx.stream("POST", f"{BASE_URL}/conversations/{conv_id}/messages",
                          headers=headers(token),
                          json={"content": "Hello, I'm looking for a software developer role."},
                          timeout=60.0) as resp:
            if resp.status_code != 200:
                return r.fail(f"Status {resp.status_code}")

            full_text = ""
            events_seen = set()
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    events_seen.add(line[7:].strip())
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "content" in data:
                            full_text += data["content"]
                    except json.JSONDecodeError:
                        pass

            if not full_text:
                return r.fail("No text content received from stream")

            r.info(f"Events: {', '.join(sorted(events_seen))}")
            r.info(f"Response length: {len(full_text)} chars")
            if verbose:
                r.info(f"Response: {full_text[:200]}...")

    except httpx.ReadTimeout:
        return r.fail("Stream timed out after 60s")
    except Exception as e:
        return r.fail(f"Stream error: {e}")

    return r.ok()


def test_small_talk_stream(token: str, verbose: bool) -> TestResult:
    r = TestResult("Small-talk stream avoids tools")
    conv_id, error = create_conversation_or_fail(token, "job_to_resume")
    if error:
        return r.fail(error)

    try:
        with httpx.stream(
            "POST",
            f"{BASE_URL}/conversations/{conv_id}/messages",
            headers=headers(token),
            json={"content": "Hello!"},
            timeout=60.0,
        ) as resp:
            if resp.status_code != 200:
                return r.fail(f"Status {resp.status_code}")

            full_text = ""
            events_seen = set()
            tool_status_events = []
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    events_seen.add(line[7:].strip())
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "content" in data:
                            full_text += data["content"]
                        if data.get("tool"):
                            tool_status_events.append(f"{data['tool']}:{data.get('state', 'unknown')}")
                    except json.JSONDecodeError:
                        pass

            if not full_text:
                return r.fail("No text content received from stream")
            if tool_status_events:
                return r.fail(f"Expected no tool status events, saw: {tool_status_events}")

            r.info(f"Events: {', '.join(sorted(events_seen)) or 'none'}")
            r.info(f"Response length: {len(full_text)} chars")
            if verbose:
                r.info(f"Response: {full_text[:200]}...")
    except httpx.ReadTimeout:
        return r.fail("Stream timed out after 60s")
    except Exception as e:
        return r.fail(f"Stream error: {e}")

    return r.ok()


def test_upload_file(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations/:id/upload")

    if not RESUME_PATH:
        r.info("Skipped (no --resume flag)")
        return r.ok("skipped")

    import os
    if not os.path.exists(RESUME_PATH):
        return r.fail(f"Resume file not found: {RESUME_PATH}")

    # Create find_jobs conversation
    conv_id, error = create_conversation_or_fail(token, "find_jobs")
    if error:
        return r.fail(error)

    # Upload file
    mime_type = guess_mime_type(RESUME_PATH)
    with open(RESUME_PATH, "rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/conversations/{conv_id}/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (os.path.basename(RESUME_PATH), f, mime_type)},
            timeout=30.0,
        )

    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")

    body = resp.json()
    if (
        guess_mime_type(RESUME_PATH) != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        and not body.get("gemini_file_uri")
    ):
        return r.fail(f"Missing gemini_file_uri: {body}")

    r.info(f"file_id: {body['file_id'][:8]}...")
    r.info(f"gemini_uri: {body['gemini_file_uri']}")
    return r.ok()


def test_upload_and_stream(token: str, verbose: bool) -> TestResult:
    r = TestResult("Upload + Stream (full Find Jobs flow)")

    if not RESUME_PATH:
        r.info("Skipped (no --resume flag)")
        return r.ok("skipped")

    import os
    if not os.path.exists(RESUME_PATH):
        return r.fail(f"Resume file not found: {RESUME_PATH}")

    # Create conversation
    conv_id, error = create_conversation_or_fail(token, "find_jobs")
    if error:
        return r.fail(error)
    r.info(f"Conversation: {conv_id[:8]}...")

    # Upload
    mime_type = guess_mime_type(RESUME_PATH)
    with open(RESUME_PATH, "rb") as f:
        upload_resp = httpx.post(
            f"{BASE_URL}/conversations/{conv_id}/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (os.path.basename(RESUME_PATH), f, mime_type)},
            timeout=30.0,
        )
    if upload_resp.status_code != 200:
        return r.fail(f"Upload failed: {upload_resp.status_code}: {upload_resp.text}")
    r.info(f"Upload OK: {upload_resp.json()['gemini_file_uri']}")

    # Stream message with file context
    r.info("Sending initial message with file context...")
    try:
        with httpx.stream("POST", f"{BASE_URL}/conversations/{conv_id}/messages",
                          headers=headers(token),
                          json={"content": "I've uploaded my resume. Please analyze it and help me find matching jobs."},
                          timeout=90.0) as resp:
            if resp.status_code != 200:
                return r.fail(f"Stream status {resp.status_code}")

            full_text = ""
            events_seen = set()
            tool_calls = []
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    events_seen.add(line[7:].strip())
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "content" in data:
                            full_text += data["content"]
                        if "tool" in data:
                            tool_calls.append(f"{data['tool']}:{data['state']}")
                    except json.JSONDecodeError:
                        pass

            if not full_text:
                return r.fail("No text content received")

            r.info(f"Events: {', '.join(sorted(events_seen))}")
            r.info(f"Tools: {', '.join(tool_calls) if tool_calls else 'none'}")
            r.info(f"Response: {len(full_text)} chars")
            if verbose:
                r.info(f"Text: {full_text[:300]}...")

    except httpx.ReadTimeout:
        return r.fail("Stream timed out after 90s")
    except Exception as e:
        return r.fail(f"Stream error: {e}")

    return r.ok()


def test_auth_required(token: str, verbose: bool) -> TestResult:
    r = TestResult("Auth required on protected endpoints")
    endpoints = [
        ("GET", "/conversations"),
        ("POST", "/conversations"),
        ("GET", "/conversations/fake-id"),
    ]
    for method, path in endpoints:
        resp = httpx.request(method, f"{BASE_URL}{path}",
                             headers={"Content-Type": "application/json"},
                             json={"mode": "job_to_resume"} if method == "POST" else None)
        if resp.status_code not in (401, 403):
            return r.fail(f"{method} {path} returned {resp.status_code}, expected 401/403")
        r.info(f"{method} {path} → {resp.status_code}")
    return r.ok()


def test_upload_validation(token: str, verbose: bool) -> TestResult:
    r = TestResult("Upload validation (bad file type)")
    conv_id, error = create_conversation_or_fail(token, "find_jobs")
    if error:
        return r.fail(error)

    # Try uploading a .txt file (not allowed)
    resp = httpx.post(
        f"{BASE_URL}/conversations/{conv_id}/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    if resp.status_code != 400:
        return r.fail(f"Expected 400, got {resp.status_code}: {resp.text}")
    r.info(f"Rejected .txt upload: {resp.json().get('detail', '')[:60]}")
    return r.ok()


def test_get_profile(token: str, verbose: bool) -> TestResult:
    r = TestResult("GET /profile")
    resp = httpx.get(f"{BASE_URL}/profile", headers=headers(token))
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    body = resp.json()
    for key in ("profile", "user_context", "uploaded_files", "generated_documents"):
        if key not in body:
            return r.fail(f"Missing '{key}' in response")
    if not body["profile"].get("email"):
        return r.fail("Missing email in profile")
    r.info(f"Context: {len(body['user_context'])}, Files: {len(body['uploaded_files'])}, Docs: {len(body['generated_documents'])}")
    return r.ok()


def test_update_profile(token: str, verbose: bool) -> TestResult:
    r = TestResult("PATCH /profile")
    resp = httpx.patch(f"{BASE_URL}/profile", headers=headers(token),
                       json={"full_name": "Test User"})
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    if resp.json().get("full_name") != "Test User":
        return r.fail(f"Unexpected response: {resp.json()}")
    r.info("Updated name to 'Test User'")
    return r.ok()


def test_delete_conversation(token: str, verbose: bool) -> TestResult:
    r = TestResult("DELETE /conversations/:id")
    conv_id, error = create_conversation_or_fail(token, "job_to_resume")
    if error:
        return r.fail(error)
    r.info(f"Created: {conv_id[:8]}...")
    del_resp = httpx.delete(f"{BASE_URL}/conversations/{conv_id}", headers=headers(token))
    if del_resp.status_code != 200:
        return r.fail(f"Delete status {del_resp.status_code}: {del_resp.text}")
    if del_resp.json().get("status") != "deleted":
        return r.fail(f"Unexpected response: {del_resp.json()}")
    get_resp = httpx.get(f"{BASE_URL}/conversations/{conv_id}", headers=headers(token))
    if get_resp.status_code != 404:
        return r.fail(f"Expected 404 after delete, got {get_resp.status_code}")
    r.info("Verified conversation deleted")
    return r.ok()


def test_bulk_delete(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations/bulk-delete")
    ids = []
    for _ in range(2):
        conv_id, error = create_conversation_or_fail(token, "job_to_resume")
        if error:
            return r.fail(error)
        ids.append(conv_id)
    r.info(f"Created {len(ids)} conversations")
    del_resp = httpx.post(f"{BASE_URL}/conversations/bulk-delete", headers=headers(token),
                          json={"conversation_ids": ids})
    if del_resp.status_code != 200:
        return r.fail(f"Status {del_resp.status_code}: {del_resp.text}")
    count = del_resp.json().get("deleted_count", 0)
    if count != 2:
        return r.fail(f"Expected deleted_count=2, got {count}")
    r.info(f"Deleted {count} conversations")
    return r.ok()


# ─── Runner ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_health,
    test_auth_required,
    test_create_conversation,
    test_list_conversations,
    test_get_conversation,
    test_upload_validation,
    test_small_talk_stream,
    test_upload_file,
    test_send_message_stream,
    test_upload_and_stream,
    test_get_profile,
    test_update_profile,
    test_delete_conversation,
    test_bulk_delete,
]

TEST_MAP = {fn.__name__.replace("test_", ""): fn for fn in ALL_TESTS}


def main():
    parser = argparse.ArgumentParser(description="Backend API tests")
    parser.add_argument("--test", help="Run specific test (e.g. 'upload', 'stream')")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full response bodies")
    parser.add_argument("--resume", help="Path to resume PDF for upload tests")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--access-code", default=DEFAULT_TEAM_ACCESS_CODE, help="Team access code if the gate is enabled")
    args = parser.parse_args()

    global RESUME_PATH, BASE_URL, TEAM_ACCESS_CODE
    RESUME_PATH = args.resume
    BASE_URL = args.base_url.rstrip("/")
    TEAM_ACCESS_CODE = args.access_code

    # Check server is running
    try:
        httpx.get(f"{BASE_URL}/health", timeout=3.0)
    except httpx.ConnectError:
        print(f"\n  Backend not running at {BASE_URL}. Start it first.\n")
        sys.exit(1)

    # Get auth token
    print("\n  Setting up test user...", end=" ")
    try:
        token = get_or_create_user()
        print(f"OK ({TEST_EMAIL})")
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)

    access_result = ensure_team_access(token, TEAM_ACCESS_CODE)
    icon = "PASS" if access_result.passed else "FAIL"
    color = "\033[32m" if access_result.passed else "\033[31m"
    reset = "\033[0m"
    print(f"  {color}{icon}{reset}  {access_result.name}")
    for detail in access_result.details:
        print(f"        {detail}")
    if access_result.error:
        print(f"        {color}Error: {access_result.error}{reset}")
    print()
    if not access_result.passed:
        sys.exit(1)

    # Select tests
    if args.test:
        matches = [fn for name, fn in TEST_MAP.items() if args.test in name]
        if not matches:
            print(f"\n  No test matching '{args.test}'. Available: {', '.join(TEST_MAP.keys())}\n")
            sys.exit(1)
        tests = matches
    else:
        tests = ALL_TESTS

    # Run
    print(f"\n  Running {len(tests)} test(s)...\n")
    results = []
    for test_fn in tests:
        start = time.time()
        result = test_fn(token, args.verbose)
        elapsed = time.time() - start

        icon = "PASS" if result.passed else "FAIL"
        color = "\033[32m" if result.passed else "\033[31m"
        reset = "\033[0m"

        print(f"  {color}{icon}{reset}  {result.name} ({elapsed:.1f}s)")
        for detail in result.details:
            print(f"        {detail}")
        if result.error:
            print(f"        {color}Error: {result.error}{reset}")
        print()
        results.append(result)

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    color = "\033[32m" if failed == 0 else "\033[31m"
    reset = "\033[0m"
    print(f"  {color}{passed}/{len(results)} passed{reset}", end="")
    if failed:
        print(f" ({failed} failed)")
    else:
        print()
    print()

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
