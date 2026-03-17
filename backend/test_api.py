#!/usr/bin/env python3
"""Backend API test runner. Tests all endpoints with real auth and streaming.

Usage:
    python test_api.py                    # Run all tests
    python test_api.py --test upload      # Run specific test
    python test_api.py --verbose          # Show full response bodies
"""

import argparse
import json
import sys
import time
import httpx
from config import settings
from supabase import create_client

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "test-api@example.com"
TEST_PASSWORD = "TestPass123!"
RESUME_PATH = None  # Set via --resume flag

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
        resp = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                          json={"mode": mode})
        if resp.status_code != 200:
            return r.fail(f"Status {resp.status_code} for mode={mode}: {resp.text}")
        body = resp.json()
        if not body.get("id"):
            return r.fail(f"Missing id in response: {body}")
        r.info(f"mode={mode} → id={body['id'][:8]}...")
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
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "job_to_resume"})
    conv_id = create.json()["id"]

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
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "job_to_resume"})
    conv_id = create.json()["id"]

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


def test_upload_file(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations/:id/upload")

    if not RESUME_PATH:
        r.info("Skipped (no --resume flag)")
        return r.ok("skipped")

    import os
    if not os.path.exists(RESUME_PATH):
        return r.fail(f"Resume file not found: {RESUME_PATH}")

    # Create find_jobs conversation
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "find_jobs"})
    conv_id = create.json()["id"]

    # Upload file
    with open(RESUME_PATH, "rb") as f:
        resp = httpx.post(
            f"{BASE_URL}/conversations/{conv_id}/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (os.path.basename(RESUME_PATH), f, "application/pdf")},
            timeout=30.0,
        )

    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")

    body = resp.json()
    if not body.get("gemini_file_uri"):
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
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "find_jobs"})
    conv_id = create.json()["id"]
    r.info(f"Conversation: {conv_id[:8]}...")

    # Upload
    with open(RESUME_PATH, "rb") as f:
        upload_resp = httpx.post(
            f"{BASE_URL}/conversations/{conv_id}/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (os.path.basename(RESUME_PATH), f, "application/pdf")},
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
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "find_jobs"})
    conv_id = create.json()["id"]

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


# ─── Runner ────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_health,
    test_auth_required,
    test_create_conversation,
    test_list_conversations,
    test_get_conversation,
    test_upload_validation,
    test_upload_file,
    test_send_message_stream,
    test_upload_and_stream,
]

TEST_MAP = {fn.__name__.replace("test_", ""): fn for fn in ALL_TESTS}


def main():
    parser = argparse.ArgumentParser(description="Backend API tests")
    parser.add_argument("--test", help="Run specific test (e.g. 'upload', 'stream')")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full response bodies")
    parser.add_argument("--resume", help="Path to resume PDF for upload tests")
    args = parser.parse_args()

    global RESUME_PATH
    RESUME_PATH = args.resume

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
